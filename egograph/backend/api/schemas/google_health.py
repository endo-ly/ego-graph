"""Google Health APIレスポンススキーマ。"""

from datetime import date
from typing import Any

from pydantic import BaseModel


class GoogleHealthDailySummaryResponse(BaseModel):
    """Google Health日次サマリ。"""

    date: date
    steps: float | None = None
    distance: float | None = None
    total_calories: float | None = None
    active_energy_burned: float | None = None
    active_minutes: float | None = None
    active_zone_minutes: float | None = None
    resting_heart_rate: float | None = None
    daily_hrv: float | None = None
    daily_oxygen_saturation: float | None = None
    daily_respiratory_rate: float | None = None
    sleep_duration: float | None = None
    daily_vo2_max: float | None = None


class GoogleHealthColumnarResponse(BaseModel):
    """Google Healthのcolumnar結果。"""

    columns: list[str]
    rows: list[list[Any]]


class GoogleHealthTimeseriesStats(BaseModel):
    """時系列の基本統計。"""

    avg: float | None = None
    min: float | None = None
    max: float | None = None


class GoogleHealthTimeseriesHighlights(BaseModel):
    """時系列の要点。"""

    peaks: list[list[Any]]
    rises: list[list[Any]]
    falls: list[list[Any]]


class GoogleHealthTimeseriesResponse(BaseModel):
    """Google Health sample/interval時系列。"""

    type: str
    metric: str | None = None
    unit: str | None = None
    resolution: str
    stats: GoogleHealthTimeseriesStats
    series: GoogleHealthColumnarResponse
    highlights: GoogleHealthTimeseriesHighlights


class GoogleHealthRecordResponse(BaseModel):
    """完全保存recordの詳細。"""

    id: str
    type: str
    kind: str
    date: date
    payload: Any
