"""Google Health UseCaseのテスト。"""

from datetime import date

import pytest
from backend.usecases.google_health import GetGoogleHealthDailySummaryUseCase


class FakeGoogleHealthRepository:
    """UseCaseテスト用Repository。"""

    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def get_daily_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        self.calls.append((start_date, end_date))
        return [{"date": start_date}]


def test_execute_validates_dates_and_delegates_to_repository():
    """有効な日付範囲をRepositoryへ委譲する。"""
    # Arrange
    repository = FakeGoogleHealthRepository()
    use_case = GetGoogleHealthDailySummaryUseCase(repository)

    # Act
    result = use_case.execute("2026-06-01", "2026-06-02")

    # Assert
    assert result == [{"date": date(2026, 6, 1)}]
    assert repository.calls == [(date(2026, 6, 1), date(2026, 6, 2))]


def test_execute_rejects_reversed_date_range():
    """開始日が終了日より後の範囲を拒否する。"""
    # Arrange
    use_case = GetGoogleHealthDailySummaryUseCase(FakeGoogleHealthRepository())

    # Act / Assert
    with pytest.raises(ValueError, match="invalid_date_range:"):
        use_case.execute("2026-06-02", "2026-06-01")
