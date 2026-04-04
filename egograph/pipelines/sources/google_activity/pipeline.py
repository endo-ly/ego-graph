import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .collector import MyActivityCollector
from .config import AccountConfig
from .storage import YouTubeStorage
from .youtube_api import QuotaExceededError, YouTubeAPIClient

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """パイプライン実行結果。

    Attributes:
        success: 成功した場合はTrue
        account_id: アカウントID
        collected_count: コレクターが取得したアイテム数
        saved_count: 保存したアイテム数
        error: 失敗した場合のエラー情報
    """

    success: bool
    account_id: str
    collected_count: int
    saved_count: int
    error: str | None = None


async def run_account_pipeline(
    account_config: AccountConfig,
    storage: YouTubeStorage,
    transform: Any,
    after_timestamp: datetime,
    max_items: int,
) -> PipelineResult:
    """単一アカウントのパイプラインを実行する。

    Args:
        account_config: アカウント設定
        storage: ストレージインスタンス
        transform: データ変換モジュール
        after_timestamp: この時刻以降の視聴履歴のみ収集
        max_items: 収集する最大アイテム数

    Returns:
        PipelineResult: 実行結果を含むデータクラス

    プロセス:
        1. インジェスト状態を取得（latest_watched_at）
        2. MyActivityから視聴履歴を収集（増分取得）
        3. 収集データを変換
        4. 生データ(JSON)をR2に保存
        5. イベントデータ(Parquet)をR2に保存（月次パーティショニング）
        6. YouTube APIで動画・チャンネルのマスターデータを取得して保存
        7. インジェスト状態を更新（全コンポーネント成功時のみ）
    """
    account_id = account_config.account_id
    logger.info(
        "Starting pipeline for account=%s (after=%s, max_items=%s)",
        account_id,
        after_timestamp.isoformat(),
        max_items,
    )

    try:
        # 1. インジェスト状態を取得
        state = storage.get_ingest_state(account_id)
        latest_watched_at = state.get("latest_watched_at") if state else None

        if isinstance(latest_watched_at, str):
            try:
                latest_watched_at = datetime.fromisoformat(latest_watched_at)
                if latest_watched_at.tzinfo is None:
                    latest_watched_at = latest_watched_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Failed to parse latest_watched_at "
                    "from state: %s. "
                    "Using after_timestamp.",
                    e,
                )
                latest_watched_at = None

        # after_timestampとlatest_watched_atの後方を取得対象にする
        fetch_after = after_timestamp
        if latest_watched_at:
            if latest_watched_at > after_timestamp:
                fetch_after = latest_watched_at
                logger.info(
                    "Using latest_watched_at=%s from state for account=%s",
                    fetch_after.isoformat(),
                    account_id,
                )

        # 2. MyActivityから視聴履歴を収集
        collector = MyActivityCollector(cookies=account_config.cookies)
        raw_items = await collector.collect_watch_history(
            after_timestamp=fetch_after, max_items=max_items
        )
        collected_count = len(raw_items)
        logger.info("Collected %d items for account=%s", collected_count, account_id)

        if collected_count == 0:
            logger.info("No items collected for account=%s", account_id)
            return PipelineResult(
                success=True,
                account_id=account_id,
                collected_count=0,
                saved_count=0,
                error=None,
            )

        # 3. 収集データを変換
        transformed_events = transform.transform_watch_history_items(
            raw_items, account_id
        )
        logger.info(
            "Transformed %d items for account=%s", len(transformed_events), account_id
        )

        # 4. 生データ(JSON)をR2に保存
        raw_saved_key = storage.save_raw_json(
            data=raw_items, prefix="youtube/activity", account_id=account_id
        )
        if not raw_saved_key:
            raise RuntimeError("Failed to save raw JSON data")

        # 5. イベントデータ(Parquet)をR2に保存（月次パーティショニング）
        # 月ごとにグループ化して保存
        monthly_events: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for event in transformed_events:
            watched_at = event["watched_at_utc"]
            month_key = (watched_at.year, watched_at.month)
            monthly_events[month_key].append(event)

        saved_count = 0
        failed_count = 0
        failed_months: list[str] = []
        for (year, month), events in monthly_events.items():
            saved_key = storage.save_parquet(
                data=events, year=year, month=month, prefix="youtube/watch_history"
            )
            if saved_key:
                saved_count += len(events)
                logger.info(
                    "Saved %d events to %s/%02d for account=%s",
                    len(events),
                    year,
                    month,
                    account_id,
                )
            else:
                failed_count += 1
                failed_months.append(f"{year}/{month:02d}")
                logger.warning(
                    "Failed to save events for %s/%02d for account=%s",
                    year,
                    month,
                    account_id,
                )

        if saved_count == 0:
            raise RuntimeError("Failed to save any events to Parquet")

        # 失敗したパーティションがある場合はstate更新をスキップ
        if failed_count > 0:
            failed_partitions = ", ".join(failed_months)
            error_message = (
                "Failed to save events for %d "
                "partition(s): %s. "
                "Ingest state not updated."
            ) % (failed_count, failed_partitions)
            raise RuntimeError(error_message)

        # 6. YouTube APIで動画・チャンネルのマスターデータを取得して保存
        video_ids = sorted(
            {
                event.get("video_id")
                for event in transformed_events
                if event.get("video_id")
            }
        )
        if video_ids:
            api_client = YouTubeAPIClient(account_config.youtube_api_key)
            try:
                video_items = api_client.get_videos(video_ids)
            except QuotaExceededError as e:
                raise RuntimeError("YouTube API quota exceeded") from e

            if not video_items:
                logger.warning("No video metadata returned for account=%s", account_id)
            else:
                video_master = [
                    transform.transform_video_info(video) for video in video_items
                ]
                saved_videos_key = storage.save_master_parquet(
                    data=video_master, prefix="youtube/videos"
                )
                if not saved_videos_key:
                    raise RuntimeError("Failed to save video master data")

                channel_ids = sorted(
                    {
                        video.get("snippet", {}).get("channelId")
                        for video in video_items
                        if video.get("snippet", {}).get("channelId")
                    }
                )
                if channel_ids:
                    channel_items = api_client.get_channels(channel_ids)
                    if not channel_items:
                        logger.warning(
                            "No channel metadata returned for account=%s",
                            account_id,
                        )
                    else:
                        channel_master = [
                            transform.transform_channel_info(channel)
                            for channel in channel_items
                        ]
                        saved_channels_key = storage.save_master_parquet(
                            data=channel_master, prefix="youtube/channels"
                        )
                        if not saved_channels_key:
                            raise RuntimeError("Failed to save channel master data")

        # 7. インジェスト状態を更新（全コンポーネント成功時のみ）
        # 最新のwatched_atを特定
        latest_event_watched_at = max(
            (event["watched_at_utc"] for event in transformed_events), default=None
        )

        if latest_event_watched_at:
            new_state = {"latest_watched_at": latest_event_watched_at.isoformat()}
            storage.save_ingest_state(new_state, account_id)
            logger.info(
                "Updated ingest state for account=%s to latest_watched_at=%s",
                account_id,
                latest_event_watched_at.isoformat(),
            )

        logger.info(
            "Pipeline completed successfully for account=%s (collected=%d, saved=%d)",
            account_id,
            collected_count,
            saved_count,
        )

        return PipelineResult(
            success=True,
            account_id=account_id,
            collected_count=collected_count,
            saved_count=saved_count,
            error=None,
        )

    except Exception as e:
        logger.exception(
            "Pipeline failed for account=%s: %s",
            account_id,
            e,
        )
        return PipelineResult(
            success=False,
            account_id=account_id,
            collected_count=0,
            saved_count=0,
            error=str(e),
        )


