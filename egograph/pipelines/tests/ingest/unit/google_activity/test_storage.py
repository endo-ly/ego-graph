"""YouTubeStorageのテスト。"""

import uuid as uuid_module
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from pipelines.sources.google_activity.storage import YouTubeStorage


class TestYouTubeStorageInit:
    """YouTubeStorage初期化のテスト。"""

    @patch("boto3.client")
    def test_initialization_creates_s3_client(self, mock_boto3_client):
        """YouTubeStorageがS3クライアントを作成することを確認。"""
        # Arrange & Act
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        # Assert
        mock_boto3_client.assert_called_once()
        assert storage.bucket_name == "test-bucket"


class TestYouTubeStorageSaveRawJson:
    """save_raw_jsonメソッドのテスト。"""

    @patch("boto3.client")
    def test_save_raw_json_with_account_id(self, mock_boto3_client):
        """account_idを指定してJSONを保存することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        data = [{"test": "data"}]

        # Act
        # uuid4モックを正確にシミュレート（str(uuid.uuid4())[:8]形式）
        mock_uuid = uuid_module.UUID("12345678-1234-5678-1234-567812345678")
        with patch.object(uuid_module, "uuid4", return_value=mock_uuid):
            storage.save_raw_json(data, prefix="activity", account_id="account1")

        # Assert
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        assert call_args[1]["Bucket"] == "test-bucket"
        assert call_args[1]["ContentType"] == "application/json"
        assert "account1" in call_args[1]["Key"]
        assert "activity" in call_args[1]["Key"]

    @patch("boto3.client")
    def test_save_raw_json_without_account_id(self, mock_boto3_client):
        """account_idなしでJSONを保存することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        data = [{"test": "data"}]

        # Act
        with patch.object(
            uuid_module, "uuid4", return_value=MagicMock(hex="test-uuid")
        ):
            storage.save_raw_json(data, prefix="videos")

        # Assert
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        assert "videos" in call_args[1]["Key"]


class TestYouTubeStorageSaveParquet:
    """save_parquetメソッドのテスト。"""

    @patch("boto3.client")
    def test_save_parquet_saves_with_partitioning(self, mock_boto3_client):
        """年月パーティションでParquetを保存することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        data = [{"test": "data"}]

        # Act
        with patch.object(
            uuid_module, "uuid4", return_value=MagicMock(hex="test-uuid")
        ):
            storage.save_parquet(
                data, year=2025, month=12, prefix="youtube/watch_history"
            )

        # Assert
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        assert "year=2025" in call_args[1]["Key"]
        assert "month=12" in call_args[1]["Key"]


class TestYouTubeStorageSaveMasterParquet:
    """save_master_parquetメソッドのテスト。"""

    @patch("boto3.client")
    def test_save_master_parquet_with_partitioning(self, mock_boto3_client):
        """年月パーティションでマスターParquetを保存することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        data = [{"test": "data"}]

        # Act
        with patch.object(
            uuid_module, "uuid4", return_value=MagicMock(hex="test-uuid")
        ):
            storage.save_master_parquet(
                data, prefix="youtube/videos", year=2025, month=12
            )

        # Assert
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        assert "year=2025" in call_args[1]["Key"]
        assert "month=12" in call_args[1]["Key"]


class TestYouTubeStorageGetIngestState:
    """get_ingest_stateメソッドのテスト。"""

    @patch("boto3.client")
    def test_get_ingest_state_success(self, mock_boto3_client):
        """状態ファイルが存在する場合に取得することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        mock_response = {"Body": MagicMock()}
        mock_response[
            "Body"
        ].read.return_value = b'{"last_watched_at": "2025-12-01T00:00:00Z"}'
        mock_s3.get_object.return_value = mock_response

        # Act
        result = storage.get_ingest_state("account1")

        # Assert
        assert result == {"last_watched_at": "2025-12-01T00:00:00Z"}
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="state/youtube_account1_state.json"
        )

    @patch("boto3.client")
    def test_get_ingest_state_not_found(self, mock_boto3_client):
        """状態ファイルが存在しない場合にNoneを返すことを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "GetObject"
        )

        # Act
        result = storage.get_ingest_state("account1")

        # Assert
        assert result is None


class TestYouTubeStorageSaveIngestState:
    """save_ingest_stateメソッドのテスト。"""

    @patch("boto3.client")
    def test_save_ingest_state(self, mock_boto3_client):
        """状態ファイルを保存することを確認。"""
        # Arrange
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3
        storage = YouTubeStorage(
            endpoint_url="https://endpoint.r2.cloudflarestorage.com",
            access_key_id="test_key",
            secret_access_key="test_secret",
            bucket_name="test-bucket",
        )

        state = {"last_watched_at": "2025-12-01T00:00:00Z"}

        # Act
        storage.save_ingest_state(state, "account1")

        # Assert
        mock_s3.put_object.assert_called_once()
        call_args = mock_s3.put_object.call_args
        assert call_args[1]["Bucket"] == "test-bucket"
        assert call_args[1]["Key"] == "state/youtube_account1_state.json"
        assert call_args[1]["ContentType"] == "application/json"
