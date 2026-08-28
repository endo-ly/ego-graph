"""Google Healthデータ取得Repositoryのインターフェース。"""

from datetime import date, datetime
from typing import Any, Protocol


class GoogleHealthRepositoryProtocol(Protocol):
    """Google Health日次サマリの取得契約。"""

    def get_daily_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """指定期間の日次健康サマリを取得する。"""
        ...

    def get_daily_metrics(
        self,
        start_date: date,
        end_date: date,
        data_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定期間の日次Projectionを取得する。"""
        ...

    def get_timeseries(
        self,
        data_type: str,
        start_at: datetime,
        end_at: datetime,
        metric: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定data typeの生sampleまたはintervalを取得する。"""
        ...

    def get_sessions(
        self,
        start_date: date,
        end_date: date,
        data_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """指定期間のsessionを取得する。"""
        ...

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        """record_idで完全保存recordを取得する。"""
        ...
