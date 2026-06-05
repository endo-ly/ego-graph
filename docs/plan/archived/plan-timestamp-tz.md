# Plan: Backend ツールレスポンスのタイムスタンプTZ対応

全ツールのタイムスタンプフィールドを環境変数 `TIMEZONE` に基づいてUTC→ローカルTZ変換し、フィールド名 `_utc` → `_at` に統一、型も `str` → `datetime` に統一する。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- Parquet ストレージ層は UTC のまま変更しない。変換は SQL 出力時にのみ行う
- SQL 側で DuckDB の `AT TIME ZONE` を使い、`params.tz_name`（既存の `TIMEZONE` 環境変数由来）を f-string で注入
- フィールド名: `_utc` → `_at`（値が UTC ではないため名前の矛盾を解消）
- 型統一: `str` で返っていたフィールド（YouTube, GitHub）を `datetime` に統一
- `get_listening_stats` / `get_watching_stats` / `get_activity_stats` の `period` は既存でTZ対応済みのため変更不要
- `data_query`（生SQLツール）は任意のカラムを返せるため対象外

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 変更内容 |
|---|---|
| Spotify `get_top_tracks` | `played_at_utc` → `played_at`, TZ変換追加 |
| YouTube `get_youtube_watch_events` | `watched_at_utc` → `watched_at`, TZ変換追加, `str`→`datetime` |
| Browser `get_page_views` | `started_at_utc`→`started_at`, `ended_at_utc`→`ended_at`, TZ変換追加 |
| GitHub `get_pull_requests` | `created_at_utc`→`created_at`, `updated_at_utc`→`updated_at`, `closed_at_utc`→`closed_at`, `merged_at_utc`→`merged_at`, TZ変換, 型統一 |
| GitHub `get_commits` | `committed_at_utc` → `committed_at`, TZ変換, 型統一 |
| GitHub `get_repositories` | `created_at_utc`→`created_at`, `updated_at_utc`→`updated_at`, `pushed_at_utc`→`pushed_at`, TZ変換, 型統一 |
| GitHub `get_repo_summary_stats` | `last_pr_updated_at`, `last_commit_at` → TZ変換追加, 型統一（フィールド名はすでに `_at`） |

## Step 0: Worktree 作成

`worktree-create` スキルで `feat/timestamp-tz` ブランチの Worktree を作成する。

---

## Step 1: Spotify — `get_top_tracks` の TZ 対応 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_returns_top_tracks` 更新 | フィールド名 `played_at_utc` → `played_at` でアサート |
| `test_top_tracks_with_jst_timezone` (新規) | JSTで`get_top_tracks`を実行し、返り値の`played_at`が`+09:00`のdatetimeであることを検証 |

### GREEN: 実装

**queries.py** `get_top_tracks`: `list(played_at_utc ...)` にTZ変換を追加

```python
# 変更前
list(played_at_utc ORDER BY played_at_utc) as played_at_utc

# 変更後 (f-stringでtz_nameを注入)
list(
    played_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}'
    ORDER BY played_at_utc
) as played_at
```

**data.py** `TopTrackResponse`: `played_at_utc: list[datetime]` → `played_at: list[datetime]`

### コミット

`refactor(backend): add timezone conversion to spotify get_top_tracks timestamps`

フィールド名変更とTZ変換を一括。

---

## Step 2: YouTube — `get_youtube_watch_events` の TZ 対応 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_get_watch_events` 更新 | フィールド名 `watched_at_utc` → `watched_at`、型 `str`→`datetime` でアサート |
| `test_watch_events_with_jst_timezone` (新規) | JSTで実行し`watched_at`が`+09:00`のdatetimeであることを検証 |

### GREEN: 実装

**youtube_queries.py** `get_watch_events`: CTE/最終SELECTでTZ変換

```python
# enriched_watch_events CTE 内
w.watched_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS watched_at,

# 最終SELECT
watched_at
FROM enriched_watch_events
```

**data.py** `WatchEventResponse`: `watched_at_utc: str` → `watched_at: datetime`

### コミット

`refactor(backend): add timezone conversion to youtube watch_events timestamps`

---

