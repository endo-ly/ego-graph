"""Google Health詳細検索MCPツール。"""

from typing import Any

from backend.domain.models.tool import ToolBase
from backend.usecases.google_health import (
    GetGoogleHealthDailyMetricsUseCase,
    GetGoogleHealthRecordUseCase,
    GetGoogleHealthSessionsUseCase,
    GetGoogleHealthTimeseriesUseCase,
)


class GetGoogleHealthDailyMetricsTool(ToolBase):
    """日次Projectionを取得する。"""

    def __init__(self, use_case: GetGoogleHealthDailyMetricsUseCase) -> None:
        self._use_case = use_case

    @property
    def name(self) -> str:
        return "get_google_health_daily_metrics"

    @property
    def description(self) -> str:
        return "Google Healthの日次metricを列指向形式で取得します。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return _date_range_schema(optional_data_type=True)

    def execute(
        self,
        start_date: str,
        end_date: str,
        data_type: str | None = None,
    ) -> dict[str, Any]:
        """日次Projectionを取得する。"""
        return self._use_case.execute(start_date, end_date, data_type)


class GetGoogleHealthTimeseriesTool(ToolBase):
    """Google Health sampleまたはinterval時系列を取得する。"""

    def __init__(self, use_case: GetGoogleHealthTimeseriesUseCase) -> None:
        self._use_case = use_case

    @property
    def name(self) -> str:
        return "get_google_health_timeseries"

    @property
    def description(self) -> str:
        return "Google Healthのsampleまたはintervalをrawまたは集約時系列で取得します。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "data_type": {"type": "string", "description": "例: heart-rate"},
                "start_at": {"type": "string", "format": "date-time"},
                "end_at": {"type": "string", "format": "date-time"},
                "metric": {
                    "type": "string",
                    "description": "metric（複数metric型では必須。例: rmssd）",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["auto", "raw", "5m", "15m", "30m", "1h"],
                    "default": "auto",
                },
            },
            "required": ["data_type", "start_at", "end_at"],
        }

    def execute(
        self,
        data_type: str,
        start_at: str,
        end_at: str,
        resolution: str = "auto",
        metric: str | None = None,
    ) -> dict[str, Any]:
        """sampleまたはinterval時系列を取得する。"""
        return self._use_case.execute(
            data_type,
            start_at,
            end_at,
            resolution,
            metric,
        )


class GetGoogleHealthSessionsTool(ToolBase):
    """sleep/exercise sessionを取得する。"""

    def __init__(self, use_case: GetGoogleHealthSessionsUseCase) -> None:
        self._use_case = use_case

    @property
    def name(self) -> str:
        return "get_google_health_sessions"

    @property
    def description(self) -> str:
        return "Google Healthの睡眠・運動sessionを列指向形式で取得します。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return _date_range_schema(optional_data_type=True)

    def execute(
        self,
        start_date: str,
        end_date: str,
        data_type: str | None = None,
    ) -> dict[str, Any]:
        """sessionを取得する。"""
        return self._use_case.execute(start_date, end_date, data_type)


class GetGoogleHealthRecordTool(ToolBase):
    """完全保存recordを取得する。"""

    def __init__(self, use_case: GetGoogleHealthRecordUseCase) -> None:
        self._use_case = use_case

    @property
    def name(self) -> str:
        return "get_google_health_record"

    @property
    def description(self) -> str:
        return "record_idでGoogle Healthの元payloadを完全なJSONとして取得します。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
        }

    def execute(self, record_id: str) -> dict[str, Any]:
        """完全保存recordを取得する。"""
        return self._use_case.execute(record_id)


def _date_range_schema(*, optional_data_type: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
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
    }
    if optional_data_type:
        properties["data_type"] = {
            "type": "string",
            "description": "Google Health data type（任意）",
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ["start_date", "end_date"],
    }
