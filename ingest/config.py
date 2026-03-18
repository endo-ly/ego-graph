"""EgoGraph Ingest設定モデル。

shared.configから移行 - Ingestサービス用の設定クラスを定義します。
"""

from pydantic import BaseModel, SecretStr, field_validator


class YouTubeConfig(BaseModel):
    """YouTube API設定。"""

    youtube_api_key: SecretStr


class GoogleActivityConfig(BaseModel):
    """Google Activity API設定。"""

    accounts: list[str]


class LastFmConfig(BaseModel):
    """Last.fm API設定。"""

    api_key: str
    api_secret: SecretStr


class SpotifyConfig(BaseModel):
    """Spotify API設定。"""

    client_id: str
    client_secret: SecretStr
    refresh_token: SecretStr
    redirect_uri: str = "http://127.0.0.1:8888/callback"
    scope: str = (
        "user-read-recently-played playlist-read-private playlist-read-collaborative"
    )


class GitHubWorklogConfig(BaseModel):
    """GitHub作業ログ取り込み設定。"""

    token: SecretStr
    github_login: str  # 個人所有Repoフィルタ用
    target_repos: list[str] | None = None  # Noneの場合は全Repo対象
    backfill_days: int = 365
    fetch_commit_details: bool = True
    max_commit_detail_requests_per_repo: int = 200


class EmbeddingConfig(BaseModel):
    """埋め込みモデル設定(ローカル実行)。"""

    model_name: str = "cl-nagoya/ruri-v3-310m"
    batch_size: int = 32
    device: str | None = None
    expected_dimension: int = 768


class QdrantConfig(BaseModel):
    """Qdrant Cloud設定。"""

    url: str
    api_key: SecretStr
    collection_name: str = "egograph_spotify_ruri"
    vector_size: int = 768
    batch_size: int = 1000

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """URLがスラッシュで終わっていないことを確認します。"""
        return v.rstrip("/")


class R2Config(BaseModel):
    """Cloudflare R2設定 (S3互換)。"""

    endpoint_url: str
    access_key_id: str
    secret_access_key: SecretStr
    bucket_name: str = "egograph"
    raw_path: str = "raw/"
    events_path: str = "events/"
    master_path: str = "master/"


class DuckDBConfig(BaseModel):
    """DuckDB設定。"""

    db_path: str = "data/analytics.duckdb"
    r2: R2Config | None = None


class Config(BaseModel):
    """メイン設定オブジェクト。"""

    log_level: str = "INFO"

    spotify: SpotifyConfig | None = None
    lastfm: LastFmConfig | None = None
    google_activity: GoogleActivityConfig | None = None
    youtube: YouTubeConfig | None = None
    github_worklog: GitHubWorklogConfig | None = None
    embedding: EmbeddingConfig | None = None
    qdrant: QdrantConfig | None = None
    duckdb: DuckDBConfig | None = None

    def validate_all(self) -> None:
        """全ての必須設定が存在することを検証します。"""
        if not self.spotify:
            raise ValueError("Spotify configuration is required")
        if not self.embedding:
            raise ValueError("Embedding configuration is required")
        if not self.qdrant:
            raise ValueError("Qdrant configuration is required")


__all__ = [
    "Config",
    "DuckDBConfig",
    "EmbeddingConfig",
    "GitHubWorklogConfig",
    "GoogleActivityConfig",
    "LastFmConfig",
    "QdrantConfig",
    "R2Config",
    "SpotifyConfig",
    "YouTubeConfig",
]
