"""Google Health extractorのテスト。"""

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from pipelines.sources.google_health.data_types import DATA_TYPE_BY_NAME
from pipelines.sources.google_health.extractor import (
    GoogleHealthExtractor,
    _build_filter,
)


class FakeClient:
    """Extractorが使用するclientの記録用fake。"""

    def __init__(self):
        self.reconcile_calls = []
        self.interval_rollup_calls = []
        self.rollup_calls = []

    def reconcile_data_points(self, *args, **kwargs):
        self.reconcile_calls.append((args, kwargs))
        if len(self.reconcile_calls) == 1:
            return {"dataPoints": [{"steps": {}}], "nextPageToken": "next"}
        return {"dataPoints": [{"steps": {}}]}

    def daily_rollup(self, *args, **kwargs):
        self.rollup_calls.append((args, kwargs))
        return {"rollupDataPoints": [{"steps": {"countSum": "1"}}]}

    def rollup(self, *args, **kwargs):
        self.interval_rollup_calls.append((args, kwargs))
        return {
            "rollupDataPoints": [{"caloriesInHeartRateZone": {"kilocaloriesSum": "1"}}]
        }


def test_extract_follows_pagination_and_collects_daily_rollup():
    """reconcileの全pageとdaily rollupを原本へ保持する。"""
    # Arrange
    client = FakeClient()
    extractor = GoogleHealthExtractor(client)

    # Act
    result = extractor.extract(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME["steps"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
    )

    # Assert
    assert len(client.reconcile_calls) == 2
    assert client.reconcile_calls[1][1]["page_token"] == "next"
    assert (
        "steps.interval.start_time"
        in (client.reconcile_calls[0][1]["filter_expression"])
    )
    assert len(result.payload["reconcileResponses"]) == 2
    assert len(result.payload["dailyRollupResponses"]) == 1
    assert result.record_count == 3


def test_short_daily_rollup_is_split_into_fourteen_day_ranges():
    """制限対象data typeのdaily rollupは14日以下へ分割する。"""
    # Arrange
    client = FakeClient()
    extractor = GoogleHealthExtractor(client)

    # Act
    extractor.extract(
        connection_id="connection-1",
        data_type=DATA_TYPE_BY_NAME["calories-in-heart-rate-zone"],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 2, 1),
    )

    # Assert
    assert len(client.reconcile_calls) == 0
    assert len(client.interval_rollup_calls) == 3
    expected_ranges = [
        (date(2026, 1, 1), date(2026, 1, 15)),
        (date(2026, 1, 15), date(2026, 1, 29)),
        (date(2026, 1, 29), date(2026, 2, 1)),
    ]
    assert [
        (call[1]["date_from"], call[1]["date_to"])
        for call in client.interval_rollup_calls
    ] == expected_ranges
    assert [
        (call[1]["date_from"], call[1]["date_to"]) for call in client.rollup_calls
    ] == expected_ranges


def test_daily_filter_uses_proto_field_name():
    """daily reconcile filterはsnake_caseのproto field名を使う。"""
    # Act
    result = _build_filter(
        DATA_TYPE_BY_NAME["daily-resting-heart-rate"],
        date(2026, 6, 1),
        date(2026, 6, 3),
    )

    # Assert
    assert result == (
        'daily_resting_heart_rate.date >= "2026-06-01" AND '
        'daily_resting_heart_rate.date < "2026-06-03"'
    )


def test_physical_filter_uses_configured_timezone_boundary():
    """物理時刻filterは設定TZのローカル日付境界をUTCへ変換する。"""
    # Act
    result = _build_filter(
        DATA_TYPE_BY_NAME["heart-rate"],
        date(2026, 6, 1),
        date(2026, 6, 2),
        timezone=ZoneInfo("Asia/Tokyo"),
    )

    # Assert
    assert result == (
        'heart_rate.sample_time.physical_time >= "2026-05-31T15:00:00Z" AND '
        'heart_rate.sample_time.physical_time < "2026-06-01T15:00:00Z"'
    )


def test_extract_rejects_empty_or_reversed_range():
    """空または逆転した期間をAPIへ送信しない。"""
    # Arrange
    extractor = GoogleHealthExtractor(FakeClient())

    # Act & Assert
    with pytest.raises(ValueError, match="date_from must be earlier"):
        extractor.extract(
            connection_id="connection-1",
            data_type=DATA_TYPE_BY_NAME["steps"],
            date_from=date(2026, 6, 3),
            date_to=date(2026, 6, 3),
        )
    with pytest.raises(ValueError, match="date_from must be earlier"):
        extractor.extract(
            connection_id="connection-1",
            data_type=DATA_TYPE_BY_NAME["steps"],
            date_from=date(2026, 6, 4),
            date_to=date(2026, 6, 3),
        )


@pytest.mark.parametrize(
    "data_type_name",
    ["steps", "total-calories", "calories-in-heart-rate-zone"],
)
def test_extract_rejects_repeated_page_token(data_type_name):
    """同じpage tokenが再返却された場合は無限取得を防止する。"""

    class RepeatingTokenClient(FakeClient):
        def reconcile_data_points(self, *args, **kwargs):
            return {"dataPoints": [], "nextPageToken": "repeated"}

        def daily_rollup(self, *args, **kwargs):
            return {"rollupDataPoints": [], "nextPageToken": "repeated"}

        def rollup(self, *args, **kwargs):
            return {"rollupDataPoints": [], "nextPageToken": "repeated"}

    extractor = GoogleHealthExtractor(RepeatingTokenClient())

    with pytest.raises(RuntimeError, match="google_health_repeated_page_token"):
        extractor.extract(
            connection_id="connection-1",
            data_type=DATA_TYPE_BY_NAME[data_type_name],
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 2),
        )
