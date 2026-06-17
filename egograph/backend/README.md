# Backend Service

データアクセス API を提供する FastAPI サーバー。

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) パッケージマネージャー

### Setup & Run

```bash
# 依存関係の同期
uv sync

# 起動（自動リロード付き開発モード）
uv run uvicorn egograph.backend.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **MCP Endpoint**: http://localhost:8000/mcp

環境変数は `egograph/backend/.env.example` を参照。

## Development

| 操作 | コマンド |
|------|----------|
| テスト | `uv run pytest egograph/backend/tests` |
| カバレッジ付きテスト | `uv run pytest egograph/backend/tests --cov=backend` |
| Lint | `uv run ruff check egograph/backend/` |
| Format | `uv run ruff format egograph/backend/` |

## Project Structure

```text
egograph/backend/
├── api/                # FastAPI ルート定義（各データソース, health）
│   └── schemas/        # リクエスト/レスポンススキーマ
├── domain/             # ドメインモデル・ツール定義
│   ├── models/         # エンティティ・DTO
│   └── tools/          # LLM ツールインターフェース
├── usecases/           # ユースケース（アプリケーション層）
│   └── tools/          # ツールファクトリ
├── infrastructure/     # インフラストラクチャ層
│   ├── database/       # DuckDB 接続・クエリ実行
│   └── repositories/   # Repository 実装
├── tests/              # テスト
└── main.py             # エントリーポイント
```

## Google Health

| Interface | Identifier | Description |
|---|---|---|
| REST | `GET /v1/data/google-health/daily-summary` | 指定したローカル日付範囲の日次健康サマリ |
| MCP | `get_google_health_daily_summary` | RESTと同じ日次健康サマリ |

`start_date`と`end_date`は`TIMEZONE`のローカル日付として両端を含む。
日次指標の`date`はローカル日付として保存済みのため変換せず、欠損値は`null`として返す。
絶対時刻を提供する場合は、他のデータソースと同様にUTC保存値を`TIMEZONE`へ変換して返す。

## See Also

> 詳細な設計・仕様は docs/ を参照。

| トピック | ドキュメント |
|----------|-------------|
| アーキテクチャ設計 | [docs/architecture/backend.md](../../docs/architecture/backend.md) |
| デプロイ手順 | [docs/deploy/backend.md](../../docs/deploy/backend.md) |
