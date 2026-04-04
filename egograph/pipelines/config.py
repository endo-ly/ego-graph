"""Pipelines サービス設定。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelinesConfig(BaseSettings):
    """pipelines サービスの実行設定。"""

    model_config = SettingsConfigDict(env_prefix="PIPELINES_", extra="ignore")

    database_path: Path = Path("data/pipelines/state.sqlite3")
    logs_root: Path = Path("data/pipelines/logs")
    host: str = "127.0.0.1"
    port: int = 8010
    timezone: str = "UTC"
    dispatcher_poll_seconds: float = 1.0
    lock_lease_seconds: int = 300
    lock_heartbeat_seconds: int = 30
