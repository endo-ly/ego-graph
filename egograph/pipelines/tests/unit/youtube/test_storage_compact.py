"""YouTube storage compact_month の単体テスト。"""

from io import BytesIO
from unittest.mock import MagicMock

import pandas as pd
from pipelines.sources.youtube.storage import YouTubeStorage

_S3_KEY_PREFIX = "events/youtube/watch_events/year=2026/month=04/"


def _storage() -> YouTubeStorage:
    return YouTubeStorage(
        endpoint_url="http://localhost:9000",
        access_key_id="test",
        secret_access_key="test",
        bucket_name="test-bucket",
    )


def _make_parquet_bytes(rows: list[dict]) -> bytes:
    buf = BytesIO()
    pd.DataFrame(rows).to_parquet(buf, index=False, engine="pyarrow")
    buf.seek(0)
    return buf.getvalue()


def _mock_s3_with_records(
    parquet_bytes: bytes, s3_key: str
) -> tuple[MagicMock, MagicMock]:
    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{"Contents": [{"Key": s3_key}]}]
    mock_s3.get_paginator.return_value = mock_paginator
    mock_s3.get_object.return_value = {"Body": BytesIO(parquet_bytes)}
    return mock_s3, mock_paginator


def _watch_event_row(watch_event_id: str, watched_at: str, video_id: str) -> dict:
    """schema 契約を満たす watch event 行。"""
    return {
        "watch_event_id": watch_event_id,
        "watched_at_utc": pd.Timestamp(f"{watched_at}Z"),
        "video_id": video_id,
        "source_event_id": f"src-{watch_event_id}",
    }


def test_compact_month_reads_source_and_saves_compacted(monkeypatch):
    """source prefix の parquet を読み込み、compacted key で保存する。"""
    storage = _storage()

    records = [_watch_event_row("we-1", "2026-04-10T12:00:00", "v1")]
    parquet_bytes = _make_parquet_bytes(records)
    mock_s3, _ = _mock_s3_with_records(parquet_bytes, f"{_S3_KEY_PREFIX}sync.parquet")

    monkeypatch.setattr(storage, "s3", mock_s3)

    result = storage.compact_month(year=2026, month=4)

    assert result is not None
    assert "compacted/" in result
    assert "year=2026/month=04/data.parquet" in result
    mock_s3.put_object.assert_called_once()
    put_call = mock_s3.put_object.call_args
    assert put_call.kwargs["Bucket"] == "test-bucket"
    assert put_call.kwargs["Key"] == result
    assert put_call.kwargs["ContentType"] == "application/octet-stream"


def test_compact_month_returns_none_when_no_records(monkeypatch):
    """source prefix に parquet が存在しない場合は None を返す。"""
    storage = _storage()

    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{}]
    mock_s3.get_paginator.return_value = mock_paginator

    monkeypatch.setattr(storage, "s3", mock_s3)

    result = storage.compact_month(year=2026, month=1)

    assert result is None
    mock_s3.put_object.assert_not_called()


def test_compact_month_deduplicates_by_watch_event_id(monkeypatch):
    """重複する watch_event_id は dedupe される。"""
    storage = _storage()

    records = [
        _watch_event_row("we-1", "2026-04-10T12:00:00", "v1"),
        _watch_event_row("we-1", "2026-04-10T12:00:00", "v1-dup"),
        _watch_event_row("we-2", "2026-04-11T12:00:00", "v2"),
    ]
    parquet_bytes = _make_parquet_bytes(records)
    mock_s3, _ = _mock_s3_with_records(parquet_bytes, f"{_S3_KEY_PREFIX}a.parquet")

    monkeypatch.setattr(storage, "s3", mock_s3)

    result = storage.compact_month(year=2026, month=4)

    assert result is not None
    put_body = mock_s3.put_object.call_args.kwargs["Body"]
    compacted_df = pd.read_parquet(BytesIO(put_body))
    assert len(compacted_df) == 2
    assert set(compacted_df["watch_event_id"].tolist()) == {"we-1", "we-2"}


def test_compact_month_sorts_by_watched_at_utc(monkeypatch):
    """watched_at_utc でソートし、重複時は最後を残す。"""
    storage = _storage()

    records = [
        _watch_event_row("we-1", "2026-04-10T12:00:00", "v1-old"),
        _watch_event_row("we-2", "2026-04-09T12:00:00", "v2"),
        _watch_event_row("we-1", "2026-04-11T12:00:00", "v1-new"),
    ]
    parquet_bytes = _make_parquet_bytes(records)
    mock_s3, _ = _mock_s3_with_records(parquet_bytes, f"{_S3_KEY_PREFIX}a.parquet")

    monkeypatch.setattr(storage, "s3", mock_s3)

    result = storage.compact_month(year=2026, month=4)

    assert result is not None
    put_body = mock_s3.put_object.call_args.kwargs["Body"]
    compacted_df = pd.read_parquet(BytesIO(put_body))
    # we-1 の最後 (v1-new) が残る
    we1_row = compacted_df[compacted_df["watch_event_id"] == "we-1"].iloc[0]
    assert we1_row["video_id"] == "v1-new"
    # ソート順: we-2 (04-09) -> we-1 (04-11)
    assert compacted_df.iloc[0]["watch_event_id"] == "we-2"
    assert compacted_df.iloc[1]["watch_event_id"] == "we-1"
