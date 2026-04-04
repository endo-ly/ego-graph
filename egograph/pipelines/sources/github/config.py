"""GitHub作業ログ取り込み固有の定数・設定定義。

このモジュールでは、GitHub API関連の定数値を定義します。
"""

# GitHub API制限
PR_PER_PAGE = 100
COMMITS_PER_PAGE = 100
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2

# APIエンドポイント
API_BASE_URL = "https://api.github.com"
API_REPOS_LIST = "/user/repos"
API_REPOS_GET = "/repos/{owner}/{repo}"
API_PRS_LIST = "/repos/{owner}/{repo}/pulls"
API_PR_COMMITS = "/repos/{owner}/{repo}/pulls/{pull_number}/commits"
API_PR_REVIEWS = "/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
API_COMMITS_LIST = "/repos/{owner}/{repo}/commits"
API_COMMIT_GET = "/repos/{owner}/{repo}/commits/{sha}"

# APIヘッダー
API_ACCEPT_HEADER = "application/vnd.github+json"
API_VERSION = "2022-11-28"
