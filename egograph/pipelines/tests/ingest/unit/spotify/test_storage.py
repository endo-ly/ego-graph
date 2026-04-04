import json
import unittest
from unittest.mock import MagicMock, patch

from pipelines.sources.spotify.storage import SpotifyStorage


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
        data = [{"col1": 1, "col2": "a"}, {"col1": 2, "col2": "b"}]

        # Act: Parquet 形式での保存を実行
        with patch("pipelines.sources.spotify.storage.pd.DataFrame.to_parquet") as _:
            key = self.storage.save_parquet(
                data, year=2023, month=10, prefix="test_events"
            )

            # Assert: 保存結果を検証
            self.mock_s3.put_object.assert_called_once()
            call_args = self.mock_s3.put_object.call_args[1]
            self.assertEqual(call_args["Bucket"], "test-bucket")
            self.assertTrue(
                call_args["Key"].startswith("events/test_events/year=2023/month=10/")
            )
            self.assertTrue(call_args["Key"].endswith(".parquet"))
            self.assertEqual(call_args["ContentType"], "application/octet-stream")
            self.assertIsNotNone(key)

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

    def test_save_master_parquet_with_partition(self):
        # Arrange: 保存するデータの準備
        data = [{"track_id": "t1", "name": "Song A"}]

        # Act: パーティション付きで保存を実行
        with patch("pipelines.sources.spotify.storage.pd.DataFrame.to_parquet") as _:
            key = self.storage.save_master_parquet(
                data, prefix="spotify/tracks", year=2024, month=1
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
        data = [{"artist_id": "a1", "name": "Artist A"}]

        # Act: パーティションなしで保存を実行
        with patch("pipelines.sources.spotify.storage.pd.DataFrame.to_parquet") as _:
            key = self.storage.save_master_parquet(data, prefix="spotify/artists")

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
                    data_domain="events",
                    dataset_path="spotify/plays",
                    year=2024,
                    month=1,
                    dedupe_key="play_id",
                )

        call_args = self.mock_s3.put_object.call_args[1]
        self.assertEqual(
            call_args["Key"],
            "compacted/events/spotify/plays/year=2024/month=01/data.parquet",
        )
        self.assertEqual(key, call_args["Key"])
