"""Google Health分析データのUseCase。"""

from datetime import date
from typing import Any

from backend.domain.repositories.google_health import GoogleHealthRepositoryProtocol
from backend.validators import validate_date_range


class GetGoogleHealthDailySummaryUseCase:
    """指定期間のGoogle Health日次サマリを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        start_date: date | str,
        end_date: date | str,
    ) -> list[dict[str, Any]]:
        """日付範囲を検証して日次サマリを取得する。"""
        start, end = validate_date_range(start_date, end_date)
        return self._repository.get_daily_summary(start, end)
