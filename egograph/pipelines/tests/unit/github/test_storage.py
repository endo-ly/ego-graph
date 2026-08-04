"""GitHubWorklogStorageの単体テスト。"""

import json
import unittest
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from dataset_catalog import datasets
from pipelines.sources.github.storage import (
    GitHubWorklogStorage,
    StorageConsistencyError,
)


def _commit_row(event_id: str, sha: str) -> dict:
    """schema 契約を満たす github.commits 行。"""
    return {
        "commit_event_id": event_id,
        "repo_full_name": "testowner/testrepo",
        "sha": sha,
        "committed_at_utc": datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
        "ingested_at_utc": datetime(2024, 1, 15, 11, 0, tzinfo=UTC),
    }


def _pr_event_row(event_id: str, pr_number: int) -> dict:
    """schema 契約を満たす github.pull_requests 行。"""
    return {
        "pr_event_id": event_id,
        "repo_full_name": "testowner/testrepo",
        "pr_number": pr_number,
        "created_at_utc": datetime(2025, 12, 31, tzinfo=UTC),
        "updated_at_utc": datetime(2026, 1, 1, tzinfo=UTC),
        "closed_at_utc": datetime(2026, 1, 2, tzinfo=UTC),
        "merged_at_utc": datetime(2026, 1, 3, tzinfo=UTC),
        "ingested_at_utc": datetime(2026, 1, 4, tzinfo=UTC),
    }


@pytest.fixture
def github_storage_with_mock_s3():
    """GitHub storageとモックS3を生成するpytest fixture。"""
    with patch("pipelines.sources.github.storage.boto3") as mock_boto3:
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        storage = GitHubWorklogStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
            raw_path="raw/",
            events_path="events/",
            master_path="master/",
        )
        yield storage, mock_s3


