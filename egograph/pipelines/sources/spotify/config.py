"""Spotify固有の設定。"""

# データ収集に必要なOAuthスコープ
REQUIRED_SCOPES = [
    "user-read-recently-played",  # 最近再生したトラック
    "playlist-read-private",  # プライベートプレイリスト
    "playlist-read-collaborative",  # コラボレーティブプレイリスト
]

# API制限
RECENTLY_PLAYED_LIMIT = 50  # Spotify APIによる最大許容数
PLAYLISTS_LIMIT = 50  # ページネーションの妥当なデフォルト値

# レート制限
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2  # 指数バックオフ: 2, 4, 8秒
