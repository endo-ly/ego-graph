# Pipelines Service

スケジュール駆動で各種サービスからデータを定期収集する常駐 ETL/ELT サービス。

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) パッケージマネージャー

### Setup & Run

```bash
# 依存関係の同期
uv sync

# Pipelines Service 起動
uv run python -m egograph.pipelines.main serve
```

- **API Docs**: http://localhost:8001/docs
- **Health Check**: http://localhost:8001/health

環境変数は `egograph/pipelines/.env.example` を参照。

## Development

| 操作 | コマンド |
|------|----------|
| 単体テスト | `uv run pytest egograph/pipelines/tests/unit` |
| 結合テスト | `uv run pytest egograph/pipelines/tests/integration` |
| E2E テスト | `uv run pytest egograph/pipelines/tests/e2e` |
| CI 用テスト（全部 + カバレッジ） | `uv run pytest egograph/pipelines/tests/unit egograph/pipelines/tests/integration egograph/pipelines/tests/e2e --cov=pipelines` |
| Lint | `uv run ruff check egograph/pipelines/` |
| Format | `uv run ruff format egograph/pipelines/` |
| ワークフロー一覧 | `uv run python -m egograph.pipelines.main workflow list --json` |

## CLI リファレンス

Pipelines Service は HTTP API サーバーとして動作しつつ、`main.py` を直接実行することで CLI としても操作できる。
`serve` コマンド以外は SQLite DB に直接アクセスするため、サービスが停止していても動作する。

### ワークフロー操作

| コマンド | 説明 |
|----------|------|
| `workflow list [--json]` | 登録済みワークフロー一覧 |
| `workflow run <workflow_id> [--json]` | 指定ワークフローを手動実行（キューに積む） |
| `workflow enable <workflow_id> [--json]` | ワークフローのスケジュールを有効化 |
| `workflow disable <workflow_id> [--json]` | ワークフローのスケジュールを無効化 |

```bash
# ワークフロー一覧（デフォルト: 簡易表示）
uv run python -m pipelines.main workflow list

# ワークフロー一覧（JSON 形式）
uv run python -m pipelines.main workflow list --json

# Spotify 取り込みワークフローを手動実行
uv run python -m pipelines.main workflow run spotify_ingest_workflow --json

# 特定ワークフローのスケジュールを無効化
uv run python -m pipelines.main workflow disable github_ingest_workflow --json
```

### Run 操作

| コマンド | 説明 |
|----------|------|
| `run list [--json]` | 全 run 一覧（最新順） |
| `run show <run_id> [--json]` | 指定 run の詳細（ステータス + 全 step の状態） |
| `run log <run_id> <step_id>` | 指定 step のログ全文を出力 |
| `run retry <run_id> [--json]` | 失敗した run を再実行（新規 run としてキュー） |
| `run cancel <run_id> [--json]` | キュー待ちの run をキャンセル |

```bash
# 全 run 一覧を JSON で確認
uv run python -m pipelines.main run list --json

# 特定 run の詳細を確認（status, steps, error_message など）
uv run python -m pipelines.main run show 722e2f38-def8-4bba-9283-bfe07459935c --json

# 特定 step のログ全文を表示
uv run python -m pipelines.main run log 722e2f38-def8-4bba-9283-bfe07459935c run_spotify_ingest

# 失敗した run をリトライ
uv run python -m pipelines.main run retry 722e2f38-def8-4bba-9283-bfe07459935c --json

# キュー待ちの run をキャンセル
uv run python -m pipelines.main run cancel 722e2f38-def8-4bba-9283-bfe07459935c --json
```

### デバッグワークフロー

run の状態遷移: `queued` → `running` → `succeeded` / `failed` / `canceled`

**ログ取得時の注意点**: `run log` は step が実行され、log ファイルが生成された後にのみ利用可能。`queued` 状態の run に対して実行すると `WorkflowNotFoundError` になる。

