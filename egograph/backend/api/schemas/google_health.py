"""Google Health APIレスポンススキーマ。"""

from datetime import date

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
