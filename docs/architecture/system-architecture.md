# システムアーキテクチャ

> 最終更新: 2026-04-05

## 1. システム概要

EgoGraphは、分散する個人データを統合し、AIエージェントを通じて自然言語で分析・対話できる基盤。**サーバーレス・ローカルファースト**を設計原則とする。

### 1.1 構成要素

| コンポーネント | 言語 | 責務 |
|---|---|---|
| **Pipelines Service** | Python 3.12+ | スケジュール駆動のデータ収集・ETL |
| **Backend (Data API / MCP Server)** | Python 3.12+ | データアクセスREST API + MCP Server |
| **Frontend (Mobile App)** | Kotlin Multiplatform | Android ネイティブチャットUI |
| **Browser Extension** | Chromium | ブラウザ履歴収集 |

### 1.2 モノレポ構成

```
egograph/
├── egograph/
│   ├── pipelines/          # Pipelines Service (uv workspace member)
│   └── backend/            # Backend API (uv workspace member)
├── frontend/
│   ├── shared/             # KMP shared module
│   └── androidApp/         # Android app entry point
├── browser-extension/
│   └── chromium-history/   # Chrome extension (browser history)
├── scripts/                # 運用スクリプト
├── .github/workflows/      # CI/CD
└── pyproject.toml          # Python workspace 設定
```

---

## 2. 全体アーキテクチャ

### 2.1 データ収集フロー（Write Path）

```mermaid
flowchart LR
    subgraph Sources["Data Sources"]
        SP[Spotify API]
        GH[GitHub API]
        GA[Google MyActivity]
        BH[Browser Extension]
    end

    subgraph Pipelines["Pipelines Service"]
        SCH["APScheduler<br/>CRON / INTERVAL"]
        Q[("SQLite Queue")]
        DISP[RunDispatcher]
        EXE["Step Executor<br/>InProcess / SubProcess"]
    end

    subgraph Storage["Cloudflare R2"]
        RAW["raw/ - JSON"]
        EVT["events/ - Parquet"]
        MST["master/ - Parquet"]
        ST["state/ - cursors"]
    end

    SP -->|collect| EXE
    GH -->|collect| EXE
    GA -->|collect| EXE
    BH -->|POST /v1/ingest/browser-history| Pipelines

    SCH -->|enqueue| Q
    DISP -->|poll| Q
    DISP -->|dispatch| EXE
    EXE -->|write| RAW
    EXE -->|write| EVT
    EXE -->|write| MST
    EXE -->|update| ST
```

### 2.2 分析・対話フロー（Read Path）

```mermaid
sequenceDiagram
    participant User
    participant Frontend as Android App
    participant Backend as Backend API
    participant LLM as LLM Provider
    participant Tool as ToolExecutor
    participant DuckDB as DuckDB :memory:
    participant SQLite as SQLite chat.db

    User->>Frontend: データを閲覧・操作
    Frontend->>Backend: GET /v1/data/*
    Backend->>Tool: execute query tool
    Tool->>DuckDB: SQL on Parquet
    DuckDB-->>Tool: query result
    Tool-->>Backend: result
    Backend-->>Frontend: JSON response

    Agent->>Backend: MCP call / REST request
    Backend->>Tool: execute tool
    Tool->>DuckDB: SQL on Parquet
    DuckDB-->>Tool: query result
    Tool-->>Backend: result
    Backend-->>Agent: tool result / JSON
```

### 2.3 EgoPulse（独立エージェント）

