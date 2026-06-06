# Pipelines Service Architecture

データ収集・ETL/ELT パイプラインを実行する常駐サービスのアーキテクチャ詳細。

## 概要

Pipelines Service は、スケジュール駆動またはイベント駆動でデータ収集ワークフローを実行する常駐サービスである。

主な責務:
- **Schedule Trigger**: CRON / INTERVAL で定期実行
- **Run Dispatch**: キュー内の run を順次処理
- **Step Execution**: inprocess / subprocess でステップを実行
- **State Management**: SQLite で run/step/lock を永続化

---

## アーキテクチャ全体像

```mermaid
flowchart TB
    subgraph External
        A[Chrome Extension]
        B[GitHub API]
        C[Spotify API]
        D[Google Takeout]
    end

    subgraph "Pipelines Service"
        subgraph "Trigger Layer"
            S[APScheduler<br/>CRON/INTERVAL]
            E[Event API<br/>POST /v1/ingest/*]
        end

        subgraph "Queue Layer"
            Q[(SQLite workflow_runs)]
        end

        subgraph "Dispatch Layer"
            DR[RunDispatcher<br/>poll & dispatch]
            L[LockManager<br/>concurrency control]
        end

        subgraph "Execution Layer"
            X1[InProcessExecutor]
            X2[SubprocessExecutor]
        end

        subgraph "Source Layer"
            GH[github/]
            SP[spotify/]
            BH[browser_history/]
            GA[google_activity/]
            LM[local_mirror_sync/]
        end
    end

    subgraph Storage
        R2[(Cloudflare R2 - raw/events/state)]
    end

    S -->|enqueue| Q
    E -->|enqueue| Q
    DR -->|poll| Q
    DR --> L
    DR --> X1
    DR --> X2
    X1 --> GH
    X1 --> SP
    X1 --> BH
    X1 --> GA
    X1 --> LM
    GH --> R2
    SP --> R2
    BH --> R2
    GA --> R2
    LM --> R2
```

---

## コンポーネント詳細

### 1. Trigger Layer

#### 1.1 Scheduler (APScheduler)

```mermaid
flowchart LR
    subgraph "ScheduleTriggerApp"
        R[Registry<br/>workflow definitions]
        D[(SQLite schedules)]
        A[APScheduler<br/>BackgroundScheduler]
    end

    R -->|sync_jobs| A
    A -->|tick| E[enqueue_run]
    E --> D
```

**責務**: CRON / INTERVAL トリガーで `workflow_runs` へ run を enqueue

**実装**: APScheduler `BackgroundScheduler`

**Misfire Policy**:
- `COALESCE_LATEST`: 複数ミスファイアを1つにまとめる
- `SKIP_MISFIRE`: ミスファイアをスキップ

**Startup Reconcile**: サービス起動時に未実行のスケジュールを検出して enqueue

#### 1.2 Event API

- **Endpoint**: `POST /v1/ingest/browser-history`
- **用途**: 外部イベント（Browser Extension 等）からのリアルタイム取り込み
- **処理**: データ受信 → 検証 → Transform → enqueue compact workflow

---

### 2. Queue Layer

#### 2.1 SQLite Schema

```mermaid
flowchart TB
    subgraph workflow_definitions
        WD[workflow_id PK<br/>name<br/>description<br/>enabled<br/>definition_version<br/>created_at<br/>updated_at]
    end
    subgraph workflow_runs
        WR[run_id PK<br/>workflow_id FK<br/>trigger_type<br/>queued_reason<br/>status<br/>scheduled_at<br/>queued_at<br/>started_at<br/>finished_at<br/>last_error_message<br/>requested_by<br/>parent_run_id<br/>result_summary]
    end
    subgraph step_runs
        SR[step_run_id PK<br/>run_id FK<br/>step_id<br/>step_name<br/>sequence_no<br/>attempt_no<br/>command<br/>status<br/>started_at<br/>finished_at<br/>exit_code<br/>stdout_tail<br/>stderr_tail<br/>log_path<br/>result_summary]
    end
    subgraph workflow_locks
        WL[lock_key PK<br/>run_id<br/>lease_owner<br/>acquired_at<br/>heartbeat_at<br/>lease_expires_at]
    end

    WD -->|1:N| WR
    WR -->|1:N| SR
    WR -->|1:1| WL
```

---

### 3. Dispatch Layer

#### 3.1 RunDispatcher

```mermaid
sequenceDiagram
    participant Q as Queue (SQLite)
    participant D as RunDispatcher
    participant L as LockManager
    participant X as Executor
    participant R as Repository

    D->>Q: lease_next_queued_run()
    Q-->>D: WorkflowRun
    D->>L: acquire(lock_key)
    L-->>D: Lease
    loop Heartbeat
        D->>L: heartbeat(lease)
    end
    loop Steps
        D->>X: execute(step)
        X-->>D: StepResult
        D->>R: update_step_result()
    end
    D->>L: release(lease)
    D->>R: update_run_result(SUCCEEDED/FAILED)
```

