"""Google Health日次サマリ取得ツール。"""

from typing import Any

from backend.domain.models.tool import ToolBase
from backend.domain.repositories.google_health import GoogleHealthRepositoryProtocol
from backend.validators import validate_date_range


class GetGoogleHealthDailySummaryTool(ToolBase):
    """指定期間の日次健康サマリを取得する。"""

    def __init__(self, repository: GoogleHealthRepositoryProtocol) -> None:
        self.repository = repository

    @property
    def name(self) -> str:
        return "get_google_health_daily_summary"

    @property
    def description(self) -> str:
        return (
            "指定期間のGoogle Health日次サマリを取得します。"
            "歩数、活動量、睡眠、心拍、HRV、SpO2、呼吸数を日付ごとに返します。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "format": "date",
                    "description": "開始日（YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "format": "date",
                    "description": "終了日（YYYY-MM-DD）",
                },
            },
            "required": ["start_date", "end_date"],
        }

    def execute(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """指定期間の日次健康サマリを取得する。"""
        start, end = validate_date_range(start_date, end_date)
        return self.repository.get_daily_summary(start, end)