async def run_all_accounts_pipeline(
    accounts: list[AccountConfig],
    storage: YouTubeStorage,
    transform: Any,
    after_timestamp: datetime,
    max_items: int,
) -> dict[str, PipelineResult]:
    """全アカウントのパイプラインを順次実行する。

    Args:
        accounts: アカウント設定リスト
        storage: ストレージインスタンス
        transform: データ変換モジュール
        after_timestamp: この時刻以降の視聴履歴のみ収集
        max_items: 収集する最大アイテム数

    Returns:
        dict[str, PipelineResult]: アカウントIDをキーとする実行結果辞書

    注意:
        - アカウントレベルの独立性を維持（1つのアカウントの失敗が他に影響しない）
        - アカウントは順次実行される（並列実行は行わない）
    """
    logger.info(
        "Starting all accounts pipeline (accounts=%d, after=%s, max_items=%s)",
        len(accounts),
        after_timestamp.isoformat(),
        max_items,
    )

    results: dict[str, PipelineResult] = {}

    for account_config in accounts:
        account_id = account_config.account_id
        try:
            result = await run_account_pipeline(
                account_config=account_config,
                storage=storage,
                transform=transform,
                after_timestamp=after_timestamp,
                max_items=max_items,
            )
            results[account_id] = result

            # 結果をログ出力
            if result.success:
                logger.info(
                    "Account %s pipeline succeeded (collected=%d, saved=%d)",
                    account_id,
                    result.collected_count,
                    result.saved_count,
                )
            else:
                logger.warning(
                    "Account %s pipeline failed: %s",
                    account_id,
                    result.error,
                )

        except Exception as e:
            # 予期しないエラーでも他のアカウントは続行
            logger.error(
                "Unexpected error for account=%s: %s",
                account_id,
                e,
                exc_info=True,
            )
            results[account_id] = PipelineResult(
                success=False,
                account_id=account_id,
                collected_count=0,
                saved_count=0,
                error=f"Unexpected error: {str(e)}",
            )

    success_count = sum(1 for r in results.values() if r.success)
    logger.info(
        "All accounts pipeline completed (success=%d/%d)",
        success_count,
        len(accounts),
    )

    return results
