# Backend Service

データアクセスと LLM エージェント機能を提供するサーバーサイドコンポーネント。

## Overview

Backend サービスは主に 2 つの目的を果たします：

1.  **Semantic Layer**: Cloudflare R2 上の compacted Parquet、またはそのローカル mirror を DuckDB でクエリする「ヘッドレス BI」レイヤーを提供します。
2.  **Agent Runtime**: ユーザーのクエリを処理し、ツールを実行する LLM エージェント（FastAPI）をホストします。

## Architecture

- **Runtime**: Python 3.12+ / FastAPI
- **Database**:
  - **DuckDB**: インメモリ（`:memory:`）で実行されるステートレス設計。`compacted/events` / `compacted/master` を読み取ります。
- **AI/LLM**:
  - OpenAI, Anthropic, OpenRouter をサポート。
  - データアクセスのための MCP ライクなツールインターフェースを実装。

### Key Directories

- `api/`: FastAPI のルート定義。
- `database/`: DuckDB 接続とクエリ実行ロジック。
- `tools/`: LLM エージェント用のツール定義。
- `llm/`: LLM プロバイダーとの統合。

## Setup & Usage

### Prerequisites

- Python 3.12+
- `uv` パッケージマネージャー

### Environment Setup

1.  依存関係の同期:
    ```bash
    uv sync
    ```
2.  `backend/.env` に設定（`.env.example`を参照）:
    - `R2_*` のクレデンシャルを設定（データアクセス用）。
    - `LOCAL_PARQUET_ROOT` を設定すると、compacted parquet のローカル mirror を優先利用します。
    - `LLM_*` のクレデンシャルを設定（チャット機能に必須）。
    - 本番では `USE_ENV_FILE=false` を指定し、systemd の `EnvironmentFile` からのみ読み込む。

### Running the Server

```bash
# 自動リロード付き開発モード
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

## Key Features & API

### System

- `GET /health`: DuckDB と compacted Parquet の読取り可否を確認します。

### Data Access

- `GET /v1/data/spotify/stats/top-tracks`: 指定された期間のトップトラックを取得します。
- `GET /v1/data/spotify/stats/listening`: 期間ごとの視聴統計を取得します。

### Chat (Agent)

- `POST /v1/chat`: 会話型インターフェース。
  - 現在は **Phase 1** (意思決定) を実装: `tool_calls` を返しますが、サーバーサイドでの完全なループ実行はまだ行いません。

## Testing

pytest を使用してテストを実行します:

```bash
# 全てのバックエンドテストを実行
uv run pytest backend/tests

# 特定のテストファイルを実行
uv run pytest backend/tests/test_api.py

# compacted parquet の local mirror を同期
uv run python backend/scripts/sync_compacted_parquet.py --root data/parquet
```
