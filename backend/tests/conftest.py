"""Backend テスト用の共有 pytest フィクスチャ。"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import backend.dependencies as deps
from backend.config import BackendConfig, LLMConfig, R2Config
from backend.infrastructure.database import (
    ChatDuckDBConnection,
    chat_connection,
    create_chat_tables,
)
from backend.main import create_app

# ========================================
# 環境変数クリア（テスト用）
# ========================================


@pytest.fixture(autouse=True)
def disable_env_files():
    """Pydantic Settingsの.env読み込みを無効化する。"""
    original_llm_env_file = LLMConfig.model_config.get("env_file")
    original_backend_env_file = BackendConfig.model_config.get("env_file")

    LLMConfig.model_config["env_file"] = []
    BackendConfig.model_config["env_file"] = []

    yield

    LLMConfig.model_config["env_file"] = original_llm_env_file
    BackendConfig.model_config["env_file"] = original_backend_env_file


# ========================================
# 設定フィクスチャ
# ========================================


@pytest.fixture
def mock_r2_config():
    """モックR2設定。"""

    # model_construct()を使って検証をスキップして直接構築
    return R2Config.model_construct(
        endpoint_url="https://test.r2.cloudflarestorage.com",
        access_key_id="test_key",
        secret_access_key=SecretStr("test_secret"),  # SecretStrでラップ
        bucket_name="test-bucket",
        raw_path="raw/",
        events_path="events/",
        master_path="master/",
        local_parquet_root=None,
    )


@pytest.fixture
def mock_llm_config():
    """モックLLM設定。"""

    # model_construct()を使って検証をスキップして直接構築
    return LLMConfig.model_construct(
        openrouter_api_key=SecretStr("test-api-key"),
        default_model="deepseek/deepseek-v3.2",
        temperature=0.7,
        max_tokens=2048,
    )


@pytest.fixture
def mock_backend_config(mock_r2_config, mock_llm_config):
    """モックBackend設定。"""

    # model_construct()を使って検証をスキップして直接構築
    config = BackendConfig.model_construct(
        host="127.0.0.1",
        port=8000,
        reload=False,
        api_key=SecretStr("test-backend-key"),  # SecretStrでラップ
        cors_origins="http://localhost:3000",  # ワイルドカードを避ける
        log_level="DEBUG",
    )
    config.r2 = mock_r2_config
    config.llm = mock_llm_config
    return config


# ========================================
# DuckDB フィクスチャ（実DuckDB使用）
# ========================================


@pytest.fixture
def duckdb_conn():
    """実DuckDB（:memory:）接続。"""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


class DuckDBConnectionWrapper:
    """DuckDB接続のラッパー（テスト用の属性を保持）。"""

    def __init__(self, conn, parquet_path):
        self._conn = conn
        self.test_parquet_path = parquet_path

    def __getattr__(self, name):
        """属性アクセスを内部の接続オブジェクトに委譲。"""
        return getattr(self._conn, name)


@pytest.fixture
def duckdb_with_sample_data(duckdb_conn, tmp_path):
    """サンプルParquetデータを持つDuckDB。"""
    # サンプルデータ作成
    sample_data = pd.DataFrame(
        {
            "played_at_utc": pd.to_datetime(
                [
                    "2024-01-01 10:00:00",
                    "2024-01-01 11:00:00",
                    "2024-01-02 10:00:00",
                    "2024-01-02 11:00:00",
                    "2024-01-03 10:00:00",
                ]
            ),
            "track_id": ["track_1", "track_2", "track_1", "track_3", "track_1"],
            "track_name": ["Song A", "Song B", "Song A", "Song C", "Song A"],
            "artist_names": [
                ["Artist X"],
                ["Artist Y"],
                ["Artist X"],
                ["Artist Z"],
                ["Artist X"],
            ],
            "album_name": ["Album 1", "Album 2", "Album 1", "Album 3", "Album 1"],
            "ms_played": [180000, 200000, 180000, 150000, 180000],
        }
    )

    # Parquetファイルとして保存
    parquet_path = tmp_path / "test_data.parquet"
    sample_data.to_parquet(parquet_path)

    # DuckDBにDataFrameを直接登録（下位互換性のため）
    duckdb_conn.register("sample_data_df", sample_data)
    duckdb_conn.execute("CREATE TABLE spotify_plays AS SELECT * FROM sample_data_df")
    duckdb_conn.unregister("sample_data_df")

    # ラッパーオブジェクトを作成
    wrapper = DuckDBConnectionWrapper(duckdb_conn, str(parquet_path))

    yield wrapper


class YouTubeConnectionWrapper:
    """YouTube用DuckDB接続のラッパー（テスト用の属性を保持）。"""

    def __init__(self, conn, watches_parquet_path, videos_parquet_path):
        self._conn = conn
        self.test_watches_parquet_path = watches_parquet_path
        self.test_videos_parquet_path = videos_parquet_path

    def __getattr__(self, name):
        """属性アクセスを内部の接続オブジェクトに委譲。"""
        return getattr(self._conn, name)


@pytest.fixture
def youtube_with_sample_data(duckdb_conn, tmp_path):
    """サンプルYouTube Parquetデータを持つDuckDB。"""
    # 視聴履歴データ作成
    watches_data = pd.DataFrame(
        {
            "watch_id": ["watch_1", "watch_2", "watch_3", "watch_4", "watch_5"],
            "account_id": ["account_1"] * 5,
            "watched_at_utc": pd.to_datetime(
                [
                    "2024-01-01 10:00:00",
                    "2024-01-01 11:00:00",
                    "2024-01-02 10:00:00",
                    "2024-01-02 11:00:00",
                    "2024-01-03 10:00:00",
                ]
            ),
            "video_id": ["video_1", "video_2", "video_1", "video_3", "video_1"],
            "video_title": [
                "Video A",
                "Video B",
                "Video A",
                "Video C",
                "Video A",
            ],
            "channel_id": [
                "channel_1",
                "channel_2",
                "channel_1",
                "channel_3",
                "channel_1",
            ],
            "channel_name": [
                "Channel X",
                "Channel Y",
                "Channel X",
                "Channel Z",
                "Channel X",
            ],
            "video_url": [
                "https://youtube.com/watch?v=video_1",
                "https://youtube.com/watch?v=video_2",
                "https://youtube.com/watch?v=video_1",
                "https://youtube.com/watch?v=video_3",
                "https://youtube.com/watch?v=video_1",
            ],
            "context": ["{}"] * 5,
        }
    )

    # 動画マスターデータ作成
    videos_data = pd.DataFrame(
        {
            "video_id": ["video_1", "video_2", "video_3"],
            "title": ["Video A", "Video B", "Video C"],
            "channel_id": ["channel_1", "channel_2", "channel_3"],
            "channel_name": ["Channel X", "Channel Y", "Channel Z"],
            "duration_seconds": [600, 900, 300],
            "view_count": [1000, 2000, 3000],
            "like_count": [100, 200, 300],
            "comment_count": [10, 20, 30],
            "published_at": pd.to_datetime(["2023-01-01", "2023-02-01", "2023-03-01"]),
            "thumbnail_url": ["thumb1.jpg", "thumb2.jpg", "thumb3.jpg"],
            "description": ["Desc A", "Desc B", "Desc C"],
            "category_id": [1, 2, 3],
            "tags": [["tag1", "tag2"], ["tag3"], ["tag4", "tag5"]],
            "updated_at": pd.to_datetime(["2024-01-01"] * 3),
        }
    )

    # Parquetファイルとして保存
    watches_parquet_path = tmp_path / "youtube_watches.parquet"
    videos_parquet_path = tmp_path / "youtube_videos.parquet"
    watches_data.to_parquet(watches_parquet_path)
    videos_data.to_parquet(videos_parquet_path)

    # DuckDBにDataFrameを直接登録
    duckdb_conn.register("youtube_watches_df", watches_data)
    duckdb_conn.execute(
        "CREATE TABLE youtube_watches AS SELECT * FROM youtube_watches_df"
    )
    duckdb_conn.unregister("youtube_watches_df")

    duckdb_conn.register("youtube_videos_df", videos_data)
    duckdb_conn.execute(
        "CREATE TABLE youtube_videos AS SELECT * FROM youtube_videos_df"
    )
    duckdb_conn.unregister("youtube_videos_df")

    # ラッパーオブジェクトを作成
    wrapper = YouTubeConnectionWrapper(
        duckdb_conn, str(watches_parquet_path), str(videos_parquet_path)
    )

    yield wrapper


class BrowserHistoryConnectionWrapper:
    """Browser History用DuckDB接続のラッパー。"""

    def __init__(self, conn, page_views_parquet_path: str):
        self._conn = conn
        self.test_page_views_parquet_path = page_views_parquet_path

    def __getattr__(self, name):
        """属性アクセスを内部の接続オブジェクトに委譲。"""
        return getattr(self._conn, name)


@pytest.fixture
def browser_history_with_sample_data(duckdb_conn, tmp_path):
    """サンプルBrowser History Parquetデータを持つDuckDB。"""
    page_views_data = pd.DataFrame(
        {
            "page_view_id": [
                "pv_1",
                "pv_2",
                "pv_3",
                "pv_4",
                "pv_5",
            ],
            "started_at_utc": pd.to_datetime(
                [
                    "2026-03-20 10:00:00+00:00",
                    "2026-03-20 10:05:00+00:00",
                    "2026-03-21 08:00:00+00:00",
                    "2026-03-21 08:10:00+00:00",
                    "2026-03-22 12:00:00+00:00",
                ],
                utc=True,
            ),
            "ended_at_utc": pd.to_datetime(
                [
                    "2026-03-20 10:00:01+00:00",
                    "2026-03-20 10:05:03+00:00",
                    "2026-03-21 08:00:00+00:00",
                    "2026-03-21 08:10:02+00:00",
                    "2026-03-22 12:00:04+00:00",
                ],
                utc=True,
            ),
            "url": [
                "https://github.com/owner/repo/pull/79",
                "https://github.com/owner/repo/pulls",
                "https://docs.python.org/3/library/pathlib.html",
                "https://github.com/owner/repo/issues/80",
                "https://news.ycombinator.com/item?id=1",
            ],
            "title": [
                "PR 79",
                "Pull Requests",
                "pathlib",
                "Issue 80",
                "HN",
            ],
            "browser": ["edge", "edge", "edge", "brave", "edge"],
            "profile": ["Default", "Default", "Work", "Default", "Default"],
            "source_device": [
                "home-pc",
                "home-pc",
                "home-pc",
                "home-pc",
                "home-pc",
            ],
            "transition": ["link", "reload", "typed", "link", "typed"],
            "visit_span_count": [2, 3, 1, 1, 4],
            "synced_at_utc": pd.to_datetime(
                ["2026-03-22 12:30:00+00:00"] * 5,
                utc=True,
            ),
            "ingested_at_utc": pd.to_datetime(
                ["2026-03-22 12:31:00+00:00"] * 5, utc=True
            ),
        }
    )

    parquet_path = tmp_path / "browser_history_page_views.parquet"
    page_views_data.to_parquet(parquet_path)

    wrapper = BrowserHistoryConnectionWrapper(duckdb_conn, str(parquet_path))

    yield wrapper


# ========================================
# R2（S3）モックフィクスチャ
# ========================================


@pytest.fixture
def mock_boto3_client():
    """モックboto3 S3クライアント。"""
    with patch("boto3.client") as mock_client:
        s3 = MagicMock()
        mock_client.return_value = s3

        # デフォルト動作設定
        s3.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
        s3.get_object.return_value = {
            "Body": BytesIO(b'{"cursor": 123456789}'),
            "ContentType": "application/json",
        }

        yield s3


# ========================================
# LLM API モックフィクスチャ
# ========================================


@pytest.fixture
def mock_httpx_client():
    """モックhttpxクライアント（LLM API用）。"""
    with patch("httpx.AsyncClient") as mock_client:
        client_instance = MagicMock()
        mock_client.return_value.__aenter__.return_value = client_instance

        # デフォルトレスポンス設定
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-test-123",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "This is a test response.",
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        client_instance.post.return_value = mock_response

        yield client_instance


# ========================================
# FastAPI テストクライアント
# ========================================


@pytest.fixture
def test_client(mock_backend_config):
    """FastAPI TestClient。"""

    # テスト用の設定でアプリを作成
    app = create_app(config=mock_backend_config)

    # 依存性オーバーライド用
    app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


# ========================================
# API Data テスト用の共通モック
# ========================================


@pytest.fixture
def mock_db_and_parquet():
    """データAPIテスト用のDB接続とParquetパスのモック。"""
    with patch("backend.api.data.get_db_connection") as mock_get_db:
        mock_conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = mock_conn
        mock_get_db.return_value.__exit__.return_value = False

        yield {"mock_get_db": mock_get_db, "mock_conn": mock_conn}


# ========================================
# チャット履歴テスト用フィクスチャ
# ========================================


@pytest.fixture
def test_client_with_chat_db(tmp_path, monkeypatch):
    """チャット履歴DBを使用するテストクライアントを提供します。

    LLM、R2、チャット履歴DBを設定したFastAPIテストクライアントを返します。
    統合テストで使用します。
    """

    # 一時的なチャット履歴DBパスを設定
    chat_db_path = tmp_path / "test_chat.duckdb"

    # chat_connection.pyのDB_PATHをモンキーパッチ
    monkeypatch.setattr(chat_connection, "DB_PATH", chat_db_path)

    # LLM APIキーとモデルを設定（モックLLMを使用）
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-v3.2")

    # R2設定（ダミー）
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

    # テーブルを事前に作成
    with ChatDuckDBConnection() as conn:
        create_chat_tables(conn)

    app = create_app()
    client = TestClient(app)

    yield client


# ========================================
# GitHub テスト用フィクスチャ
# ========================================


class GitHubConnectionWrapper:
    """GitHub用DuckDB接続のラッパー（テスト用の属性を保持）。"""

    def __init__(
        self,
        conn,
        prs_parquet_path: str,
        commits_parquet_path: str,
        repos_parquet_path: str,
    ):
        self._conn = conn
        self.test_prs_parquet_path = prs_parquet_path
        self.test_commits_parquet_path = commits_parquet_path
        self.test_repos_parquet_path = repos_parquet_path

    def __getattr__(self, name):
        """属性アクセスを内部の接続オブジェクトに委譲。"""
        return getattr(self._conn, name)


@pytest.fixture
def github_with_sample_data(duckdb_conn, tmp_path):
    """サンプルGitHub Parquetデータを持つDuckDB。"""
    # PRイベントデータ作成
    prs_data = pd.DataFrame(
        {
            "pr_event_id": ["pr_event_1", "pr_event_2", "pr_event_3"],
            "pr_key": ["pr_key_1", "pr_key_1", "pr_key_2"],
            "source": ["github"] * 3,
            "owner": ["test_owner"] * 3,
            "repo": ["test_repo"] * 3,
            "repo_full_name": ["test_owner/test_repo"] * 3,
            "pr_number": [1, 1, 2],
            "pr_id": [101, 101, 102],
            "action": ["opened", "merged", "opened"],
            "state": ["open", "closed", "open"],
            "is_merged": [False, True, False],
            "title": ["Test PR 1", "Test PR 1", "Test PR 2"],
            "labels": [["bug"], ["bug", "enhancement"], ["feature"]],
            "base_ref": ["main"] * 3,
            "head_ref": ["feature-1", "feature-1", "feature-2"],
            "created_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-01 10:00:00", "2024-01-02 10:00:00"]
            ),
            "updated_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 10:00:00", "2024-01-02 10:00:00"]
            ),
            "closed_at_utc": pd.to_datetime(
                [None, "2024-01-02 10:00:00", None]
            ),
            "merged_at_utc": pd.to_datetime(
                [None, "2024-01-02 10:00:00", None]
            ),
            "comments_count": [5, 10, 3],
            "review_comments_count": [2, 5, 1],
            "reviews_count": [1, 2, 0],
            "commits_count": [3, 5, 1],
            "additions": [100, 150, 50],
            "deletions": [20, 30, 10],
            "changed_files_count": [5, 8, 2],
            "ingested_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00"] * 3
            ),
        }
    )

    # Commitイベントデータ作成
    commits_data = pd.DataFrame(
        {
            "commit_event_id": ["commit_1", "commit_2", "commit_3"],
            "source": ["github"] * 3,
            "owner": ["test_owner"] * 3,
            "repo": ["test_repo"] * 3,
            "repo_full_name": ["test_owner/test_repo"] * 3,
            "sha": ["abc123", "def456", "ghi789"],
            "message": [
                "Initial commit",
                "Add feature",
                "Fix bug",
            ],
            "committed_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 10:00:00", "2024-01-03 10:00:00"]
            ),
            "changed_files_count": [5, 3, 1],
            "additions": [100, 50, 10],
            "deletions": [20, 10, 5],
            "ingested_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00"] * 3
            ),
        }
    )

    # Repositoryマスターデータ作成
    repos_data = pd.DataFrame(
        {
            "repo_id": [101, 102],
            "source": ["github"] * 2,
            "owner": ["test_owner"] * 2,
            "repo": ["test_repo", "another_repo"],
            "repo_full_name": ["test_owner/test_repo", "test_owner/another_repo"],
            "description": ["Test repository", "Another test repository"],
            "homepage_url": [None, None],
            "is_private": [False, False],
            "is_fork": [False, True],
            "archived": [False, False],
            "default_branch": ["main", "main"],
            "primary_language": ["Python", "TypeScript"],
            "topics": [["test", "demo"], ["example"]],
            "stargazers_count": [10, 5],
            "forks_count": [2, 1],
            "open_issues_count": [3, 1],
            "size_kb": [100, 50],
            "created_at_utc": pd.to_datetime(
                ["2023-01-01 10:00:00", "2023-02-01 10:00:00"]
            ),
            "updated_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 10:00:00"]
            ),
            "pushed_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", "2024-01-02 10:00:00"]
            ),
            "repo_summary_text": ["Test repo summary", None],
            "summary_source": ["manual", None],
            "summary_updated_at_utc": pd.to_datetime(
                ["2024-01-01 10:00:00", None]
            ),
        }
    )

    # Parquetファイルとして保存
    prs_parquet_path = tmp_path / "github_prs.parquet"
    commits_parquet_path = tmp_path / "github_commits.parquet"
    repos_parquet_path = tmp_path / "github_repos.parquet"
    prs_data.to_parquet(prs_parquet_path)
    commits_data.to_parquet(commits_parquet_path)
    repos_data.to_parquet(repos_parquet_path)

    # DuckDBにDataFrameを直接登録
    duckdb_conn.register("github_prs_df", prs_data)
    duckdb_conn.execute("CREATE TABLE github_prs AS SELECT * FROM github_prs_df")
    duckdb_conn.unregister("github_prs_df")

    duckdb_conn.register("github_commits_df", commits_data)
    duckdb_conn.execute(
        "CREATE TABLE github_commits AS SELECT * FROM github_commits_df"
    )
    duckdb_conn.unregister("github_commits_df")

    duckdb_conn.register("github_repos_df", repos_data)
    duckdb_conn.execute(
        "CREATE TABLE github_repos AS SELECT * FROM github_repos_df"
    )
    duckdb_conn.unregister("github_repos_df")

    # ラッパーオブジェクトを作成
    wrapper = GitHubConnectionWrapper(
        duckdb_conn,
        str(prs_parquet_path),
        str(commits_parquet_path),
        str(repos_parquet_path),
    )

    yield wrapper
