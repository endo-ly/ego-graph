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
├── api/                # FastAPI ルート定義（data, health, browser_history, github）
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

## See Also

> 詳細な設計・仕様は docs/ を参照。

| トピック | ドキュメント |
|----------|-------------|
| アーキテクチャ設計 | [docs/20.egograph/backend/architecture.md](../../docs/20.egograph/backend/architecture.md) |
| デプロイ手順 | [docs/50.deploy/backend.md](../../docs/50.deploy/backend.md) |