## Step 3: Browser History — `get_page_views` の TZ 対応 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_get_page_views` 更新 | `started_at_utc`→`started_at`, `ended_at_utc`→`ended_at` でアサート |
| `test_page_views_with_jst_timezone` (新規) | JSTで実行し`started_at`/`ended_at`が`+09:00`のdatetimeであることを検証 |

### GREEN: 実装

**browser_history_queries.py** `get_page_views`: SELECT句でTZ変換

```python
started_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS started_at,
ended_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS ended_at,
```

**data.py** `PageViewResponse`: `started_at_utc: datetime` → `started_at: datetime`, `ended_at_utc: datetime` → `ended_at: datetime`

### コミット

`refactor(backend): add timezone conversion to browser_history page_views timestamps`

---

## Step 4: GitHub — 全ツールの TZ 対応 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| PRテスト全件更新 | `created_at_utc`→`created_at`, `updated_at_utc`→`updated_at`, `closed_at_utc`→`closed_at`, `merged_at_utc`→`merged_at`、型`datetime`でアサート |
| Commitテスト更新 | `committed_at_utc`→`committed_at`, 型`datetime`でアサート |
| Repositoryテスト更新 | `created_at_utc`→`created_at`, `updated_at_utc`→`updated_at`, `pushed_at_utc`→`pushed_at`、型`datetime`でアサート |
| RepoSummaryStatsテスト更新 | `last_pr_updated_at`, `last_commit_at` 型`datetime`でアサート |
| `test_prs_with_jst_timezone` (新規) | JSTでPR取得し`created_at`等が`+09:00`であることを検証 |

### GREEN: 実装

**github_queries.py**: 4関数のSELECT句全タイムスタンプにTZ変換追加。全クエリに `{params.tz_name}` 注入。

```python
# 例: get_pull_requests
created_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS created_at,
updated_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS updated_at,
closed_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS closed_at,
merged_at_utc::TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE '{params.tz_name}' AS merged_at,
```

`get_repo_summary_stats` の `last_pr_updated_at`, `last_commit_at` は `MAX(...)` の結果だが、同様にTZ変換を追加する。`last_pr_updated_at` の `NULL` はCTEの固定値のため変換不要。

**github.py** 全スキーマのタイムスタンプフィールド:
- フィールド名 `_utc` → `_at`
- 型 `str` → `datetime`
- `last_pr_updated_at: str | None` → `last_pr_updated_at: datetime | None`
- `last_commit_at: str | None` → `last_commit_at: datetime | None`

### コミット

`refactor(backend): add timezone conversion to github all-tool timestamps`

---

## Step 5: 動作確認

```bash
# 全backendテスト
uv run pytest egograph/backend/tests/ -v

# Lint
uv run ruff check egograph/backend/

# スキーマバリデーション確認
uv run python -c "from backend.api.schemas.data import TopTrackResponse, WatchEventResponse, PageViewResponse; print('OK')"
uv run python -c "from backend.api.schemas.github import PullRequestResponse, CommitResponse, RepositoryResponse, RepoSummaryStatsResponse; print('OK')"
```

---

## Step 6: PR 作成

