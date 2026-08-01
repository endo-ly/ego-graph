import json
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from dataset_catalog import datasets
from pipelines.sources.spotify.storage import SpotifyStorage, StorageConsistencyError


def _play_row() -> dict:
    """schema 契約を満たす spotify.plays 行。"""
    return {
        "play_id": "2023-10-01T00:00:00.000Z_t1",
        "played_at_utc": datetime(2023, 10, 1, tzinfo=UTC),
        "track_id": "t1",
        "track_name": "Song A",
    }


class TestSpotifyStorage(unittest.TestCase):
    def setUp(self):
        self.mock_boto3 = patch("pipelines.sources.spotify.storage.boto3").start()
        self.mock_s3 = MagicMock()
        self.mock_boto3.client.return_value = self.mock_s3

        self.storage = SpotifyStorage(
            endpoint_url="http://test-endpoint",
            access_key_id="test-key",
            secret_access_key="test-secret",
            bucket_name="test-bucket",
            raw_path="raw/",
            events_path="events/",
            master_path="master/",
        )

    def tearDown(self):
        patch.stopall()

    def test_save_raw_json(self):
        # Arrange: 保存するデータの準備
        data = [{"id": "1", "name": "test"}]

        # Act: RAW JSON として保存を実行
        key = self.storage.save_raw_json(data, prefix="test_prefix")

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(call_args["Key"].startswith("raw/test_prefix/"))
        self.assertTrue(call_args["Key"].endswith(".json"))
        self.assertEqual(call_args["ContentType"], "application/json")
        self.assertIsNotNone(key)

    def test_save_parquet(self):
        # Arrange: 保存するデータの準備
        data = [_play_row()]

        # Act: Parquet 形式での保存を実行
        key = self.storage.save_parquet(
            data,
            year=2023,
            month=10,
            dataset=datasets.SPOTIFY_PLAYS,
        )

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(
            call_args["Key"].startswith(
                "events/spotify/plays/year=2023/month=10/"
            )
        )
        self.assertTrue(call_args["Key"].endswith(".parquet"))
        self.assertEqual(call_args["ContentType"], "application/octet-stream")
        self.assertIsNotNone(key)

    def test_save_parquet_returns_none_without_upload_on_missing_required_column(
        self,
    ):
        # Arrange: 必須カラム欠落データ
        data = [{"play_id": "p1", "track_name": "Song A"}]

        # Act: 保存を実行
        key = self.storage.save_parquet(
            data,
            year=2023,
            month=10,
            dataset=datasets.SPOTIFY_PLAYS,
        )

        # Assert: アップロードされず None を返す
        self.mock_s3.put_object.assert_not_called()
        self.assertIsNone(key)

    def test_save_parquet_returns_none_without_upload_on_type_mismatch(self):
        # Arrange: played_at_utc が文字列（契約違反）のデータ
        data = [
            {
                "play_id": "2023-10-01T00:00:00.000Z_t1",
                "played_at_utc": "2023-10-01T00:00:00Z",
                "track_id": "t1",
                "track_name": "Song A",
            }
        ]

        # Act: 保存を実行
        key = self.storage.save_parquet(
            data,
            year=2023,
            month=10,
            dataset=datasets.SPOTIFY_PLAYS,
        )

        # Assert: アップロードされず None を返す
        self.mock_s3.put_object.assert_not_called()
        self.assertIsNone(key)

    def test_save_parquet_returns_none_without_upload_when_data_is_empty(self):
        # Arrange: 保存対象なし
        # Act: 保存を実行
        key = self.storage.save_parquet(
            [],
            year=2023,
            month=10,
            dataset=datasets.SPOTIFY_PLAYS,
        )

        # Assert: アップロードされず None を返す
        self.mock_s3.put_object.assert_not_called()
        self.assertIsNone(key)

    def test_get_ingest_state_exists(self):
        # Arrange: 保存されている状態がある場合をモック
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"cursor": 123}).encode("utf-8")
        self.mock_s3.get_object.return_value = {"Body": mock_body}

        # Act: 保存されている状態を取得
        state = self.storage.get_ingest_state()

        # Assert: 取得された状態を検証
        self.assertEqual(state, {"cursor": 123})
        self.mock_s3.get_object.assert_called_with(
            Bucket="test-bucket", Key="state/spotify_ingest_state.json"
        )

    def test_save_ingest_state(self):
        # Arrange: 保存する状態の準備
        state = {"cursor": 456}

        # Act: 状態の保存を実行
        self.storage.save_ingest_state(state)

        # Assert: put_object が正しい引数で呼ばれたことを検証
        self.mock_s3.put_object.assert_called()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Key"], "state/spotify_ingest_state.json")
        self.assertEqual(json.loads(call_args["Body"]), state)

    def test_get_ingest_state_raises_on_unexpected_client_error(self):
        error_response = {"Error": {"Code": "AccessDenied", "Message": "denied"}}
        self.mock_s3.get_object.side_effect = ClientError(error_response, "get_object")

        with self.assertRaises(StorageConsistencyError):
            self.storage.get_ingest_state()

    def test_save_ingest_state_raises_on_write_failure(self):
        self.mock_s3.put_object.side_effect = RuntimeError("write failed")

        with self.assertRaises(StorageConsistencyError):
            self.storage.save_ingest_state({"cursor": 456})

    def test_save_master_parquet_with_partition(self):
        # Arrange: 保存するデータの準備
        data = [
            {
                "track_id": "t1",
                "name": "Song A",
                "updated_at": datetime(2024, 1, 1, tzinfo=UTC),
            }
        ]

        # Act: パーティション付きで保存を実行
        key = self.storage.save_master_parquet(
            data,
            dataset=datasets.SPOTIFY_TRACKS,
            year=2024,
            month=1,
        )

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(
            call_args["Key"].startswith("master/spotify/tracks/year=2024/month=01/")
        )
        self.assertTrue(call_args["Key"].endswith(".parquet"))
        self.assertEqual(call_args["ContentType"], "application/octet-stream")
        self.assertIsNotNone(key)

    def test_save_master_parquet_without_partition(self):
        # Arrange: 保存するデータの準備
        data = [
            {
                "artist_id": "a1",
                "name": "Artist A",
                "updated_at": datetime(2024, 1, 1, tzinfo=UTC),
            }
        ]

        # Act: パーティションなしで保存を実行
        key = self.storage.save_master_parquet(
            data,
            dataset=datasets.SPOTIFY_ARTISTS,
        )

        # Assert: 保存結果を検証
        self.mock_s3.put_object.assert_called_once()
        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(call_args["Bucket"], "test-bucket")
        self.assertTrue(call_args["Key"].startswith("master/spotify/artists/"))
        self.assertTrue(call_args["Key"].endswith(".parquet"))
        self.assertEqual(call_args["ContentType"], "application/octet-stream")
        self.assertIsNotNone(key)

    def test_compact_month_for_events_saves_fixed_key(self):
        data = [{"play_id": "play_1", "track_name": "Song A"}]

        with patch(
            "pipelines.sources.spotify.storage.read_parquet_records_from_prefix",
            return_value=data,
        ):
            with patch(
                "pipelines.sources.spotify.storage.dataframe_to_parquet_bytes",
                return_value=b"x",
            ):
                key = self.storage.compact_month(
                    dataset=datasets.SPOTIFY_PLAYS,
                    year=2024,
                    month=1,
                )

        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(
            call_args["Key"],
            "compacted/events/spotify/plays/year=2024/month=01/data.parquet",
        )
        self.assertEqual(key, call_args["Key"])
