# 技術スタック

モノレポ構成における各コンポーネントの技術選定とその理由。

---

## モノレポ構成

| コンポーネント | 言語/FW     | パッケージマネージャー | 主要ライブラリ                        |
| -------------- | ----------- | ---------------------- | ------------------------------------- |
| **egograph/pipelines/** | Python 3.13   | uv     | FastAPI, APScheduler, SQLite, Spotipy, requests, DuckDB, boto3, pyarrow |
| **egograph/backend/**   | Python 3.13   | uv     | FastAPI, Uvicorn, DuckDB |
| **frontend/**           | Kotlin 2.2.21 | Gradle | Compose Multiplatform, Voyager, Koin, Ktor, FCM |

- **Python Workspace**: uv で pipelines, backend を一元管理
- **Frontend**: Kotlin Multiplatform (Gradle)

---

## 1. Data Storage

### DuckDB (OLAP 分析エンジン)

- **用途**: SQL 分析、集計、台帳管理
- **Extension**:
  - `parquet`: Parquet ファイルに対する高速クエリ
  - `httpfs`: Cloudflare R2 (S3互換) からの直接読取
- **実行モード**: `:memory:` (Backend でステートレス実行)
- **理由**: 列指向処理による高速集計、ファイルベースで運用が簡単

### Qdrant Cloud (ベクトル検索)

- **用途**: 意味検索、RAG のインデックス
- **Free Tier**: 1GB メモリ（約10万ベクトル）
- **理由**: マネージドサービスで運用不要、Backend のメモリ負荷を削減

### Cloudflare R2 (Object Storage)

- **用途**: 正本（Parquet/Raw JSON）の永続化
- **特徴**: S3 互換、egress 無料
- **構造**:
  - `events/`: 時系列データ（年月パーティショニング）
  - `master/`: マスターデータ
  - `raw/`: API レスポンス（監査用）
  - `state/`: 増分取り込みカーソル

---

## 2. Pipelines Service（データ収集・ジョブ管理）

- **Language**: Python 3.13
- **実行環境**: 常駐 `egograph-pipelines.service`
- **ジョブ管理**: APScheduler + SQLite + Dispatcher/Executor
- **主要ライブラリ**:
  - `fastapi`: 管理 API / Browser History ingest API
  - `apscheduler`: 定期 trigger
  - `spotipy`: Spotify API クライアント
  - `requests`: HTTP クライアント（GitHub API 用）
  - `pyarrow`: Parquet ファイル作成
  - `boto3`: R2 アップロード
  - `duckdb`: データ変換・検証
- **特性**: Idempotent（冪等性）、Stateful（R2 カーソル + SQLite 実行管理）

---

## 3. Backend（Agent API Server）

- **Framework**: FastAPI (Python 3.13)
- **Web Server**: Uvicorn (ASGI)
- **主要ライブラリ**:
  - `duckdb`: データアクセス
  - `httpx`: 外部 API 呼び出し
  - LLM プロバイダー SDK（OpenAI, Anthropic, OpenRouter）
- **Agent Framework**: LangChain / LlamaIndex（検討中）
- **LLM**:
  - Agent Reasoning: OpenAI GPT-4o / DeepSeek v3
  - Embedding: `cl-nagoya/ruri-v3-310m`（ローカル実行）
- **実行環境**: VPS/GCP VM（常駐サーバー）
- **特性**: ステートレス（DuckDB `:memory:` で初期化）

---

## 4. Frontend（モバイル/Web アプリ）

- **Framework**: Kotlin Multiplatform + Compose Multiplatform
- **Language**: Kotlin 2.2.21
- **Mobile Runtime**: Native Android
- **UI System**: Material3 (Compose)
- **Navigation**: Voyager 1.1.0-beta03
- **State Management**: StateFlow + Channel (MVVM パターン)
- **DI**: Koin 4.0.0
- **HTTP Client**: Ktor 3.3.3
- **Terminal UI**: xterm.js (WebView), xterm-addon-fit
- **Push Notification**: Firebase Cloud Messaging (FCM)
- **音声入力**: Android SpeechRecognizer
- **Logging**: Kermit
- **テスト**: kotlin-test, Turbine, MockK, Ktor MockEngine
- **実行環境**: モバイル（Android）

---

## 5. CI/CD

### GitHub Actions

| ワークフロー             | トリガー      | 用途                    |
| ------------------------ | ------------- | ----------------------- |
| `ci-backend.yml`         | `backend/**`  | Backend テスト・Lint    |
| `ci-pipelines.yml`       | `pipelines/**` | Pipelines テスト・Lint  |
| `ci-frontend.yml`        | `frontend/**` | Frontend テスト (JUnit) |
| `deploy-backend.yml`     | `main` push   | backend/pipelines デプロイ |

### Pipelines 定期実行

Spotify / GitHub / Google Activity / local mirror sync の定期実行は
GitHub Actions ではなく、`egograph/pipelines` の APScheduler が担う。

### テストツール

- **Python**: pytest, pytest-cov, Ruff (Lint/Format)
- **Frontend**: Kotest, Ktlint, Detekt

---

## 6. Deployment Infrastructure

### 開発環境

- **Python**: uv で依存関係管理（`uv sync`）
- **Frontend**: Gradle で依存関係管理（`./gradlew build`）

### 本番環境（想定）

- **Server**: VPS (Hetzner / Sakura) or GCP VM
- **Storage**:
  - Cloudflare R2: 正本（Parquet/Raw JSON）
  - Local SSD: DuckDB キャッシュ
- **Monitoring**: (未実装)
- **Deployment**: (未実装、将来的に Docker Compose 等)

---

## なぜこの技術スタックか？

### DuckDB + Qdrant のハイブリッド構成

1. **Separation of Concerns**: 分析（集計）と探索（意味検索）を分離
2. **Performance**: DuckDB の列指向処理 + Qdrant の高速ベクトル検索
3. **Simplicity**: ファイルベースで大規模 DWH 不要、個人運用に最適
4. **Cost Effective**: VPS + マネージドサービス（Qdrant Free Tier）で低コスト

### モノレポ + uv workspace

1. **コンポーネント分離**: 各層（pipelines/backend/frontend）が独立した責任範囲
2. **依存関係の透明性**: workspace 依存で Python パッケージの共通基盤を明示
3. **開発効率**: `uv sync` 一発で全 Python パッケージをセットアップ
4. **CI/CD の最適化**: コンポーネント別テストで高速フィードバック

### Mobile First (KMP)

1. **Native Performance**: ネイティブAndroidアプリとしての高速な動作
2. **Type Safety**: Kotlinによる堅牢な型システムと、Backend (Pydantic) との連携
3. **Future Proof**: iOS版も同じコードベース（Compose Multiplatform）で展開可能
