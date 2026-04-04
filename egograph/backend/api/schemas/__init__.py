"""API Schemas.

API用のリクエスト/レスポンススキーマを定義します。
"""

from backend.api.schemas.chat import ChatRequest, ChatResponse, ToolInfo, ToolsResponse
from backend.api.schemas.data import (
    ListeningStatsResponse,
    PageViewResponse,
    TopChannelResponse,
    TopDomainResponse,
    TopTrackResponse,
    WatchHistoryResponse,
    WatchingStatsResponse,
)
from backend.api.schemas.github import (
    ActivityStatsResponse,
    CommitResponse,
    PullRequestResponse,
    RepositoryResponse,
    RepoSummaryStatsResponse,
)
from backend.api.schemas.models import ModelsResponse
from backend.api.schemas.system_prompt import (
    SystemPromptResponse,
    SystemPromptUpdateRequest,
)
from backend.api.schemas.thread import (
    ThreadListResponse,
    ThreadMessagesResponse,
)
from backend.domain.models.llm_model import DEFAULT_MODEL, LLMModel

# ドメインモデルも便利のため再エクスポート
from backend.domain.models.thread import Thread, ThreadMessage
from backend.usecases.llm_model import get_all_models, get_model

__all__ = [
    # Chat API スキーマ
    "ChatRequest",
    "ChatResponse",
    "ToolInfo",
    "ToolsResponse",
    # Data API スキーマ
    "TopTrackResponse",
    "ListeningStatsResponse",
    "PageViewResponse",
    "WatchHistoryResponse",
    "WatchingStatsResponse",
    "TopDomainResponse",
    "TopChannelResponse",
    # GitHub API スキーマ
    "PullRequestResponse",
    "CommitResponse",
    "RepositoryResponse",
    "ActivityStatsResponse",
    "RepoSummaryStatsResponse",
    # Models API スキーマ
    "ModelsResponse",
    "LLMModel",
    "DEFAULT_MODEL",
    "get_model",
    "get_all_models",
    # Thread API スキーマ
    "ThreadListResponse",
    "ThreadMessagesResponse",
    # System Prompt API スキーマ
    "SystemPromptResponse",
    "SystemPromptUpdateRequest",
    # ドメインモデル
    "Thread",
    "ThreadMessage",
]