```bash
# 1. ワークフローを手動実行
uv run python -m pipelines.main workflow run spotify_ingest_workflow --json
# → run_id が返る

# 2. run の状態を確認（running になるまで待つ）
uv run python -m pipelines.main run show <run_id> --json
# → "status": "running" または "succeeded" を確認

# 3. step のログを確認
uv run python -m pipelines.main run log <run_id> <step_id>
```

## REST API リファレンス

Pipelines Service はポート `8001`（デフォルト）で HTTP API を提供する。
全エンドポイントは API キー認証が必要（環境変数 `PIPELINES_API_KEY` で設定）。

### エンドポイント一覧

| Method | Path | 説明 |
|--------|------|------|
| `GET` | `/v1/health` | ヘルスチェック |
| `GET` | `/v1/workflows` | ワークフロー一覧 |
| `GET` | `/v1/workflows/{workflow_id}` | ワークフロー詳細 |
| `GET` | `/v1/workflows/{workflow_id}/runs` | 指定ワークフローの run 一覧 |
| `POST` | `/v1/workflows/{workflow_id}/runs` | ワークフロー手動実行 |
| `POST` | `/v1/workflows/{workflow_id}/enable` | ワークフロー有効化 |
| `POST` | `/v1/workflows/{workflow_id}/disable` | ワークフロー無効化 |
| `GET` | `/v1/runs` | 全 run 一覧 |
| `GET` | `/v1/runs/{run_id}` | run 詳細 |
| `GET` | `/v1/runs/{run_id}/steps/{step_id}/log` | step ログ全文 |
| `POST` | `/v1/runs/{run_id}/retry` | run リトライ |
| `POST` | `/v1/runs/{run_id}/cancel` | run キャンセル |

```bash
# API ドキュメント（Swagger UI）
http://localhost:8001/docs

# ヘルスチェック
curl http://localhost:8001/health

# ワークフロー一覧
curl -H "X-API-Key: $PIPELINES_API_KEY" http://localhost:8001/v1/workflows

# Spotify ワークフローを手動実行
curl -X POST -H "X-API-Key: $PIPELINES_API_KEY" \
  http://localhost:8001/v1/workflows/spotify_ingest_workflow/runs

# run 詳細取得
curl -H "X-API-Key: $PIPELINES_API_KEY" \
  http://localhost:8001/v1/runs/<run_id>
```

## Project Structure

```text
egograph/pipelines/
├── api/                # FastAPI ルート定義（health, workflows, runs, ingest）
├── domain/             # ドメインモデル（workflow, schedule, errors）
├── infrastructure/     # インフラストラクチャ層
│   ├── db/             # SQLite 接続・マイグレーション
│   ├── scheduling/     # APScheduler トリガー管理
│   ├── dispatching/    # キュー管理・run ディスパッチ
│   └── execution/      # Step 実行エンジン（inprocess / subprocess）
├── sources/            # データソース実装
│   ├── spotify/        # Spotify リスニング履歴
│   ├── github/         # GitHub アクティビティ
│   ├── browser_history/ # ブラウザ閲覧履歴
│   ├── google_activity/ # Google アクティビティ
│   └── local_mirror_sync/ # ローカルファイルミラー
├── workflows/          # ワークフロー定義レジストリ
├── tests/              # テスト（unit / integration / e2e / live）
├── main.py             # CLI エントリーポイント
├── app.py              # FastAPI アプリケーション
└── service.py          # サービス起動・スケジューラ管理
```

## See Also

> 詳細な設計・仕様は docs/ を参照。

| トピック | ドキュメント |
|----------|-------------|
| アーキテクチャ設計 | [docs/20.egograph/pipelines/architecture.md](../../docs/20.egograph/pipelines/architecture.md) |
| テスト戦略 | [docs/20.egograph/pipelines/testing-strategy.md](../../docs/20.egograph/pipelines/testing-strategy.md) |
| データソース一覧 | [docs/20.egograph/pipelines/README.md](../../docs/20.egograph/pipelines/README.md) |
| データ戦略 | [docs/10.architecture/data-strategy.md](../../docs/10.architecture/data-strategy.md) |
| デプロイ手順 | [docs/50.deploy/pipelines.md](../../docs/50.deploy/pipelines.md) |
