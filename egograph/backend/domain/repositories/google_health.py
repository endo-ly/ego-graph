"""Google Healthデータ取得Repositoryのインターフェース。"""

from datetime import date
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
