"""FastAPI routers."""

from . import (
    browser_history_data,
    chat,
    data,
    github,
    health,
    system_prompts,
    threads,
)

__all__ = [
    "browser_history_data",
    "chat",
    "data",
    "github",
    "health",
    "system_prompts",
    "threads",
]
