# 技術スタック

各コンポーネントが使用している技術の一覧。

---

## モノレポ構成

| コンポーネント | 言語 | パッケージマネージャー |
|---|---|---|
| `egograph/pipelines/` | Python 3.12+ | uv (workspace) |
| `egograph/backend/` | Python 3.12+ | uv (workspace) |
| `frontend/` | Kotlin 2.2.21 | Gradle |

---

## Pipelines Service

| カテゴリ | 技術 |
|---|---|
| Web Framework | FastAPI |
| ジョブスケジューラ | APScheduler |
| ジョブ状態管理 | SQLite |
| 外部API通信 | Spotipy (Spotify), requests (GitHub) |
| データ変換 | pyarrow, DuckDB |
| ストレージ | boto3 → Cloudflare R2 |
| Lint/Format | Ruff |
| テスト | pytest, pytest-cov |

## Backend (Data API / MCP Server)

| カテゴリ | 技術 |
|---|---|
| Web Framework | FastAPI + Uvicorn |
| 分析エンジン | DuckDB `:memory:` + httpfs |
| 会話履歴 | SQLite (WAL) |
| HTTP Client | httpx |
| バリデーション | Pydantic |
| MCP | FastMCP / RMCP 互換クライアント想定 |
| ツール実行 | 自前 ToolExecutor |
| Lint/Format | Ruff |
| テスト | pytest, pytest-cov |

## Frontend (Mobile App)

| カテゴリ | 技術 | バージョン |
|---|---|---|
| 言語 | Kotlin | 2.2.21 |
| UI | Compose Multiplatform | 1.9.0 |
| ナビゲーション | Voyager | 1.1.0-beta03 |
| DI | Koin | 4.0.0 |
| HTTP Client | Ktor | 3.3.3 |
| プッシュ通知 | Firebase Cloud Messaging | - |
| ロギング | Kermit | - |
| 図レンダリング | WebView (Mermaid.js v11 CDN) | - |
| テスト | kotlin-test, Turbine, MockK, Ktor MockEngine | - |
| カバレッジ | Kover | - |
| Lint | Ktlint, Detekt | - |

## 関連リポジトリ

[EgoPulse](https://github.com/endo-ly/egopulse) — AI エージェントランタイム（Rust/Tokio）。独立リポジトリで開発。

## インフラ

| 要素 | 技術 |
|---|---|
| Object Storage | Cloudflare R2 (S3互換) |
| CI/CD | GitHub Actions |
| コンテナ | Dockerfile (Backend/Pipelines) |

---

## CI/CD

| ワークフロー | トリガー | 内容 |
|---|---|---|
| `ci-backend.yml` | `egograph/backend/**` | Backend テスト・Lint |
| `ci-pipelines.yml` | `egograph/pipelines/**` | Pipelines テスト・Lint |
| `ci-frontend.yml` | `frontend/**` | Frontend テスト・Lint |
| `ci-browser-extension.yml` | `browser-extension/**` | Extension ビルド |
| `deploy-backend.yml` | `main` push | Backend/Pipelines デプロイ |
| `release-frontend-kmp.yml` | タグ | Frontend リリース |

## テスト戦略

| レイヤー | Python | Frontend |
|---|---|---|
| Unit | pytest | kotlin-test |
| Integration | pytest (fixtures) | Turbine + MockK |
| E2E | pytest (live, 要認証) | Maestro |
| Lint/Format | Ruff | Ktlint + Detekt |
