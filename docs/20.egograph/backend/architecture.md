# Backend Architecture

個人データへのアクセスを提供するデータ提供サーバー。
REST API と MCP (Model Context Protocol) の2つのインターフェースを単一プロセスで提供する。

## 提供するもの

| インターフェース | 用途 | 対象 |
|---|---|---|
| REST API (`/v1/data/*`) | ダッシュボードやデータ可視化など直接データアクセス | Frontend, 外部ツール |
| MCP Server (`/mcp`) | AIエージェントがツール経由でデータにアクセス | EgoPulse, 外部エージェント |

## アーキテクチャ概要

DDD レイヤードアーキテクチャ。4層構造で依存関係は上位→下位に一方向。

```
Presentation → Application → Domain ← Infrastructure
     |              |           |           |
   API層      UseCase層    Domain層   Infrastructure層
```

- **API層**: UseCase層に依存。HTTPリクエストの受付とレスポンス生成
- **UseCase層**: Domain層に依存。ツールの管理・実行・オーケストレーション
- **Domain層**: 外部に依存しない。ツールの抽象定義とビジネスロジック
- **Infrastructure層**: Domain層のインターフェースを実装。DB接続・データ取得

## ディレクトリ構造

```
backend/
├── main.py                  # エントリーポイント（FastAPI + MCP）
├── config.py                # BackendConfig, R2Config
├── dependencies.py          # FastAPI 依存性注入
├── validators.py            # 入力バリデーション
├── mcp_server.py            # MCP Server 構築
│
├── api/                     # Presentation Layer
│   ├── {data_source}.py     #   データソース別エンドポイント
│   └── schemas/             #   Request/Response スキーマ
│
├── usecases/                # Application Layer
│   └── tools/
│       ├── registry.py      #   ToolRegistry
│       └── factory.py       #   DI 構築
│
├── domain/                  # Domain Layer
│   ├── models/tool.py       #   Tool, ToolBase（抽象定義）
│   └── tools/               #   データソース別ツール実装
│       └── {source}/
│
├── infrastructure/          # Infrastructure Layer
│   ├── database/            #   DuckDB 接続・クエリ・Parquetパス解決
│   ├── repositories/        #   データソース別 Repository
│   └── context/             #   AIエージェント向けコンテキスト（MCP instructions）
│
└── tests/                   # unit / integration / domain / performance
```

## データアクセス基盤

### DuckDB + Parquet アーキテクチャ

ステートレス設計。リクエストごとに `:memory:` モードで新規接続を作成し、R2（またはローカル）の Parquet を直接クエリする。

```
リクエスト → DuckDBConnection(:memory:) → LOAD httpfs → CREATE SECRET (R2認証)
           → read_parquet(s3://bucket/...) → 結果返却 → 接続クローズ
```

特徴:
- サーバー側に状態を保持しない（DB永続化なし）
- DuckDB の httpfs 拡張で R2 に直接アクセス
- ローカル Parquet が存在すればそちらを優先（`local_parquet_root` 設定時）

### Parquet パス解決

データは月次パーティション（`year=YYYY/month=MM/data.parquet`）で格納されている。

- `build_partition_paths()`: 指定期間の月次パーティションパスを構築
- `build_dataset_glob()`: データセット全体の glob パターンを構築

ローカル優先ロジック: `local_parquet_root` が設定されており、該当パスにファイルが存在すればローカルパスを使用。なければ R2 (s3://) パスを使用。

### データソース

| データソース | Parquet パス | 内容 |
|---|---|---|
| Spotify | `events/spotify/plays/` | 再生履歴 |
| Browser History | `events/browser_history/page_views/` | ページビュー |
| GitHub | `events/github/prs/`, `events/github/commits/`, `master/github/repos/` | PR・コミット・リポジトリ |
| YouTube | `events/youtube/watch_events/`, `master/youtube/videos/`, `master/youtube/channels/` | 視聴イベント・動画・チャンネル |

## REST API

### エンドポイント一覧

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/health` `/v1/health` | DuckDB + R2 接続確認 |
| GET | `/v1/data/spotify/stats/top-tracks` | トップトラック |
| GET | `/v1/data/spotify/stats/listening` | 再生統計（日/週/月） |
| GET | `/v1/data/browser-history/page-views` | ページビュー一覧 |
| GET | `/v1/data/browser-history/top-domains` | ドメインランキング |
| GET | `/v1/data/github/pull-requests` | PR イベント |
| GET | `/v1/data/github/commits` | コミットイベント |
| GET | `/v1/data/github/repositories` | リポジトリ一覧 |
| GET | `/v1/data/github/activity-stats` | アクティビティ統計 |
| GET | `/v1/data/github/repo-summary-stats` | リポジトリ別サマリー |
| GET | `/v1/data/youtube/watch-events` | 視聴イベント一覧 |
| GET | `/v1/data/youtube/stats/watching` | 視聴統計（日/週/月） |
| GET | `/v1/data/youtube/stats/top-videos` | トップ動画 |
| GET | `/v1/data/youtube/stats/top-channels` | トップチャンネル |

共通パラメータパターン:
- `start_date` / `end_date`（必須、ISO形式）: 期間フィルタ
- `limit`（任意、1〜100）: 取得件数
- データソース固有フィルタ（`owner`, `repo`, `state`, `browser`, `profile` 等）

## ツールシステム

### ToolBase 抽象クラス

全ツールの基底。`name`, `description`, `input_schema`, `execute()` を実装する。

```python
class ToolBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    @property
    @abstractmethod
    def description(self) -> str: ...
    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...
    @abstractmethod
    def execute(self, **params) -> Any: ...
    def to_schema(self) -> Tool: ...
```

### ツール実装の責務分離

- **Domain Tools** (`domain/tools/`): バリデーションとビジネスルール
- **Repository** (`infrastructure/repositories/`): データ取得（DuckDB + Parquet）

ツールはビジネスロジック（バリデーション）のみを担当し、データ取得は Repository に委譲。

```python
class GetTopTracksTool(ToolBase):
    def __init__(self, repository: SpotifyRepository):
        self.repository = repository

    def execute(self, start_date: str, end_date: str, limit: int):
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit)
        return self.repository.get_top_tracks(start, end, validated_limit)
