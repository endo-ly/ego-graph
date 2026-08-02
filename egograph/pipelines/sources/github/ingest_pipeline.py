"""GitHub作業ログ取り込みパイプラインのオーケストレーション。"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from pipelines.sources.common.config import Config
from pipelines.sources.github.collector import GitHubWorklogCollector
from pipelines.sources.github.storage import GitHubWorklogStorage
from pipelines.sources.github.transform import (
    transform_commits_to_events,
    transform_prs_to_master,
    transform_repository,
)

logger = logging.getLogger(__name__)


def _parse_iso_utc(value: str | None) -> datetime | None:
    """ISO8601文字列をUTC datetimeに変換する。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def _migrate_state(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """旧state形式を新形式に移行する。

    旧形式: {"cursor_utc": "...", "total_repos": N}
    新形式: {"github_login": "...", "repos": {"owner/repo": {"cursor_utc": "..."}}}

    旧形式のcursor_utcは全リポジトリ共通の初期cursorとして扱う。
    """
    if state is None:
        return {"github_login": None, "repos": {}}

    # 新形式はそのまま返す
    if "repos" in state:
        return state

    # 旧形式からの移行
    cursor_utc = state.get("cursor_utc") or state.get("last_ingested_at")
    migrated: dict[str, Any] = {"github_login": None, "repos": {}}
    if cursor_utc:
        migrated["global_cursor_utc"] = cursor_utc
        logger.info(
            "Migrating legacy state cursor to global_cursor_utc: %s", cursor_utc
        )
    return migrated


def _resolve_since_iso(
    repo_full_name: str,
    state: dict[str, Any],
    backfill_days: int,
) -> str:
    """リポジトリ単位で増分取得開始時刻を決定する。

    優先順位:
    1. 該当リポジトリのcursor_utc
    2. 旧形式からの移行cursor (global_cursor_utc)
    3. backfill_days に基づくフルフェッチ

    Args:
        repo_full_name: リポジトリのフルネーム (例: "owner/repo")
        state: 現在のstate（新形式）
        backfill_days: フルフェッチ時の遡及日数

    Returns:
        ISO8601形式の開始時刻文字列
    """
    repos_state = state.get("repos", {})
    repo_cursor = repos_state.get(repo_full_name, {}).get("cursor_utc")

    if repo_cursor:
        logger.info("Using incremental cursor for %s: %s", repo_full_name, repo_cursor)
        return repo_cursor

    # 旧形式からの移行cursor
    global_cursor = state.get("global_cursor_utc")
    if global_cursor:
        logger.info(
            "Using migrated global cursor for %s: %s", repo_full_name, global_cursor
        )
        return global_cursor

    start = datetime.now(timezone.utc) - timedelta(days=backfill_days)
    since = start.isoformat()
    logger.info("No cursor for %s. Backfill mode since=%s", repo_full_name, since)
    return since


def _build_ingest_state(
    state: dict[str, Any],
    target_repos: list[str],
    repo_cursors: dict[str, str],
    failed_repos: set[str],
    github_login: str,
    updated_at: str,
) -> dict[str, Any]:
    """保存完了結果から次回実行用のstateを構築する。

    失敗したリポジトリは新しいcursorを持たず、既存cursorだけを維持する。
    これにより、未保存データを次回実行で再取得できる。
    """
    existing_repos = state.get("repos", {})
    repos_state: dict[str, dict[str, str]] = {}

    for repo_full_name in target_repos:
        if repo_full_name in failed_repos:
            existing_cursor = existing_repos.get(repo_full_name, {}).get("cursor_utc")
            if existing_cursor:
                repos_state[repo_full_name] = {"cursor_utc": existing_cursor}
            continue

        cursor = repo_cursors.get(repo_full_name)
        if cursor:
            repos_state[repo_full_name] = {"cursor_utc": cursor}

    return {
        "github_login": github_login,
        "repos": repos_state,
        "updated_at": updated_at,
    }


def run_pipeline(config: Config) -> None:
    """GitHub作業ログインジェストの実行ロジック。

    Args:
        config: 設定情報（GitHubとR2を含む）

    Raises:
        ValueError: 設定が不足している場合
        RuntimeError: パイプラインの実行に失敗した場合
    """
    if not config.github_worklog:
        raise ValueError("GitHub worklog configuration is required")
    if not config.duckdb or not config.duckdb.r2:
        raise ValueError("R2 configuration is required for this pipeline")

    github_conf = config.github_worklog
    r2_conf = config.duckdb.r2

    logger.info("=" * 60)
    logger.info("GitHub Worklog Ingestion Pipeline")
    logger.info("GitHub User: [redacted]")
    if github_conf.target_repos:
        logger.info("Target Repos: %d specified", len(github_conf.target_repos))
    else:
        logger.info("Target Repos: all personal repositories")
    logger.info("=" * 60)

    # StorageとCollectorを初期化
    storage = GitHubWorklogStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )

    collector = GitHubWorklogCollector(
        token=github_conf.token.get_secret_value(),
        github_login=github_conf.github_login,
    )

    # 状態を取得・移行
    raw_state = storage.get_ingest_state()
    state = _migrate_state(raw_state)

    # github_login 変更検知: 不一致時はstateをリセット
    stored_login = state.get("github_login")
    if stored_login is not None and stored_login != github_conf.github_login:
        logger.warning(
            "GitHub login changed: %s -> %s. Resetting state for full backfill.",
            stored_login,
            github_conf.github_login,
        )
        state = {"github_login": github_conf.github_login, "repos": {}}
    elif not stored_login:
        state["github_login"] = github_conf.github_login

    # ターゲットリポジトリを決定
    if github_conf.target_repos:
        target_repos = github_conf.target_repos
        logger.info("Processing %d specified repositories", len(target_repos))
    else:
        all_repos = collector.get_user_repositories()
        target_repos = [r["full_name"] for r in all_repos]
        logger.info("Found %d personal repositories", len(target_repos))

    if not target_repos:
        logger.warning("No repositories to process. Exiting.")
        return

    # 各リポジトリを処理
    total_prs = 0
    total_new_pr_events = 0
    total_duplicate_pr_events = 0
    total_commits = 0
    total_new_commits = 0
    total_duplicate_commits = 0
    total_failed_records = 0
    total_failed_fatal_api_calls = 0
    total_failed_enrichment_api_calls = 0

    all_commits_data = []
    # リポジトリごとのcursorを追跡
    repo_cursors: dict[str, str] = {}
    failed_repos: set[str] = set()

    for repo_full_name in target_repos:
        try:
            owner, repo = repo_full_name.split("/", 1)
            logger.info("Processing repository: %s", repo_full_name)

            # リポジトリ単位のcursorを解決
            since_iso = _resolve_since_iso(
                repo_full_name, state, github_conf.backfill_days
            )

            # Repository情報を取得
            repo_info = collector.get_repository(owner, repo)
            repo_transformed = transform_repository(repo_info, github_conf.github_login)
            if repo_transformed:
                repo_saved = storage.save_repo_master([repo_transformed], owner, repo)
                if repo_saved is None:
                    logger.error(
                        "Failed to save repository master for %s", repo_full_name
                    )
                    total_failed_records += 1
                    failed_repos.add(repo_full_name)
            else:
                logger.info("Skipping non-personal repo: %s", repo_full_name)
                continue

            # PR一覧を取得
            prs = collector.get_pull_requests(owner, repo, since=since_iso)
            logger.info("Found %d PRs in %s", len(prs), repo_full_name)

            # 各PRのレビュー数を取得
            for pr in prs:
                pr_number = pr.get("number")
                if pr_number:
                    try:
                        reviews = collector.get_pr_reviews(owner, repo, pr_number)
                        pr["reviews_count"] = len(reviews)
                    except Exception as e:
                        pr_number_str = str(pr_number)
                        logger.warning(
                            "Failed to fetch reviews for PR #%s: %s",
                            pr_number_str,
                            e,
                        )
                        pr["reviews_count"] = 0
                        total_failed_enrichment_api_calls += 1

            # リポジトリ単位のcursor候補を追跡
            max_cursor_candidate: datetime | None = None
            for pr in prs:
                dt = _parse_iso_utc(pr.get("updated_at"))
                if dt and (max_cursor_candidate is None or dt > max_cursor_candidate):
                    max_cursor_candidate = dt

            total_prs += len(prs)

            # PRイベントを保存
            if prs:
                prs_transformed = transform_prs_to_master(prs, github_conf.github_login)
                total_failed_records += len(prs) - len(prs_transformed)
                if prs_transformed:
                    pr_events_by_month = _group_pr_events_by_month(prs_transformed)
                    for (year, month), pr_events in pr_events_by_month.items():
                        stats = storage.save_pr_events_parquet_with_stats(
                            pr_events,
                            year,
                            month,
                        )
                        if stats["failed"] > 0:
                            logger.error(
                                "Failed to save pull request events for %d-%02d",
                                year,
                                month,
                            )
                            total_failed_records += stats["failed"]
                            failed_repos.add(repo_full_name)
                        else:
                            logger.info(
                                (
                                    "Saved pull request events for %d-%02d "
                                    "(fetched=%d new=%d duplicates=%d)"
                                ),
                                year,
                                month,
                                stats["fetched"],
                                stats["new"],
                                stats["duplicates"],
                            )
                        total_new_pr_events += stats["new"]
                        total_duplicate_pr_events += stats["duplicates"]

                # PR生データを保存
                raw_pr_saved = storage.save_raw_prs(prs, owner, repo)
                if raw_pr_saved is None:
                    logger.error("Failed to save raw PRs for %s", repo_full_name)
                    total_failed_records += len(prs)
                    failed_repos.add(repo_full_name)

            # Repository Commitsを取得
            commits = collector.get_repository_commits(owner, repo, since=since_iso)
            logger.info("Found %d commits in %s", len(commits), repo_full_name)

            # 各Commitの詳細を取得（変更量メタデータ用）
            enriched_commits = []
            detail_failures = 0
            details_requested = 0
            details_enabled = github_conf.fetch_commit_details
            max_detail_requests = github_conf.max_commit_detail_requests_per_repo
            detail_budget_exceeded_logged = False
            for commit in commits:
                sha = commit.get("sha")
                if not sha or not details_enabled:
                    enriched_commits.append(commit)
                    continue

                if details_requested >= max_detail_requests:
                    if not detail_budget_exceeded_logged:
                        logger.warning(
                            (
                                "Commit detail request budget exceeded for %s "
                                "(max=%d); skipping remaining detail fetches"
                            ),
                            repo_full_name,
                            max_detail_requests,
                        )
                        detail_budget_exceeded_logged = True
                    enriched_commits.append(commit)
                    continue

                details_requested += 1
                try:
                    detail = collector.get_commit_detail(owner, repo, sha)
                    commit_with_detail = {**commit, **detail}
                    enriched_commits.append(commit_with_detail)
                except Exception as e:
                    logger.warning("Failed to fetch detail for commit %s: %s", sha, e)
                    detail_failures += 1
                    total_failed_enrichment_api_calls += 1
                    enriched_commits.append(commit)

            if details_enabled and detail_failures > 0:
                logger.warning(
                    "Commit detail fetch failures for %s: %d/%d",
                    repo_full_name,
                    detail_failures,
                    details_requested,
                )

            # Commitsを変換
            commits_transformed = transform_commits_to_events(
                enriched_commits, repo_full_name
            )
            total_failed_records += len(enriched_commits) - len(commits_transformed)
            all_commits_data.extend(commits_transformed)
            total_commits += len(commits_transformed)

            for commit in commits_transformed:
                dt = _as_datetime(commit.get("committed_at_utc"))
                if dt and (max_cursor_candidate is None or dt > max_cursor_candidate):
                    max_cursor_candidate = dt

            # Commit生データを保存
            if commits:
                raw_commits_saved = storage.save_raw_commits(commits, owner, repo)
                if raw_commits_saved is None:
                    logger.error("Failed to save raw commits for %s", repo_full_name)
                    total_failed_records += len(commits)
                    failed_repos.add(repo_full_name)

            # リポジトリのcursorを記録
            if repo_full_name not in failed_repos:
                if max_cursor_candidate is not None:
                    repo_cursors[repo_full_name] = max_cursor_candidate.isoformat()
                else:
                    now_utc = datetime.now(timezone.utc)
                    repo_cursors[repo_full_name] = now_utc.isoformat()

        except Exception:
            logger.exception("Failed to process repository %s", repo_full_name)
            total_failed_fatal_api_calls += 1
            failed_repos.add(repo_full_name)
            continue

    logger.info("Total collected: %d PRs, %d commits", total_prs, total_commits)

    # Commitイベントを年月でグループ化して保存
    commits_by_month = _group_commits_by_month(all_commits_data)

    for (year, month), commits in commits_by_month.items():
        contributing_repos = {
            commit["repo_full_name"]
            for commit in commits
            if commit.get("repo_full_name")
        }
        try:
            stats = storage.save_commits_parquet_with_stats(commits, year, month)
        except Exception:
            logger.exception("Failed to save commits Parquet for %d-%02d", year, month)
            failed_repos.update(contributing_repos)
            total_failed_records += len(commits)
            continue

        if stats["failed"] > 0:
            logger.error("Failed to save commits Parquet for %d-%02d", year, month)
            failed_repos.update(contributing_repos)
        else:
            logger.info(
                "Saved commits for %d-%02d (fetched=%d new=%d duplicates=%d)",
                year,
                month,
                stats["fetched"],
                stats["new"],
                stats["duplicates"],
            )
        total_new_commits += stats["new"]
        total_duplicate_commits += stats["duplicates"]
        total_failed_records += stats["failed"]

    logger.info(
        (
            "Ingest stats: prs_fetched=%d prs_new=%d prs_duplicates=%d "
            "commits_fetched=%d commits_new=%d commits_duplicates=%d "
            "failed_records=%d failed_api=%d failed_repos=%d"
        ),
        total_prs,
        total_new_pr_events,
        total_duplicate_pr_events,
        total_commits,
        total_new_commits,
        total_duplicate_commits,
        total_failed_records,
        total_failed_fatal_api_calls,
        len(failed_repos),
    )
    logger.info("Ingest enrichment API failures: %d", total_failed_enrichment_api_calls)

    # 状態を更新（失敗リポジトリのcursorは更新しない）
    now_utc = datetime.now(timezone.utc).isoformat()
    new_state = _build_ingest_state(
        state,
        target_repos,
        repo_cursors,
        failed_repos,
        github_conf.github_login,
        now_utc,
    )

    try:
        storage.save_ingest_state(new_state)
    except Exception as exc:
        logger.exception("Failed to save GitHub ingest state")
        raise RuntimeError("Failed to save GitHub ingest state") from exc

    if failed_repos:
        logger.warning(
            "Pipeline had failures. State partially updated (failed repos excluded)."
        )
        raise RuntimeError(
            f"GitHub ingest failed for repositories: {', '.join(sorted(failed_repos))}"
        )

    logger.info("Pipeline completed successfully!")