class TestGitHubWorklogStorage(unittest.TestCase):
    """GitHubWorklogStorageの単体テストクラス。"""

    def setUp(self):
        """テスト前にboto3をモック化し、Storageインスタンスを初期化する。"""
        self.mock_boto3 = patch("pipelines.sources.github.storage.boto3").start()
        self.mock_s3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_s3

        self.storage = GitHubWorklogStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
            raw_path="raw/",
            events_path="events/",
            master_path="master/",
        )

    def tearDown(self):
        """テスト後に全てのモックを停止する。"""
        patch.stopall()

    def test_init(self):
        """初期化時に正しくS3クライアントとパスが設定されることを検証する。"""
        # Assert: 属性が正しく設定されている
        self.assertEqual(self.storage.bucket_name, "test-bucket")
        self.assertEqual(self.storage.raw_path, "raw/")
        self.assertEqual(self.storage.events_path, "events/")
        self.assertEqual(self.storage.master_path, "master/")
        self.mock_boto3.client.assert_called_once()

    def test_save_raw_prs(self):
        """PR生データをJSON形式でR2に保存することを検証する。

        Path: raw/github/pull_requests/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
        """
        # Arrange: 保存するPRデータの準備
        data = [
            {
                "id": 1,
                "number": 100,
                "title": "Test PR",
                "state": "open",
                "user": {"login": "testuser"},
            }
        ]

        # Act: PR生データとして保存を実行
        key = self.storage.save_raw_prs(data, owner="testowner", repo="testrepo")

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(call_args["Key"].startswith("raw/github/pull_requests/"))
        self.assertTrue(call_args["Key"].endswith(".json"))
        self.assertEqual(call_args["ContentType"], "application/json")
        self.assertIsNotNone(key)

    def test_save_raw_commits(self):
        """Commit生データをJSON形式でR2に保存することを検証する。

        Path: raw/github/commits/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
        """
        # Arrange: 保存するCommitデータの準備
        data = [
            {
                "sha": "abc123",
                "commit": {
                    "author": {"name": "Test User", "email": "test@example.com"},
                    "message": "Test commit",
                },
                "stats": {"additions": 10, "deletions": 5, "total": 15},
            }
        ]

        # Act: Commit生データとして保存を実行
        key = self.storage.save_raw_commits(data, owner="testowner", repo="testrepo")

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(call_args["Key"].startswith("raw/github/commits/"))
        self.assertTrue(call_args["Key"].endswith(".json"))
        self.assertEqual(call_args["ContentType"], "application/json")
        self.assertIsNotNone(key)

    def test_save_commits_parquet(self):
        """CommitイベントをParquet形式で保存することを検証する。

        Path: events/github/commits/year={YYYY}/month={MM}/{uuid}.parquet
        """
        # Arrange: 保存するCommitイベントデータの準備
        data = [_commit_row("testowner/testrepo/abc123", "abc123")]

        # Act: Parquet形式での保存を実行
        key = self.storage.save_commits_parquet(data, year=2024, month=1)

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(
            call_args["Key"].startswith("events/github/commits/year=2024/month=01/")
        )
        self.assertTrue(call_args["Key"].endswith(".parquet"))
        self.assertEqual(call_args["ContentType"], "application/octet-stream")
        self.assertIsNotNone(key)

    def test_save_commits_parquet_deduplication(self):
        """既存Commit IDが重複排除されることを検証する。"""
        # Arrange: 保存するデータ（既存IDを含む）
        data = [_commit_row("existing_id", "abc123"), _commit_row("new_id", "def456")]

        # Act: Parquet形式での保存を実行
        with patch.object(
            self.storage,
            "_load_existing_commit_ids",
            return_value={"existing_id"},
        ):
            key = self.storage.save_commits_parquet(data, year=2024, month=1)

        # Assert: 新規IDのみが保存されることを検証
        self.mock_s3.put_object.assert_called_once()
        self.assertIsNotNone(key)

    def test_save_commits_parquet_empty_when_all_duplicates(self):
        """全てのCommitが重複している場合、保存がスキップされることを検証する。"""
        # Arrange: 全て重複するデータ
        data = [
            {"commit_event_id": "existing_id_1", "sha": "abc123"},
            {"commit_event_id": "existing_id_2", "sha": "def456"},
        ]

        # Act: 全て重複する状態で保存を実行
        with patch.object(
            self.storage,
            "_load_existing_commit_ids",
            return_value={"existing_id_1", "existing_id_2"},
        ):
            key = self.storage.save_commits_parquet(data, year=2024, month=1)

            # Assert: put_objectが呼ばれない（保存スキップ）
            self.mock_s3.put_object.assert_not_called()
            self.assertIsNone(key)

    def test_save_commits_parquet_with_stats(self):
        """新規/重複件数の統計が返ることを検証する。"""
        data = [_commit_row("existing_id", "abc123"), _commit_row("new_id", "def456")]

        with patch.object(
            self.storage,
            "_load_existing_commit_ids",
            return_value={"existing_id"},
        ):
            stats = self.storage.save_commits_parquet_with_stats(
                data,
                year=2024,
                month=1,
            )

        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["failed"], 0)

    def test_save_commits_parquet_with_stats_on_validation_failure(self):
        """schema 契約違反時に failed 件数が返り、アップロードされないことを
        検証する。"""
        data = [_commit_row("new_id", "def456")]
        data[0]["committed_at_utc"] = "2024-01-15T10:00:00Z"

        with patch.object(
            self.storage,
            "_load_existing_commit_ids",
            return_value=set(),
        ):
            stats = self.storage.save_commits_parquet_with_stats(
                data,
                year=2024,
                month=1,
            )

        self.assertEqual(stats["fetched"], 1)
        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(stats["failed"], 1)
        self.mock_s3.put_object.assert_not_called()

    def test_save_commits_parquet_with_stats_on_failure(self):
        """保存失敗時にfailed件数が返ることを検証する。"""
        data = [{"commit_event_id": "new_id", "sha": "def456"}]

        with patch.object(
            self.storage,
            "_load_existing_commit_ids",
            return_value=set(),
        ):
            with patch.object(self.storage, "_upload_parquet", return_value=None):
                stats = self.storage.save_commits_parquet_with_stats(
                    data,
                    year=2024,
                    month=1,
                )

                self.assertEqual(stats["fetched"], 1)
                self.assertEqual(stats["new"], 0)
                self.assertEqual(stats["duplicates"], 0)
                self.assertEqual(stats["failed"], 1)

    def test_save_pr_events_parquet_with_stats(self):
        data = [
            _pr_event_row("existing_event", 100),
            _pr_event_row("new_event", 101),
        ]

        with patch.object(
            self.storage,
            "_load_existing_pr_event_ids",
            return_value={"existing_event"},
        ):
            stats = self.storage.save_pr_events_parquet_with_stats(
                data,
                year=2026,
                month=1,
            )

        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["failed"], 0)
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertTrue(
            call_args["Key"].startswith(
                "events/github/pull_requests/year=2026/month=01/"
            )
        )

    def test_save_pr_events_parquet_with_stats_when_all_duplicates(self):
        data = [_pr_event_row("existing_event", 100)]

        with patch.object(
            self.storage,
            "_load_existing_pr_event_ids",
            return_value={"existing_event"},
        ):
            stats = self.storage.save_pr_events_parquet_with_stats(
                data,
                year=2026,
                month=1,
            )

        self.assertEqual(stats["fetched"], 1)
        self.assertEqual(stats["new"], 0)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["failed"], 0)
        self.mock_s3.put_object.assert_not_called()

    def test_save_repo_master(self):
        """Repository MasterをParquet形式で保存することを検証する。

        Path: master/github/repositories/{owner}/{repo}.parquet
        """
        # Arrange: 保存するRepository Masterデータの準備
        data = [
            {
                "repo_id": 12345,
                "repo_full_name": "testowner/testrepo",
                "updated_at_utc": datetime(2024, 1, 15, tzinfo=UTC),
            }
        ]

        # Act: Repository Masterとして保存を実行
        key = self.storage.save_repo_master(data, owner="testowner", repo="testrepo")

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(
            call_args["Key"].startswith("master/github/repositories/testowner/testrepo")
        )
        self.assertTrue(call_args["Key"].endswith(".parquet"))
        self.assertEqual(call_args["ContentType"], "application/octet-stream")
        self.assertIsNotNone(key)

    def test_get_ingest_state_exists(self):
        """インジェスト状態が存在する場合、正しく取得されることを検証する。"""
        # Arrange: 保存されている状態がある場合をモック
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"cursor": "2024-01-15T10:00:00Z", "last_repo": "testowner/testrepo"}
        ).encode("utf-8")
        self.mock_s3.get_object.return_value = {"Body": mock_body}

        # Act: 保存されている状態を取得
        state = self.storage.get_ingest_state()

        # Assert: 取得された状態を検証
        self.assertEqual(state["cursor"], "2024-01-15T10:00:00Z")
        self.assertEqual(state["last_repo"], "testowner/testrepo")
        self.mock_s3.get_object.assert_called_with(
            Bucket="test-bucket", Key="state/github_worklog_ingest_state.json"
        )

    def test_get_ingest_state_not_exists(self):
        """インジェスト状態が存在しない場合、Noneが返されることを検証する。"""
        # Arrange: NoSuchKeyエラーをモック
        error_response = {
            "Error": {"Code": "NoSuchKey", "Message": "The key does not exist"}
        }
        self.mock_s3.get_object.side_effect = ClientError(error_response, "get_object")

        # Act: 状態を取得
        state = self.storage.get_ingest_state()

        # Assert: Noneが返される
        self.assertIsNone(state)

    def test_save_ingest_state(self):
        """インジェスト状態が正しく保存されることを検証する。"""
        # Arrange: 保存する状態の準備
        state = {
            "cursor": "2024-01-15T10:00:00Z",
            "last_repo": "testowner/testrepo",
            "processed_count": 42,
        }

        # Act: 状態の保存を実行
        self.storage.save_ingest_state(state)

        # Assert: put_object が正しい引数で呼ばれたことを検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Key"], "state/github_worklog_ingest_state.json")
        self.assertEqual(json.loads(call_args["Body"]), state)
        self.assertEqual(call_args["ContentType"], "application/json")

    def test_get_ingest_state_raises_on_unexpected_client_error(self):
        """NoSuchKey以外の状態取得失敗は例外で表面化する。"""
        error_response = {"Error": {"Code": "AccessDenied", "Message": "denied"}}
        self.mock_s3.get_object.side_effect = ClientError(error_response, "get_object")

        with self.assertRaises(StorageConsistencyError):
            self.storage.get_ingest_state()

    def test_save_ingest_state_raises_on_write_failure(self):
        """状態保存失敗は例外で表面化する。"""
        self.mock_s3.put_object.side_effect = RuntimeError("write failed")

        with self.assertRaises(StorageConsistencyError):
            self.storage.save_ingest_state({"cursor": "x"})

    def test_save_raw_prs_empty_data(self):
        """空データを渡した場合、保存がスキップされることを検証する。"""
        # Arrange: 空データ
        data = []

        # Act: 保存を実行
        key = self.storage.save_raw_prs(data, owner="testowner", repo="testrepo")

        # Assert: put_objectが呼ばれない
        self.mock_s3.put_object.assert_not_called()
        self.assertIsNone(key)

    def test_save_commits_parquet_empty_data(self):
        """空データを渡した場合、Parquet保存がスキップされることを検証する。"""
        # Arrange: 空データ
        data = []

        # Act: 保存を実行
        key = self.storage.save_commits_parquet(data, year=2024, month=1)

        # Assert: put_objectが呼ばれない
        self.mock_s3.put_object.assert_not_called()
        self.assertIsNone(key)

    def test_load_existing_commit_ids(self):
        """既存Commit IDが正しく読み込まれることを検証する。"""
        # Arrange: paginator と get_object をモック
        mock_page = {
            "Contents": [
                {"Key": "events/github/commits/year=2024/month=01/file1.parquet"},
                {"Key": "events/github/commits/year=2024/month=01/file2.parquet"},
            ]
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        self.mock_s3.get_paginator.return_value = mock_paginator

        # 各ファイルのDataFrameを作成
        df1 = pd.DataFrame([{"commit_event_id": "id1"}])
        df2 = pd.DataFrame([{"commit_event_id": "id2"}])

        # BytesIOに変換
        buffer1 = BytesIO()
        buffer2 = BytesIO()
        df1.to_parquet(buffer1, index=False, engine="pyarrow")
        df2.to_parquet(buffer2, index=False, engine="pyarrow")
        buffer1.seek(0)
        buffer2.seek(0)

        mock_body1 = MagicMock()
        mock_body1.read.return_value = buffer1.read()
        mock_body2 = MagicMock()
        mock_body2.read.return_value = buffer2.read()

        self.mock_s3.get_object.side_effect = [
            {"Body": mock_body1},
            {"Body": mock_body2},
        ]

        # Act: 既存Commit IDを読み込み
        existing_ids = self.storage._load_existing_commit_ids(year=2024, month=1)

        # Assert: 正しいIDが含まれる
        self.assertIn("id1", existing_ids)
        self.assertIn("id2", existing_ids)

    def test_load_existing_commit_ids_no_files(self):
        """ファイルが存在しない場合、空セットが返されることを検証する。"""
        # Arrange: ファイルが存在しない状態をモック
        error_response = {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}
        self.mock_s3.get_paginator.side_effect = ClientError(
            error_response, "get_paginator"
        )

        # Act: 既存Commit IDを読み込み
        existing_ids = self.storage._load_existing_commit_ids(year=2024, month=1)

        # Assert: 空セットが返される
        self.assertEqual(existing_ids, set())

    def test_load_existing_commit_ids_raises_on_corrupt_parquet(self):
        """既存Parquetが壊れている場合は例外で表面化する。"""
        mock_page = {
            "Contents": [
                {"Key": "events/github/commits/year=2024/month=01/bad.parquet"},
            ]
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_page]
        self.mock_s3.get_paginator.return_value = mock_paginator

        mock_body = MagicMock()
        mock_body.read.return_value = b"not a parquet file"
        self.mock_s3.get_object.return_value = {"Body": mock_body}

        with self.assertRaises(StorageConsistencyError):
            self.storage._load_existing_commit_ids(year=2024, month=1)

    def test_path_normalization(self):
        """パスが正規化され、末尾に/が付くことを検証する。"""
        # Arrange & Act: 末尾スラッシュなしで初期化
        storage_no_slash = GitHubWorklogStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
            raw_path="raw",  # 末尾スラッシュなし
            events_path="events",
            master_path="master",
        )

        # Assert: 全てのパスが末尾スラッシュ付きに正規化される
        self.assertEqual(storage_no_slash.raw_path, "raw/")
        self.assertEqual(storage_no_slash.events_path, "events/")
        self.assertEqual(storage_no_slash.master_path, "master/")

    def test_compact_month_saves_fixed_key(self):
        data = [_commit_row("commit_1", "abc123")]

        with patch(
            "pipelines.sources.github.storage.read_parquet_records_from_prefix",
            return_value=data,
        ):
            key = self.storage.compact_month(
                dataset=datasets.GITHUB_COMMITS,
                year=2024,
                month=1,
            )

        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(
            call_args["Key"],
            "compacted/events/github/commits/year=2024/month=01/data.parquet",
        )
        self.assertEqual(key, call_args["Key"])

    def test_compact_month_normalizes_legacy_pr_string_timestamp(self):
        """既存PR sourceの文字列日時をtimestamp Parquetへ変換して保存する。"""
        data = [_pr_event_row("pr_1", 1)]
        data[0]["updated_at_utc"] = "2026-07-02T12:00:00Z"

        with patch(
            "pipelines.sources.github.storage.read_parquet_records_from_prefix",
            return_value=data,
        ):
            key = self.storage.compact_month(
                dataset=datasets.GITHUB_PULL_REQUESTS,
                year=2026,
                month=7,
            )

        body = self.mock_s3.put_object.call_args.kwargs["Body"]
        compacted = pd.read_parquet(BytesIO(body))
        self.assertEqual(
            key,
            "compacted/events/github/pull_requests/year=2026/month=07/data.parquet",
        )
        self.assertEqual(compacted["updated_at_utc"].dtype.name, "datetime64[ns, UTC]")