```

### ToolRegistry

ツールの登録・管理・名前による実行。

- `register(tool)`: ツールを登録
- `get_tool(name)`: ツールを取得
- `get_all_schemas()`: 全ツールのスキーマを返す（MCP list_tools 用）
- `execute(tool_name, **params)`: ツールを実行

### Factory（DI 構築）

`build_tool_registry(r2_config)` で Repository → Tool → Registry の配線を一括構築。

```
R2Config → SpotifyRepository → GetTopTracksTool ─┐
         → BrowserHistoryRepository → ...        ├→ ToolRegistry
         → GitHubRepository → ...                ┘
         → DataQueryTool（直接 R2Config 使用）
```

### 登録ツール一覧

| ツール名 | 内容 | 対応データソース |
|---|---|---|
| `get_top_tracks` | 指定期間のトップトラック | Spotify |
| `get_listening_stats` | 再生統計（日/週/月） | Spotify |
| `get_page_views` | ページビュー一覧 | Browser History |
| `get_top_domains` | ドメインランキング | Browser History |
| `get_pull_requests` | PR イベント | GitHub |
| `get_commits` | コミットイベント | GitHub |
| `get_repositories` | リポジトリ一覧 | GitHub |
| `get_activity_stats` | アクティビティ統計 | GitHub |
| `get_repo_summary_stats` | リポジトリ別サマリー | GitHub |
| `get_youtube_watch_events` | 視聴イベント一覧 | YouTube |
| `get_youtube_watching_stats` | 視聴統計（日/週/月） | YouTube |
| `get_youtube_top_videos` | トップ動画 | YouTube |
| `get_youtube_top_channels` | トップチャンネル | YouTube |
| `data_query` | DuckDB 生SQL（SELECTのみ） | 全データ |

## MCP Server

FastMCP を使用し、ToolRegistry のツールを MCP プロトコルで公開する。

- **エンドポイント**: `http://<host>:<port>/mcp`（Streamable HTTP transport）
- **認証**: `BACKEND_API_KEY` 設定時、`X-API-Key` ヘッダーが必須
- **ハンドラ**:
  - `list_tools`: レジストリの全ツールスキーマを返す
  - `call_tool`: 指定ツールを実行し、JSON シリアライズした結果を `TextContent` で返す

EgoPulse 等の AIエージェントは MCP 経由でツールを呼び出し、個人データにアクセスする。

### egopulse 設定例

`mcp.json`

```json
{
  "mcpServers": {
    "egograph": {
      "transport": "streamable_http",
      "endpoint": "http://127.0.0.1:8000/mcp",
      "headers": {
        "x-api-key": "<your-backend-api-key>"
      },
      "request_timeout_secs": 120
    }
  }
}
```

`BACKEND_API_KEY` を設定していない場合は `headers` を省略（ローカル開発）。

## 認証・セキュリティ

### API Key 認証

`BACKEND_API_KEY` 環境変数が設定されている場合、`_ApiKeyAuthMiddleware` が全リクエストで `X-API-Key` ヘッダーを検証する。

- **対象**: REST API + MCP（共通）
- **除外パス**: `/health`, `/v1/health`, `/docs`, `/redoc`, `/openapi.json`
- **検証**: `secrets.compare_digest` でタイミングセーフ比較

### CORS

