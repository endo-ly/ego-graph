"""バックエンド全体で使用する定数。

SQLクエリ、API制限、タイムアウト値などのマジックナンバーを管理します。
"""

# SQL/Query Limits
DEFAULT_TOP_TRACKS_LIMIT = 10
DEFAULT_SEARCH_TRACKS_LIMIT = 20
DEFAULT_PAGE_VIEWS_LIMIT = 50
DEFAULT_TOP_DOMAINS_LIMIT = 20
HEALTH_CHECK_LIMIT = 1
DEFAULT_THREAD_LIST_LIMIT = 10
DEFAULT_LIMIT = 100  # GitHub API default limit

# API/Validation Limits
MIN_LIMIT = 1
MAX_LIMIT = 100

# Timeouts (seconds)
LLM_REQUEST_TIMEOUT = 60.0
TOTAL_CHAT_TIMEOUT = 90.0

# Conversion Factors
MS_TO_MINUTES_FACTOR = 60000.0

# Tool Execution
MAX_TOOL_ITERATIONS = 5

# Daily Timeline
DEFAULT_TIMELINE_LIMIT = 500
MAX_TIMELINE_LIMIT = 2000
DEFAULT_GAP_MINUTES = 120
MAX_GAP_MINUTES = 1440  # 24時間分

# Daily Timeline が扱う source 一覧。items に混ぜる source と、
# daily_summaries / coverage にのみ現れる source を含む。
TIMELINE_SOURCES = (
    "spotify",
    "youtube",
    "browser_history",
    "github",
    "google_health",
)

# 同一時刻の item 整列で使う source 優先度（小さいほど先）。
# Browser History → YouTube → Spotify → GitHub の順で、ページ遷移から
# 視聴イベントが続く流れを読みやすくする。
TIMELINE_SOURCE_PRIORITY = {
    "browser_history": 0,
    "youtube": 1,
    "spotify": 2,
    "github": 3,
}

# Browser History と YouTube 視聴イベントの関連候補判定窓（秒）。
CORRELATION_YOUTUBE_WINDOW_SECONDS = 120
