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

環境変数の一覧は `egograph/backend/.env.example` を参照。Backend は `.env` を自動読み込みしないため、シェル・IDE・systemd・デプロイ基盤からプロセス環境へ設定する。

## Configuration modes

ローカル開発では `BACKEND_ENV=development`（デフォルト）を使用する。API key なしでも起動でき、`CORS_ORIGINS=*` を許可する。

本番では `BACKEND_ENV=production` を設定する。起動時に `BACKEND_API_KEY` と R2 設定の存在を検証する。ブラウザからのクロスオリジンアクセスが不要な場合は `CORS_ORIGINS` を未設定または空にでき、FEを別オリジンから接続する場合は空要素やワイルドカードを含まないオリジンを指定する。不足時は app を起動しない（HTTP 応答は返らない）。

`/health` と `/v1/health` は readiness endpoint であり、依存サービスが利用可能なら HTTP 200（データ未投入も含む）、起動後の DuckDB・R2 障害なら HTTP 503 を返す。本番設定の不足は起動時に検出されるため、503ではなくプロセス起動失敗として扱う。

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
| REST | `GET /v1/data/google-health/daily-metrics` | 日次Projectionをmetric単位で取得 |
| MCP | `get_google_health_daily_metrics` | RESTと同じ日次metric |
| REST | `GET /v1/data/google-health/timeseries` | sample / intervalの統計・bucket・特徴的な変化 |
| MCP | `get_google_health_timeseries` | RESTと同じ時系列結果 |
| REST | `GET /v1/data/google-health/sessions` | sleep / exercise session一覧 |
| MCP | `get_google_health_sessions` | RESTと同じsession一覧 |
| REST | `GET /v1/data/google-health/records/{record_id}` | DataPoint完全情報 |
| MCP | `get_google_health_record` | RESTと同じrecord detail |

`start_date`と`end_date`は`TIMEZONE`のローカル日付として両端を含む。
日次指標の`date`はローカル日付として保存済みのため変換せず、欠損値は`null`として返す。
timeseriesの`resolution`は`auto`（既定）、`raw`、`5m`、`15m`、`30m`、`1h`を指定できる。
`heart-rate-variability`のような複数metric型では`metric`を必須とし、異なるmetricを混在させない。
`auto`は期間に応じて内部bucket幅を調整し、最大80点程度へ収める。
`raw`の返却上限は1,000行で、超過時はエラーを返す。絶対時刻を提供する場合は、他のデータソースと同様にUTC保存値を`TIMEZONE`へ変換して返す。

## Parquet データソースの選択

期間指定のクエリでは、対象期間のcompact ParquetがLocal mirrorにすべて存在する場合だけLocalを使用する。1つでも欠けている場合は、クエリ内の全partitionをR2から読み込み、LocalとR2を混在させない。

期間を持たない全件検索とdataset存在判定はR2のglobを使用する。Local mirrorは期間指定クエリの読み取りを補助するものであり、全件検索の完全な分析正本ではない。manifestやgenerationによる完全性管理は別途導入する。

## See Also

> 詳細な設計・仕様は docs/ を参照。

| トピック | ドキュメント |
|----------|-------------|
| アーキテクチャ設計 | [docs/architecture/backend.md](../../docs/architecture/backend.md) |
| デプロイ手順 | [docs/deploy/backend.md](../../docs/deploy/backend.md) |