`CORS_ORIGINS` 環境変数（カンマ区切り）で許可オリジンを指定。ワイルドカード `*` は開発環境用。

### MCP Transport Security

`MCP_ALLOWED_HOSTS` で MCP の Host 許可リストを設定可能。テスト環境向けに `testserver` 等を許可し、本番では DNS rebinding 保護を適用。

## 設定管理

### BackendConfig

| 設定項目 | 環境変数 | デフォルト | 内容 |
|---|---|---|---|
| `host` | `BACKEND_HOST` | `127.0.0.1` | バインドホスト |
| `port` | `BACKEND_PORT` | `8000` | バインドポート |
| `reload` | `BACKEND_RELOAD` | `True` | ホットリロード |
| `api_key` | `BACKEND_API_KEY` | `None` | API Key（オプション） |
| `cors_origins` | `CORS_ORIGINS` | `*` | CORS 許可オリジン |
| `log_level` | `LOG_LEVEL` | `INFO` | ログレベル |
| `mcp_allowed_hosts` | `MCP_ALLOWED_HOSTS` | `[]` | MCP Host 許可リスト |

### R2Config

| 設定項目 | 環境変数 | 内容 |
|---|---|---|
| `endpoint_url` | `R2_ENDPOINT_URL` | R2 エンドポイント |
| `access_key_id` | `R2_ACCESS_KEY_ID` | アクセスキー |
| `secret_access_key` | `R2_SECRET_ACCESS_KEY` | シークレットキー |
| `bucket_name` | `R2_BUCKET_NAME` | バケット名 |
| `raw_path` | `R2_RAW_PATH` | raw データパス |
| `events_path` | `R2_EVENTS_PATH` | events データパス |
| `master_path` | `R2_MASTER_PATH` | master データパス |
| `local_parquet_root` | - | ローカル Parquet ルート |

### 依存性注入

`dependencies.py` で FastAPI の DI を構成:

- `get_config()`: BackendConfig を環境変数からロード（初回のみ、キャッシュ）
- `get_db_connection()`: DuckDB接続をコンテキストマネージャーとして提供（リクエストごと）

## エラーハンドリング

| エラー | HTTP ステータス | 内容 |
|---|---|---|
| `ValueError` (validation) | 400 | バリデーションエラー（日付範囲、limit 等） |
| `FileNotFoundError` | - | Parquet ファイル未存在（health では `data_available=False`） |
| `duckdb.IOException` | - | R2 接続エラー |
| 認証エラー | 401 | API Key 不正 |
| MCP ツール不明 | - | `ValueError("Unknown tool")` |
| MCP 実行エラー | - | `RuntimeError` でラップ |

エラーメッセージフォーマット: `invalid_<field>: <reason>`（例: `invalid_date_range: start_date must be on or before end_date`）

## テスト戦略

### テスト構造

```
tests/
├── conftest.py              # 共有フィクスチャ（モック設定、DuckDB、サンプルデータ）
├── unit/                    # ユニットテスト
│   ├── api/                 #   APIハンドラー
│   ├── database/            #   クエリ
│   ├── repositories/        #   Repository
│   ├── models/              #   ドメインモデル
│   ├── tools/               #   ツール実装
│   └── usecases/            #   UseCase
├── integration/             # インテグレーションテスト
│   ├── test_api_data.py     #   Spotify API E2E
│   ├── test_api_health.py   #   ヘルスチェック E2E
│   ├── test_browser_history_data_api.py
│   ├── test_github.py
│   ├── test_compacted_parquet_reads.py
│   └── test_mcp_endpoint.py #   MCP エンドポイント E2E
├── domain/                  # ドメインロジックテスト
├── performance/             # パフォーマンステスト
└── fixtures/                # テストデータ
```

### テストパターン

- **Unit Tests**: Repository をモックしてビジネスロジックをテスト
- **Integration Tests**: 実 DuckDB (`:memory:`) + サンプル Parquet で E2E 検証
- **Mock 境界**: `DuckDBConnection`, `SpotifyRepository`, `GitHubRepository`, `BrowserHistoryRepository`

### 共通フィクスチャ

- `mock_r2_config`: テスト用 R2 設定
- `mock_backend_config`: テスト用 Backend 設定（API Key 有り、CORS 制限付き）
- `duckdb_conn`: 実 DuckDB :memory: 接続
- `*_with_sample_data`: データソース別のサンプル Parquet データ
- `test_client`: FastAPI TestClient（依存性オーバーライド済み）

## 起動コマンド

```bash
# 開発モード（ホットリロード）
uv run uvicorn egograph.backend.main:create_app --factory --reload --host 127.0.0.1 --port 8000

# または直接実行
uv run python -m egograph.backend.main
```

- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **MCP Endpoint**: http://localhost:8000/mcp
