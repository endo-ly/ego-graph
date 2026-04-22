"""YouTube storage unit tests."""

from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from pipelines.sources.youtube.storage import YouTubeStorage


def _storage() -> YouTubeStorage:
    return YouTubeStorage(
        endpoint_url="http://localhost:9000",
        access_key_id="test",
        secret_access_key="test",
        bucket_name="test-bucket",
    )


def test_save_video_master_upserts_by_video_id(monkeypatch):
    """video master は video_id ごとに upsert 保存される。"""
    storage = _storage()
    monkeypatch.setattr(
        storage,
        "_load_master_rows_with_etag",
        lambda _key: (
            [
                {"video_id": "v1", "title": "old-title"},
                {"video_id": "v2", "title": "stay-title"},
            ],
            "etag-1",
        ),
    )
    mock_save = MagicMock(return_value="master/youtube/videos/data.parquet")
    monkeypatch.setattr(storage, "_save_dataframe_key_with_condition", mock_save)

    result = storage.save_video_master(
        [
            {"video_id": "v1", "title": "new-title"},
            {"video_id": "v3", "title": "new-video"},
        ]
    )

    assert result == "master/youtube/videos/data.parquet"
    saved_rows = mock_save.call_args.args[0]
    assert saved_rows == [
        {"video_id": "v1", "title": "new-title"},
        {"video_id": "v2", "title": "stay-title"},
        {"video_id": "v3", "title": "new-video"},
    ]
    assert mock_save.call_args.args[1] == "master/youtube/videos/data.parquet"
    assert mock_save.call_args.kwargs["if_match"] == "etag-1"
    assert mock_save.call_args.kwargs["if_none_match"] is None
    assert mock_save.call_args.kwargs["reraise"] is True


def test_save_channel_master_upserts_by_channel_id(monkeypatch):
    """channel master は channel_id ごとに upsert 保存される。"""
    storage = _storage()
    monkeypatch.setattr(
        storage,
        "_load_master_rows_with_etag",
        lambda _key: (
            [
                {"channel_id": "c1", "channel_name": "old"},
                {"channel_id": "c2", "channel_name": "stay"},
            ],
            "etag-1",
        ),
    )
    mock_save = MagicMock(return_value="master/youtube/channels/data.parquet")
    monkeypatch.setattr(storage, "_save_dataframe_key_with_condition", mock_save)

    result = storage.save_channel_master(
        [
            {"channel_id": "c1", "channel_name": "new"},
            {"channel_id": "c3", "channel_name": "new-channel"},
        ]
    )

    assert result == "master/youtube/channels/data.parquet"
    saved_rows = mock_save.call_args.args[0]
    assert saved_rows == [
        {"channel_id": "c1", "channel_name": "new"},
        {"channel_id": "c2", "channel_name": "stay"},
        {"channel_id": "c3", "channel_name": "new-channel"},
    ]
    assert mock_save.call_args.args[1] == "master/youtube/channels/data.parquet"
    assert mock_save.call_args.kwargs["if_match"] == "etag-1"
    assert mock_save.call_args.kwargs["if_none_match"] is None
    assert mock_save.call_args.kwargs["reraise"] is True


def test_save_video_master_retries_on_precondition_failed(monkeypatch):
    """条件付き保存が 412 のときはリトライして保存する。"""
    storage = _storage()
    load_mock = MagicMock(side_effect=[([], None), ([], None)])
    monkeypatch.setattr(storage, "_load_master_rows_with_etag", load_mock)
    monkeypatch.setattr(
        "pipelines.sources.youtube.storage.time.sleep", lambda _seconds: None
    )
    precondition_error = ClientError(
        {
            "Error": {"Code": "PreconditionFailed", "Message": "etag mismatch"},
            "ResponseMetadata": {"HTTPStatusCode": 412},
        },
        "PutObject",
    )
    save_mock = MagicMock(
        side_effect=[
            precondition_error,
            "master/youtube/videos/data.parquet",
        ]
    )
    monkeypatch.setattr(storage, "_save_dataframe_key_with_condition", save_mock)

    result = storage.save_video_master([{"video_id": "v1", "title": "new-title"}])

    assert result == "master/youtube/videos/data.parquet"
    assert load_mock.call_count == 2
    assert save_mock.call_count == 2