def test_compact_month_normalizes_legacy_string_timestamp(
    github_storage_with_mock_s3,
):
    """既存sourceの文字列日時をtimestamp Parquetへ変換して保存する。"""
    storage, mock_s3 = github_storage_with_mock_s3
    data = [_commit_row("commit_1", "abc123")]
    data[0]["committed_at_utc"] = "2026-07-01T12:00:00Z"

    with patch(
        "pipelines.sources.github.storage.read_parquet_records_from_prefix",
        return_value=data,
    ):
        key = storage.compact_month(
            dataset=datasets.GITHUB_COMMITS,
            year=2026,
            month=7,
        )

    body = mock_s3.put_object.call_args.kwargs["Body"]
    compacted = pd.read_parquet(BytesIO(body))
    assert key == "compacted/events/github/commits/year=2026/month=07/data.parquet"
    assert compacted["committed_at_utc"].dtype.name == "datetime64[ns, UTC]"


def test_compact_month_normalizes_mixed_commit_ingestion_timestamps(
    github_storage_with_mock_s3,
):
    """複数source間で型が混在するCommitの取り込み日時を正規化する。"""
    storage, mock_s3 = github_storage_with_mock_s3
    data = [
        _commit_row("commit_1", "abc123"),
        _commit_row("commit_2", "def456"),
    ]
    data[1]["ingested_at_utc"] = "2026-07-01T12:00:00Z"

    with patch(
        "pipelines.sources.github.storage.read_parquet_records_from_prefix",
        return_value=data,
    ):
        key = storage.compact_month(
            dataset=datasets.GITHUB_COMMITS,
            year=2026,
            month=7,
        )

    body = mock_s3.put_object.call_args.kwargs["Body"]
    compacted = pd.read_parquet(BytesIO(body))

    assert key == "compacted/events/github/commits/year=2026/month=07/data.parquet"
    assert compacted["ingested_at_utc"].dtype.name == "datetime64[ns, UTC]"


def test_compact_month_normalizes_mixed_pr_creation_timestamps(
    github_storage_with_mock_s3,
):
    """複数source間で型が混在するPRの作成日時を正規化する。"""
    storage, mock_s3 = github_storage_with_mock_s3
    data = [_pr_event_row("pr_1", 1), _pr_event_row("pr_2", 2)]
    data[1]["created_at_utc"] = "2026-07-02T12:00:00Z"

    with patch(
        "pipelines.sources.github.storage.read_parquet_records_from_prefix",
        return_value=data,
    ):
        key = storage.compact_month(
            dataset=datasets.GITHUB_PULL_REQUESTS,
            year=2026,
            month=7,
        )

    body = mock_s3.put_object.call_args.kwargs["Body"]
    compacted = pd.read_parquet(BytesIO(body))

    assert key == (
        "compacted/events/github/pull_requests/year=2026/month=07/data.parquet"
    )
    assert compacted["created_at_utc"].dtype.name == "datetime64[ns, UTC]"