> EgoPulseは [endo-ly/egopulse](https://github.com/endo-ly/egopulse) に切り出された。EgoGraphのデータに直接アクセスせず、MCP/HTTP経由で連携する独立したエージェントランタイム。詳細は同リポジトリを参照。

---

## 3. コンポーネント詳細

### 3.1 Pipelines Service

**責務**: スケジュール駆動で外部APIからデータを収集し、R2に保存する常駐ETLサービス。

#### アーキテクチャ

```
Trigger Layer (APScheduler)
    ↓ enqueue
Queue Layer (SQLite: workflow_runs)
    ↓ poll
Dispatch Layer (RunDispatcher + LockManager)
    ↓ execute
Execution Layer (InProcessExecutor / SubprocessExecutor)
    ↓
Source Layer (spotify, github, google_activity, browser_history, local_mirror_sync)
    ↓
Storage (Cloudflare R2: raw/, events/, master/, state/)
```

#### 管理API

| Method | Path | 説明 |
|---|---|---|
| GET | `/v1/health` | ヘルスチェック |
| GET | `/v1/workflows` | ワークフロー一覧 |
| GET | `/v1/workflows/{id}` | ワークフロー詳細 |
| POST | `/v1/workflows/{id}/runs` | 手動実行 |
| POST | `/v1/workflows/{id}/enable` | 有効化 |
| POST | `/v1/workflows/{id}/disable` | 無効化 |
| GET | `/v1/runs` | 実行一覧 |
| GET | `/v1/runs/{id}` | 実行詳細 |
| POST | `/v1/runs/{id}/retry` | 再実行 |
| POST | `/v1/runs/{id}/cancel` | キャンセル |
| POST | `/v1/ingest/browser-history` | ブラウザ履歴受信（イベント駆動） |

#### ワークフロー定義

| Workflow | トリガー | ステップ |
|---|---|---|
| `spotify_ingest_workflow` | CRON 6回/日 | ingest → compact |
| `github_ingest_workflow` | CRON 1回/日 | ingest → compact |
| `google_activity_ingest_workflow` | CRON 1回/日 | ingest |
| `local_mirror_sync_workflow` | INTERVAL 6h | sync |
| `browser_history_compact_workflow` | イベント駆動 | compact |
| `browser_history_compact_maintenance_workflow` | INTERVAL 6h | compact maintenance |

#### データソース

| ソース | 種別 | 収集方法 |
|---|---|---|
| Spotify | 音楽再生履歴 | Spotipy API (OAuth) |
| GitHub | 開発活動ログ | GitHub REST API |
| Google Activity | YouTube視聴履歴 | Google MyActivity + Cookie認証 |
| Browser History | ブラウザ閲覧履歴 | Chrome Extension → POST API |
| Local Mirror Sync | R2→ローカル同期 | boto3 S3 sync |

#### 状態管理（SQLite）

- `workflow_definitions`: ワークフロー定義
- `workflow_schedules`: スケジュール（CRON/INTERVAL）
- `workflow_runs`: 実行履歴（QUEUED → RUNNING → SUCCEEDED/FAILED/CANCELED）
- `step_runs`: ステップ実行（attempt管理付き）
- `workflow_locks`: 排他制御（lease + heartbeat）

---

### 3.2 Backend (Data API / MCP Server)

**責務**: DuckDB経由のデータアクセスREST APIと、外部エージェント向けMCP Serverを提供する。

#### アーキテクチャ（レイヤード）

```
api/              ← プレゼンテーション層（FastAPIルーター、Pydanticスキーマ）
usecases/         ← アプリケーション層（ToolExecutor、ToolRegistry 構築）
infrastructure/   ← インフラ層（Repository実装、DuckDB接続、MCP server）
domain/           ← ドメイン層（モデル定義、ツール定義）
```

#### REST API

| Method | Path | 説明 |
|---|---|---|
| GET | `/health` | ヘルスチェック |
| GET | `/v1/data/spotify/stats/top-tracks` | Spotify トップトラック |
| GET | `/v1/data/spotify/stats/listening` | Spotify 聴取統計 |
| GET | `/v1/data/github/*` | GitHub データ |
| GET | `/v1/data/browser-history/*` | ブラウザ履歴データ |
| POST | `/mcp` | MCP Streamable HTTP endpoint |

#### ツールシステム

| カテゴリ | ツール名 | 説明 |
|---|---|---|
| Spotify | `get_top_tracks` | 期間内のトップトラック |
| Spotify | `get_listening_stats` | 聴取統計 |
| Browser History | `get_page_views` | 閲覧ページ検索 |
| Browser History | `get_top_domains` | 閲覧ドメイン上位 |
| GitHub | `get_pull_requests` | PR一覧 |
| GitHub | `get_commits` | コミット一覧 |
| GitHub | `get_repositories` | リポジトリ一覧 |
| GitHub | `get_activity_stats` | 活動統計 |
| GitHub | `get_repo_summary_stats` | リポジトリ要約統計 |

> **注**: YouTubeツールは2025-02-04より一時非推奨。

#### DuckDB（分析エンジン）

- **モード**: `:memory:`（ステートレス、リクエスト毎に新規接続）
- **拡張**: `httpfs`（R2からの直接Parquet読み込み）
- **認証**: CREATE SECRET（S3互換、ハッシュ化secret名）
- **ローカルミラー**: `data/parquet/compacted/` をR2より優先して読み込む

---

### 3.3 Frontend (Mobile App)

**責務**: EgoGraph のデータ可視化・設定を担う Android ネイティブ companion app。必要に応じて EgoPulse と連携する補助UIにもなりうる。

#### アーキテクチャ（MVVM）

```
Screen          ← Compose UI表示
  ↓
ScreenModel     ← ビジネスロジック（StateFlow + Channel）
  ↓
State / Effect  ← UI状態 / One-shotイベント
  ↓
Repository      ← データアクセス（Ktor HTTP）
  ↓
Network         ← Ktor Client (SSE/REST)
```

#### 機能モジュール

| 機能 | Screen | ScreenModel | 状態 |
|---|---|---|---|
| データ閲覧/対話UI | `ChatScreen` | `ChatScreenModel` | 既存実装を整理中 |
| サイドバー | `SidebarScreen` | (共有) | 実装済み |
| 設定 | `SettingsScreen` | `SettingsScreenModel` | 実装済み |
| システムプロンプト | `SystemPromptEditorScreen` | `SystemPromptEditorScreenModel` | 実装済み |
| ターミナル | - | - | EgoPulse 連携候補（WIP） |

#### ナビゲーション

```
MainActivity
  └── Voyager Navigator
        └── SidebarScreen (root)
              ├── Drawer: ThreadList + Footer
              └── Content: MainNavigationHost
                    ├── Chat → ChatScreen
                    ├── SystemPrompt → SystemPromptEditorScreen
                    └── Settings → SettingsScreen
```

スワイプジェスチャー対応の独自ナビゲーションコンテナ。

#### 通信

| 宛先 | 用途 | プロトコル |
|---|---|---|
| Backend API | データ取得、設定、可視化用メタデータ | HTTPS/REST |
| EgoPulse Gateway | FCMトークン登録 | HTTPS/REST |

#### プッシュ通知（FCM）

```
FCM Service (onMessageReceived)
  → NotificationChannelManager
  → NotificationDisplayer
  → 通知種別: task_completed
  → FcmTokenManager: トークン登録（指数バックオフ5回）
    → PUT {gateway}/v1/push/token
```

#### 技術スタック

| 要素 | 技術 | バージョン |
|---|---|---|
| Kotlin | 言語 | 2.2.21 |
| Compose Multiplatform | UI | 1.9.0 |
| Voyager | ナビゲーション | 1.1.0-beta03 |
| Koin | DI | 4.0.0 |
| Ktor | HTTPクライアント | 3.3.3 |
| Kermit | ロギング | - |
| WebView (Mermaid.js) | 図レンダリング | v11 CDN |

---

### 3.4 Browser Extension

**責務**: Chromiumブラウザの閲覧履歴を収集し、Pipelines Serviceに送信。

- **ディレクトリ**: `browser-extension/chromium-history/`
- **送信先**: `POST {pipelines}/v1/ingest/browser-history`
- **ビルド**: dist/ 配下に出力

---

## 4. データフロー

### 4.1 書き込み（Ingestion）

```
1. Trigger: APScheduler (CRON/INTERVAL) または Event API
2. Queue: SQLite に workflow_run を enqueue
3. Dispatch: RunDispatcher が poll → lease → execute
4. Collect: 各Sourceが外部APIからデータ取得
5. Transform: スキーママッピング、Parquet変換
6. Store: R2 に raw/ (JSON), events/ (Parquet), master/ (Parquet) を保存
7. State: R2 state/ にカーソル位置を更新
```

### 4.2 読み取り（Analytics / Tool Access）

```
1. Request: Frontend または外部エージェントが Backend に問い合わせる
2. Tool: ToolExecutor が該当ツールを実行
3. DuckDB: :memory: 接続で R2 Parquet を httpfs 経由でクエリ
   （ローカルミラーがあれば優先）
4. Response: JSON または MCP tool result を返す
5. Agent side: EgoPulse などの外部エージェントが必要に応じて応答生成や自律実行を行う
```

### 4.3 R2 ディレクトリ構造

```
s3://{bucket}/
├── events/              # 時系列データ
│   ├── spotify/plays/   # 再生履歴 (year={yyyy}/month={mm}/)
│   └── github/          # GitHub活動
├── master/              # マスターデータ
│   └── spotify/         # tracks/, artists/
├── raw/                 # APIレスポンス（監査用JSON）
└── state/               # 増分取り込みカーソル
```

> ストレージの責務分離・配置ルール・判断基準 → [data-strategy.md](./data-strategy.md)
> 技術選定の理由（ADR）→ [tech-stack.md](./tech-stack.md)

---

## 5. CI/CD

### 5.1 GitHub Actions ワークフロー

| ワークフロー | トリガー | 内容 |
|---|---|---|
| `ci-backend.yml` | `egograph/backend/**` | Backend テスト・Lint |
| `ci-pipelines.yml` | `egograph/pipelines/**` | Pipelines テスト・Lint |
| `ci-frontend.yml` | `frontend/**` | Frontend テスト・Lint |
| `ci-browser-extension.yml` | `browser-extension/**` | Extension ビルド |
| `deploy-backend.yml` | `main` push | Backend/Pipelines デプロイ |
| `release-frontend-kmp.yml` | タグ | Frontend リリース |

### 5.2 テストピラミッド

| レイヤー | Python | Frontend |
|---|---|---|
| Unit | pytest | kotlin-test |
| Integration | pytest (fixtures) | Turbine + MockK |
| E2E | pytest (live, 要認証) | Maestro |
| Lint | Ruff | Ktlint + Detekt |

---

## 6. セキュリティ

### 6.1 認証

| コンポーネント | 方式 |
|---|---|
| Pipelines API | API Key 検証 |
| Backend API | API Key 検証 |

### 6.2 データ保護

- APIキー・認証情報は環境変数で管理（`.env` はGit管理外）
- Backendのエラーレスポンスから機密情報を自動除去（`_redact_string`）
- DuckDBのSECRET名はSHA-256ハッシュで衝突回避
- CORS設定は環境変数から制御

---

## 7. 現状と制約

### 7.1 コンポーネント成熟度

| コンポーネント | 状態 | 備考 |
|---|---|---|
| Pipelines Service | 運用中 | 4データソース + ローカルミラー同期 |
| Backend | 運用中 | Data API + MCP Server |
| Frontend | 開発中 | データ可視化中心に拡張中。EgoPulse 連携は検討中 |
| Browser Extension | 保守中 | 履歴収集 → Pipelines API送信 |
| [EgoPulse](https://github.com/endo-ly/egopulse) | 運用中 | 独立リポジトリで開発中 |

### 7.2 未実装・制限事項

- **Qdrant（ベクトル検索）**: 設計段階。実装なし
- **YouTubeツール**: 2025-02-04より一時非推奨
- **Last.fm**: ジョブ停止中
- **Frontend ターミナル**: ディレクトリ構造のみ（WIP）
- **データ可視化**: MermaidDiagram（マークダウン図レンダリング）のみ実装済み
- **モニタリング**: 未実装

### 7.3 既知の技術的負債

- `data-strategy.md` に記載されているQdrant前提の表現は現状と不一致
- 会話履歴のベクトル化方式は未選定
- DockerデプロイはBackendのみ（Pipelines分離デプロイ未対応）