`pr-review-back-workflow` スキルでレビュー → 修正 → PR作成。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egograph/backend/infrastructure/database/queries.py` | 変更 | `get_top_tracks`: `played_at_utc` → `played_at` + TZ変換 |
| `egograph/backend/infrastructure/database/youtube_queries.py` | 変更 | `watched_at_utc` → `watched_at` + TZ変換, 型統一 |
| `egograph/backend/infrastructure/database/browser_history_queries.py` | 変更 | `started_at_utc`→`started_at`, `ended_at_utc`→`ended_at` + TZ変換 |
| `egograph/backend/infrastructure/database/github_queries.py` | 変更 | 4関数全タイムスタンプフィールド名変更+TZ変換+型統一 |
| `egograph/backend/api/schemas/data.py` | 変更 | `TopTrackResponse`, `WatchEventResponse`, `PageViewResponse` フィールド名変更+型統一 |
| `egograph/backend/api/schemas/github.py` | 変更 | 4クラス全タイムスタンプフィールド名変更+型統一 |
| `egograph/backend/tests/conftest.py` | 変更 | 一部フィクスチャのカラム名調整（必要な場合のみ） |
| `egograph/backend/tests/unit/tools/spotify/test_stats.py` | 変更 | mockデータ・アサーションのフィールド名更新 |
| `egograph/backend/tests/unit/database/test_queries.py` | 変更 | アサーションのフィールド名更新 |
| `egograph/backend/tests/unit/database/test_browser_history_queries.py` | 変更 | アサーションのフィールド名更新 |
| `egograph/backend/tests/unit/database/*.py` (GitHub/Youtube) | 変更 | アサーションのフィールド名+型更新 |
| `egograph/backend/tests/unit/tools/*.py` (GitHub/Youtube) | 変更 | mockデータのフィールド名+型更新 |
| `egograph/backend/tests/integration/test_api_data.py` | 変更 | アサーションのフィールド名更新 |
| `egograph/backend/tests/integration/test_compacted_parquet_reads.py` | 変更 | アサーションのフィールド名更新 |

## コミット分割

1. `refactor(backend): add timezone conversion to spotify get_top_tracks timestamps`
   - queries.py, data.py, test_stats.py, test_queries.py, test_api_data.py

2. `refactor(backend): add timezone conversion to youtube watch_events timestamps`
   - youtube_queries.py, data.py (WatchEventResponse), 該当テストファイル

3. `refactor(backend): add timezone conversion to browser_history page_views timestamps`
   - browser_history_queries.py, data.py (PageViewResponse), 該当テストファイル

4. `refactor(backend): add timezone conversion to github all-tool timestamps`
   - github_queries.py, github.py, 該当テストファイル群

## テストケース一覧（全 22 件）

### Spotify get_top_tracks (4)
1. `test_returns_top_tracks` — `played_at` フィールド存在・型・件数
2. `test_respects_limit_parameter` — 既存（影響なしだがフィールド名追随）
3. `test_filters_by_date_range` — 既存（影響なしだがフィールド名追随）
4. `test_top_tracks_with_jst_timezone` — **新規**: JSTで`played_at`が`+09:00`のdatetime配列であること

### YouTube watch_events (3)
5. `test_get_watch_events` — `watched_at` フィールド名+型 `datetime`
6. `test_watch_events_order` — 既存追随
7. `test_watch_events_with_jst_timezone` — **新規**: JSTで`watched_at`が`+09:00`であること

### Browser History page_views (3)
8. `test_get_page_views` — `started_at`, `ended_at` フィールド名
9. `test_page_views_filter` — 既存追随
10. `test_page_views_with_jst_timezone` — **新規**: JSTで`started_at`/`ended_at`が`+09:00`であること

### GitHub Pull Requests (4)
11. `test_get_pull_requests` — 全タイムスタンプフィールド名+型
12. `test_pr_state_filter` — 既存追随
13. `test_pr_owner_filter` — 既存追随
14. `test_pull_requests_with_jst_timezone` — **新規**: JSTで各timestampが`+09:00`であること

### GitHub Commits (2)
15. `test_get_commits` — `committed_at` フィールド名+型
16. `test_commits_with_jst_timezone` — **新規**: JSTで`committed_at`が`+09:00`であること

### GitHub Repositories (2)
17. `test_get_repositories` — `created_at`, `updated_at`, `pushed_at` フィールド名+型
18. `test_repositories_with_jst_timezone` — **新規**: JSTで各timestampが`+09:00`であること

### GitHub RepoSummaryStats (2)
19. `test_get_repo_summary_stats` — `last_pr_updated_at`, `last_commit_at` 型変更
20. `test_repo_summary_with_jst_timezone` — **新規**: JSTで集計timestampが`+09:00`であること

### API 統合テスト (2)
21. `test_get_top_tracks_success` — `played_at_utc`→`played_at` アサーション更新
22. `test_get_watch_events_success` (新規or既存) — `watched_at` アサーション更新

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | Worktree 作成 | ~0 行 |
| Step 1 | Spotify SQL + Schema + テスト | ~40 行 |
| Step 2 | YouTube SQL + Schema + テスト | ~50 行 |
| Step 3 | Browser History SQL + Schema + テスト | ~40 行 |
| Step 4 | GitHub SQL + Schema + テスト | ~120 行 |
| Step 5 | 動作確認 | ~0 行 |
| Step 6 | PR 作成 | ~0 行 |
| **合計** | | **~250 行** |