**責務**: queued run を poll して workflow step を順次実行

**主要機能**:
- `dispatch_once()`: キューから1件取得して実行
- `run_forever()`: 停止要求まで poll を継続
- Heartbeat: 実行中の lock を定期更新

#### 3.2 LockManager

**責務**: workflow 単位の排他制御

**機能**:
- `acquire()`: lock 取得（失敗時は `WorkflowLockUnavailableError`）
- `heartbeat()`: lock 更新
- `release()`: lock 解放
- `cleanup_stale_locks()`: 古い lock のクリーンアップ

**Lock のライフサイクル**:
1. run 開始時に `acquire`
2. 実行中に `heartbeat` を定期的に送信
3. run 終了時に `release`

---

### 4. Execution Layer

#### 4.1 Executor Types

| Type | 用途 | 特徴 |
|---|---|---|
| **InProcessExecutor** | Python callable 実行 | 同一プロセス内で関数呼び出し |
| **SubprocessExecutor** | CLI コマンド実行 | 分離プロセスで実行、タイムアウト制御可能 |

#### 4.2 Step Definition

```python
@dataclass(frozen=True)
class StepDefinition:
    step_id: str                    # ステップ識別子
    step_name: str                  # 表示名
    executor_type: StepExecutorType  # inprocess / subprocess
    command: tuple[str, ...]        # subprocess の場合のコマンド
    callable_ref: str | None        # inprocess の場合の関数参照
    timeout_seconds: int = 1800    # タイムアウト
    max_attempts: int = 1            # 最大試行回数
    retry_delay_seconds: float = 0.0  # 再試行間隔
```

#### 4.3 Execution Flow

```mermaid
stateDiagram-v2
    [*] --> QUEUED: enqueue
    QUEUED --> RUNNING: dispatch
    RUNNING --> SUCCEEDED: all steps passed
    RUNNING --> FAILED: step failed (after retries)
    RUNNING --> CANCELED: cancel request
    SUCCEEDED --> [*]
    FAILED --> [*]
    CANCELED --> [*]
```

---

### 5. Source Layer

各データソースのパイプライン実装。

#### 5.1 共通パターン

```mermaid
flowchart LR
    C[Collector] --> T[Transform]
    T --> S[Storage]
    S --> R2[(R2)]
```

| コンポーネント | 責務 |
|---|---|
| Collector | 外部 API からデータ取得 |
| Transform | 正規化・加工・Parquet 変換 |
| Storage | R2 へのアップロード |

#### 5.2 ディレクトリ構成

```
egograph/pipelines/sources/
├── browser_history/
│   ├── collector.py
│   ├── transform.py
│   ├── storage.py
│   ├── pipeline.py       # ingest / compact エントリーポイント
│   └── schema.py
├── github/
│   ├── collector.py
│   ├── transform.py
│   ├── storage.py
│   └── pipeline.py
├── spotify/
│   ├── collector.py
│   ├── transform.py
│   ├── storage.py
│   └── pipeline.py
└── common/
    ├── compaction.py
    ├── config.py
    └── utils.py
```

---

## Workflow 定義

### Workflow Definition

```python
@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str                      # ワークフロー識別子
    name: str                              # 表示名
    description: str                       # 説明
    steps: tuple[StepDefinition, ...]      # ステップ定義
    triggers: tuple[TriggerSpec, ...]      # トリガー定義
    enabled: bool = True                   # 有効フラグ
    definition_version: int = 1            # バージョン
    concurrency_key: str | None = None     # 排他制御キー
    timeout_seconds: int = 3600            # 全体タイムアウト
    misfire_policy: MisfirePolicy = COALESCE_LATEST
```

### Trigger Types

| Type | 記法 | 例 |
|---|---|---|
| **CRON** | 5フィールド cron | `0 15 * * *` (毎日 15:00 UTC) |
| **INTERVAL** | 数値+単位 | `6h` (6時間ごと) |

### 現在の Workflows

| Workflow | Schedule | Steps |
|---|---|---|
| `spotify_ingest_workflow` | 6回/日 (0,4,8,12,16,22 JST) | ingest → compact |
| `github_ingest_workflow` | 1回/日 (00:00 JST) | ingest → compact |
| `google_activity_ingest_workflow` | 1回/日 (23:00 JST) | ingest |
| `local_mirror_sync_workflow` | 6時間ごと | sync |
| `browser_history_compact_workflow` | イベント駆動 | compact |
| `browser_history_compact_maintenance_workflow` | 6時間ごと | compact maintenance |

---

## Run State Machine

### WorkflowRun Status

```mermaid
stateDiagram-v2
    [*] --> QUEUED: enqueue
    QUEUED --> RUNNING: dispatch
    QUEUED --> CANCELED: cancel
    RUNNING --> SUCCEEDED: success
    RUNNING --> FAILED: failure
    RUNNING --> CANCELED: cancel
    SUCCEEDED --> [*]
    FAILED --> [*]
    CANCELED --> [*]
```

### StepRun Status

