"""Google Health日次サマリMCPツール。"""

from typing import Any

from backend.domain.models.tool import ToolBase
from backend.usecases.google_health import GetGoogleHealthDailySummaryUseCase


class GetGoogleHealthDailySummaryTool(ToolBase):
    """指定期間の日次健康サマリを取得する。"""

    def __init__(self, use_case: GetGoogleHealthDailySummaryUseCase) -> None:
        self._use_case = use_case

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

    def execute(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """指定期間の日次健康サマリを取得する。"""
        return self._use_case.execute(start_date, end_date)