def _as_datetime(value: Any) -> datetime | None:
    """datetime / ISO 8601 文字列を UTC aware datetime に変換する。

    不正な文字列・naive datetime は None を返し、非 UTC 書き込みを避ける。
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    return None


def _group_commits_by_month(
    commits: list[dict[str, Any]],
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """コミットイベントを年月でグループ化する。

    Args:
        commits: コミットイベントのリスト

    Returns:
        年月をキーとしたコミットリストの辞書
    """
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

    for commit in commits:
        committed_date = commit.get("committed_at_utc")
        if committed_date:
            try:
                dt = _as_datetime(committed_date)
                if dt is None:
                    raise ValueError(f"invalid date: {committed_date}")
                grouped[(dt.year, dt.month)].append(commit)
            except (ValueError, AttributeError) as e:
                logger.warning("Failed to parse date %s: %s", committed_date, e)
        else:
            commit_id = commit.get("commit_event_id", "unknown")
            logger.warning(
                "Commit %s has no committed_at_utc; skipping month grouping",
                commit_id,
            )

    return grouped


def _group_pr_events_by_month(
    pr_events: list[dict[str, Any]],
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

    for pr_event in pr_events:
        updated_date = pr_event.get("updated_at_utc")
        if updated_date:
            try:
                dt = _as_datetime(updated_date)
                if dt is None:
                    raise ValueError(f"invalid date: {updated_date}")
                grouped[(dt.year, dt.month)].append(pr_event)
            except (ValueError, AttributeError) as e:
                pr_key = pr_event.get("pr_key", "unknown")
                logger.warning(
                    "Failed to parse PR updated_at_utc %s for %s: %s",
                    updated_date,
                    pr_key,
                    e,
                )
        else:
            pr_key = pr_event.get("pr_key", "unknown")
            logger.warning(
                "Pull request event %s has no updated_at_utc; skipping", pr_key
            )

    return grouped