```mermaid
stateDiagram-v2
    [*] --> QUEUED: create
    QUEUED --> RUNNING: start
    RUNNING --> SUCCEEDED: success
    RUNNING --> FAILED: failure (retryable)
    RUNNING --> SKIPPED: prev step failed
    FAILED --> RUNNING: retry
    SUCCEEDED --> [*]
    SKIPPED --> [*]
```

---

## エラーハンドリング

### エラー種別

| Error | 処理 |
|---|---|
| `WorkflowNotFoundError` | run を FAILED に設定 |
| `WorkflowLockUnavailableError` | run を requeue |
| `WorkflowDisabledError` | run を reject |
| Step timeout | FAILED として記録、再試行判定 |
| Step exception | FAILED として記録、再試行判定 |
| `AuthenticationError` | **即時** FAILED（リトライ対象外） |

### 再試行ロジック

```python
for attempt_no in range(1, step.max_attempts + 1):
    result = execute_step(step, attempt_no)
    if result.status == SUCCEEDED:
        return True
    if isinstance(exc, AuthenticationError):
        return False  # 認証エラーは即 fail-fast
    if attempt_no < step.max_attempts:
        sleep(step.retry_delay_seconds)
return False
```

### AuthenticationError (Fail-fast)

OAuth トークン失効など**回復不能な認証エラー**を通常の `SpotifyException` / `RuntimeError` と区別する。`AuthenticationError` 発生時は `step.max_attempts` に関わらず 1 回で即失敗する。

```python
# 例: SpotifyCollector で invalid_grant を変換
try:
    self.auth_manager.refresh_access_token(refresh_token)
except SpotifyOauthError as exc:
    if exc.error == "invalid_grant":
        raise AuthenticationError(
            "Spotify refresh token revoked or expired"
        ) from exc
    raise AuthenticationError(
        f"Spotify OAuth error: {exc.error or 'unknown'}"
    ) from exc
```

## 失敗通知 (Webhook)

Pipeline run が FAILED に遷移した際、Webhook で通知する。デフォルトは無効 (`PIPELINES_WEBHOOK_URL` 未設定)。

### 環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `PIPELINES_WEBHOOK_URL` | 未設定 (通知無効) | Webhook 送信先 URL |
| `PIPELINES_WEBHOOK_TYPE` | `generic` | `generic` (CloudEvents-inspired JSON) / `discord` (Embed) |

### Payload 形式 (Generic)

```json
{
  "source": "urn:egograph:pipelines",
  "type": "egograph.pipelines.workflow_failed",
  "time": "2026-06-05T14:00:02Z",
  "data": {
    "workflow_id": "spotify_ingest_workflow",
    "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
    "error_message": "AuthenticationError: Spotify refresh token revoked",
    "custom_message": "認証でエラーが発生しました。再認証スクリプトを実行してください: uv run python scripts/spotify_auth.py"
  }
}
```

### コンポーネント

- `domain/notification.py`: `NotificationEvent` / `NotificationData`（不変 dataclass）
- `infrastructure/notification/adapters.py`: `WebhookAdapter` (抽象) / `GenericAdapter` / `DiscordAdapter`
- `infrastructure/notification/service.py`: `NotificationService`（`custom_message` 補完と送信失敗の握りつぶし）

### 発火タイミング

1. step 失敗（`max_attempts` 消費後、または `AuthenticationError` 即時 skip）
2. 予期しない dispatcher 例外 (`_mark_run_failed_after_unexpected_exception` 経由）

Lock 競合 (`WorkflowLockUnavailableError` での requeue) や未知 workflow 設定エラーでは通知しない。

---

## 運用

### サービス起動・停止

```bash
# 起動
uv run python -m pipelines.main serve

# 停止 (SIGTERM で graceful shutdown)
```

### Startup 時の収束処理

1. **stale running runs**: 前回停止時に実行中だった run を FAILED に設定
2. **stale locks**: 古い lock を解放

### ログ

- **構造化ログ**: JSON 形式で `logs/` ディレクトリに出力
- **Step ログ**: 各 step の stdout/stderr を `logs/{workflow_id}/{run_id}/{step_id}.log` に保存

---

## API Endpoints

| Method | Path | 説明 |
|---|---|---|
| GET | `/v1/health` | ヘルスチェック |
| GET | `/v1/workflows` | ワークフロー一覧 |
| GET | `/v1/workflows/{id}` | ワークフロー詳細 |
| POST | `/v1/workflows/{id}/runs` | 手動実行 |
| POST | `/v1/workflows/{id}/enable` | 有効化 |
| POST | `/v1/workflows/{id}/disable` | 無効化 |
| GET | `/v1/runs` | run 一覧 |
| GET | `/v1/runs/{id}` | run 詳細 |
| POST | `/v1/runs/{id}/retry` | 再実行 |
| POST | `/v1/runs/{id}/cancel` | キャンセル |
| POST | `/v1/ingest/browser-history` | Browser History 受信 |

---

## 参考

- [Testing Strategy](./testing-strategy.md)
- [データ戦略](../../10.architecture/data-strategy.md)
