"""パイプラインモジュールのテスト。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipelines.sources.google_activity.config import AccountConfig
from pipelines.sources.google_activity.pipeline import (
    run_account_pipeline,
    run_all_accounts_pipeline,
)


class TestRunAccountPipeline:
    """run_account_pipelineのテスト。"""

    @pytest.mark.asyncio
    async def test_success_path_with_all_components_working(self):
        """正常ケース: 全てのコンポーネントが正常に動作すること。"""
        # Arrange
        account_config = AccountConfig(
            account_id="account1",
            cookies={"SID": "test_sid", "HSID": "test_hsid"},
            youtube_api_key="test_api_key",
        )

        mock_collector = AsyncMock()
        mock_collector.collect_watch_history.return_value = [
            {
                "video_id": "abc123",
                "title": "Test Video",
                "channel_name": "Test Channel",
                "watched_at": datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                "video_url": "https://www.youtube.com/watch?v=abc123",
            }
        ]

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        mock_transform.transform_watch_history_items.return_value = [
            {
                "watch_id": "test_watch_id",
                "account_id": "account1",
                "watched_at_utc": datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                "video_id": "abc123",
                "video_title": "Test Video",
                "channel_id": None,
                "channel_name": "Test Channel",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "context": None,
            }
        ]
        mock_transform.transform_video_info.return_value = {"video_id": "abc123"}
        mock_transform.transform_channel_info.return_value = {"channel_id": "chan1"}

        mock_api_client = MagicMock()
        mock_api_client.get_videos.return_value = [
            {"id": "abc123", "snippet": {"channelId": "chan1"}}
        ]
        mock_api_client.get_channels.return_value = [{"id": "chan1"}]

        # Act
        with (
            patch(
                "pipelines.sources.google_activity.pipeline.MyActivityCollector",
                return_value=mock_collector,
            ),
            patch(
                "pipelines.sources.google_activity.pipeline.YouTubeAPIClient",
                return_value=mock_api_client,
            ),
        ):
            result = await run_account_pipeline(
                account_config=account_config,
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        # Assert
        assert result.success is True
        assert result.account_id == "account1"
        assert result.collected_count == 1
        assert result.saved_count == 1
        assert result.error is None
        mock_collector.collect_watch_history.assert_called_once()
        mock_transform.transform_watch_history_items.assert_called_once()
        mock_storage.save_raw_json.assert_called_once()
        mock_storage.save_parquet.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_path_when_collector_fails(self):
        """異常ケース: コレクターが失敗した場合。"""
        # Arrange
        account_config = AccountConfig(
            account_id="account1",
            cookies={"SID": "test_sid"},
            youtube_api_key="test_api_key",
        )

        mock_collector = AsyncMock()
        mock_collector.collect_watch_history.side_effect = Exception("Collector failed")

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        mock_transform.transform_watch_history_items.return_value = []
        mock_transform.transform_video_info.return_value = {"video_id": "abc123"}
        mock_transform.transform_channel_info.return_value = {"channel_id": "chan1"}

        # Act
        with (
            patch(
                "pipelines.sources.google_activity.pipeline.MyActivityCollector",
                return_value=mock_collector,
            ),
            patch(
                "pipelines.sources.google_activity.pipeline.YouTubeAPIClient",
                return_value=MagicMock(),
            ),
        ):
            result = await run_account_pipeline(
                account_config=account_config,
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        # Assert
        assert result.success is False
        assert result.account_id == "account1"
        assert result.collected_count == 0
        assert result.saved_count == 0
        assert result.error is not None
        assert "Collector failed" in str(result.error)
        mock_collector.collect_watch_history.assert_called_once()
        # Storage should not be called on collector failure
        mock_storage.save_raw_json.assert_not_called()
        mock_storage.save_parquet.assert_not_called()

    @pytest.mark.asyncio
    async def test_account1_failure_isolation_account2_runs_regardless(self):
        """account1が失敗してもaccount2は実行されること（アカウントレベルの独立性）。"""
        # Arrange
        account1_config = AccountConfig(
            account_id="account1",
            cookies={"SID": "test_sid1"},
            youtube_api_key="test_api_key",
        )

        account2_config = AccountConfig(
            account_id="account2",
            cookies={"SID": "test_sid2"},
            youtube_api_key="test_api_key",
        )

        mock_collector1 = AsyncMock()
        mock_collector1.collect_watch_history.side_effect = Exception("Account1 failed")

        mock_collector2 = AsyncMock()
        mock_collector2.collect_watch_history.return_value = [
            {
                "video_id": "xyz789",
                "title": "Test Video 2",
                "channel_name": "Test Channel 2",
                "watched_at": datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                "video_url": "https://www.youtube.com/watch?v=xyz789",
            }
        ]

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        # Note: account1 fails at collector step, so transform is never called
        # for account1. The first call to transform_watch_history_items is
        # for account2
        mock_transform.transform_watch_history_items.return_value = [
            {
                "watch_id": "test_watch_id_2",
                "account_id": "account2",
                "watched_at_utc": datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                "video_id": "xyz789",
                "video_title": "Test Video 2",
                "channel_id": None,
                "channel_name": "Test Channel 2",
                "video_url": "https://www.youtube.com/watch?v=xyz789",
                "context": None,
            }
        ]
        mock_transform.transform_video_info.return_value = {"video_id": "xyz789"}
        mock_transform.transform_channel_info.return_value = {"channel_id": "chan2"}

        mock_api_client = MagicMock()
        mock_api_client.get_videos.return_value = [
            {"id": "xyz789", "snippet": {"channelId": "chan2"}}
        ]
        mock_api_client.get_channels.return_value = [{"id": "chan2"}]

        # Act & Assert for account1 (fails)
        with (
            patch(
                "pipelines.sources.google_activity.pipeline.MyActivityCollector",
                return_value=mock_collector1,
            ),
            patch(
                "pipelines.sources.google_activity.pipeline.YouTubeAPIClient",
                return_value=mock_api_client,
            ),
        ):
            result1 = await run_account_pipeline(
                account_config=account1_config,
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        assert result1.success is False
        assert result1.account_id == "account1"
        assert result1.error is not None

        # Act & Assert for account2 (succeeds)
        with (
            patch(
                "pipelines.sources.google_activity.pipeline.MyActivityCollector",
                return_value=mock_collector2,
            ),
            patch(
                "pipelines.sources.google_activity.pipeline.YouTubeAPIClient",
                return_value=mock_api_client,
            ),
        ):
            result2 = await run_account_pipeline(
                account_config=account2_config,
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        assert result2.success is True
        assert result2.account_id == "account2"
        assert result2.collected_count == 1
        assert result2.saved_count == 1


class TestRunAllAccountsPipeline:
    """run_all_accounts_pipelineのテスト。"""

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        """全てのアカウントが順次実行されること。"""
        # Arrange
        account1_config = AccountConfig(
            account_id="account1",
            cookies={"SID": "test_sid1"},
            youtube_api_key="test_api_key",
        )

        account2_config = AccountConfig(
            account_id="account2",
            cookies={"SID": "test_sid2"},
            youtube_api_key="test_api_key",
        )

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        mock_transform.transform_watch_history_items.return_value = [
            {
                "watch_id": "test_watch_id",
                "account_id": "account1",
                "watched_at_utc": datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc),
                "video_id": "abc123",
                "video_title": "Test Video",
                "channel_id": None,
                "channel_name": "Test Channel",
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "context": None,
            }
        ]

        # Mock run_account_pipeline to track execution order
        execution_order = []

        async def mock_run_account_pipeline(
            account_config, storage, transform, after_timestamp, max_items
        ):
            execution_order.append(account_config.account_id)
            return MagicMock(
                success=True,
                account_id=account_config.account_id,
                collected_count=1,
                saved_count=1,
                error=None,
            )

        # Act
        with patch(
            "pipelines.sources.google_activity.pipeline.run_account_pipeline",
            side_effect=mock_run_account_pipeline,
        ):
            results = await run_all_accounts_pipeline(
                accounts=[account1_config, account2_config],
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        # Assert
        assert len(execution_order) == 2
        assert execution_order == ["account1", "account2"]  # Sequential order preserved
        assert "account1" in results
        assert "account2" in results

    @pytest.mark.asyncio
    async def test_result_dict_contains_all_accounts(self):
        """結果辞書が全てのアカウントを含んでいること。"""
        # Arrange
        account_configs = [
            AccountConfig(
                account_id=f"account{i}",
                cookies={"SID": f"test_sid{i}"},
                youtube_api_key="test_api_key",
            )
            for i in range(1, 4)
        ]

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        mock_transform.transform_watch_history_items.return_value = []

        async def mock_run_account_pipeline(
            account_config, storage, transform, after_timestamp, max_items
        ):
            return MagicMock(
                success=True,
                account_id=account_config.account_id,
                collected_count=0,
                saved_count=0,
                error=None,
            )

        # Act
        with patch(
            "pipelines.sources.google_activity.pipeline.run_account_pipeline",
            side_effect=mock_run_account_pipeline,
        ):
            results = await run_all_accounts_pipeline(
                accounts=account_configs,
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        # Assert
        assert isinstance(results, dict)
        assert len(results) == 3
        assert "account1" in results
        assert "account2" in results
        assert "account3" in results

    @pytest.mark.asyncio
    async def test_account_level_independence(self):
        """アカウントレベルでの独立性が保たれていること（1つのアカウントの失敗が他に影響しない）。"""
        # Arrange
        account1_config = AccountConfig(
            account_id="account1",
            cookies={"SID": "test_sid1"},
            youtube_api_key="test_api_key",
        )

        account2_config = AccountConfig(
            account_id="account2",
            cookies={"SID": "test_sid2"},
            youtube_api_key="test_api_key",
        )

        account3_config = AccountConfig(
            account_id="account3",
            cookies={"SID": "test_sid3"},
            youtube_api_key="test_api_key",
        )

        mock_storage = MagicMock()
        mock_storage.save_raw_json = MagicMock(return_value="raw_key")
        mock_storage.save_parquet = MagicMock(return_value="parquet_key")
        mock_storage.save_master_parquet = MagicMock(return_value="master_key")
        mock_storage.get_ingest_state.return_value = None
        mock_storage.save_ingest_state = MagicMock()

        mock_transform = MagicMock()
        mock_transform.transform_watch_history_items.return_value = []

        # Mock different results for each account
        async def mock_run_account_pipeline(
            account_config, storage, transform, after_timestamp, max_items
        ):
            if account_config.account_id == "account2":
                # account2 fails
                return MagicMock(
                    success=False,
                    account_id=account_config.account_id,
                    collected_count=0,
                    saved_count=0,
                    error="Account2 collector failed",
                )
            else:
                # account1 and account3 succeed
                return MagicMock(
                    success=True,
                    account_id=account_config.account_id,
                    collected_count=1,
                    saved_count=1,
                    error=None,
                )

        # Act
        with patch(
            "pipelines.sources.google_activity.pipeline.run_account_pipeline",
            side_effect=mock_run_account_pipeline,
        ):
            results = await run_all_accounts_pipeline(
                accounts=[account1_config, account2_config, account3_config],
                storage=mock_storage,
                transform=mock_transform,
                after_timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                max_items=10,
            )

        # Assert
        assert len(results) == 3
        assert results["account1"].success is True
        assert results["account1"].collected_count == 1
        assert results["account1"].saved_count == 1

        assert results["account2"].success is False
        assert results["account2"].collected_count == 0
        assert results["account2"].saved_count == 0
        assert "Account2 collector failed" in str(results["account2"].error)

        assert results["account3"].success is True
        assert results["account3"].collected_count == 1
        assert results["account3"].saved_count == 1
