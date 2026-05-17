---
name: "pipelines-monitoring"
description: "Pipelines Service のAPI仕様書。ヘルスチェック、データ鮮度、成功率、キュー状況など、エージェントがAPI経由でパイプラインの監視・運用を行う。"
allowed-tools: "Bash, Read"
---

# Pipelines Monitoring API

Pipelines Service の全APIエンドポイント仕様。エージェントがAPI経由でパイプラインの監視・運用を行うためのリファレンス。

## 環境設定

```bash
export API_BASE="http://localhost:8001"    # Pipelines ServiceのURL
export PIPELINES_API_KEY="<your-api-key>"  # 認証キー（/v1/health以外必須）
```

## エンドポイント一覧

全エンドポイント（`/v1/health` 除く）に `X-API-Key` ヘッダーが必要。

| Method | Path | 説明 | 認証 |
|--------|------|------|------|
| `GET` | `/v1/health` | ヘルスチェック | 不要 |
| `GET` | `/v1/workflows` | ワークフロー一覧 | 必須 |
| `GET` | `/v1/workflows/{workflow_id}` | ワークフロー詳細 | 必須 |
| `GET` | `/v1/workflows/{workflow_id}/runs` | 指定workflowのrun一覧 | 必須 |
| `POST` | `/v1/workflows/{workflow_id}/runs` | 手動トリガー | 必須 |
| `POST` | `/v1/workflows/{workflow_id}/enable` | スケジュール有効化 | 必須 |
| `POST` | `/v1/workflows/{workflow_id}/disable` | スケジュール無効化 | 必須 |
| `GET` | `/v1/runs` | 全run一覧 | 必須 |
| `GET` | `/v1/runs/{run_id}` | run詳細（steps含む） | 必須 |
| `GET` | `/v1/runs/{run_id}/steps/{step_id}/log` | stepログ全文 | 必須 |
| `POST` | `/v1/runs/{run_id}/retry` | リトライ | 必須 |
| `POST` | `/v1/runs/{run_id}/cancel` | queued runをキャンセル | 必須 |

---

## エンドポイント詳細

### GET /v1/health

サービス死活確認。認証不要。

```bash
curl -s "${API_BASE}/v1/health"
```

**Response 200:**
```json
{"status": "ok"}
```

---

### GET /v1/workflows

登録済みワークフロー一覧。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows"
```

**Response 200:**
```json
[
  {
    "workflow_id": "spotify_ingest_workflow",
    "name": "Spotify Ingest",
    "description": "Spotify再生履歴の収集とcompact",
    "enabled": true,
    "steps": [
      {
        "step_id": "run_spotify_ingest",
        "step_name": "Spotify ingest",
        "executor_type": "inprocess",
        "timeout_seconds": 1800,
        "max_attempts": 1
      },
      {
        "step_id": "run_spotify_compact",
        "step_name": "Spotify compact",
        "executor_type": "inprocess",
        "timeout_seconds": 1800,
        "max_attempts": 1
      }
    ],
    "triggers": [
      {
        "trigger_type": "cron",
        "trigger_expr": "0 */4 * * *",
        "timezone": "Asia/Tokyo",
        "misfire_policy": "coalesce_latest"
      }
    ],
    "definition_version": 1,
    "concurrency_key": "spotify_ingest_workflow",
    "timeout_seconds": 3600
  }
]
```

---

### GET /v1/workflows/{workflow_id}

指定ワークフローの詳細。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/spotify_ingest_workflow"
```

**Response 200:** ワークフロー単体オブジェクト（上記配列の要素と同形式）

**Response 404:**
```json
{"detail": "workflow not found: xxx"}
```

---

### GET /v1/workflows/{workflow_id}/runs

指定ワークフローのrun一覧（新しい順）。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/spotify_ingest_workflow/runs"
```

**Response 200:**
```json
[
  {
    "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
    "workflow_id": "spotify_ingest_workflow",
    "trigger_type": "schedule",
    "queued_reason": "schedule_tick",
    "status": "succeeded",
    "scheduled_at": "2026-05-16T04:00:00",
    "queued_at": "2026-05-16T04:00:00",
    "started_at": "2026-05-16T04:00:01",
    "finished_at": "2026-05-16T04:02:15",
    "last_error_message": null,
    "requested_by": "system",
    "parent_run_id": null,
    "result_summary": {"tracks_count": 42}
  }
]
```

---

### POST /v1/workflows/{workflow_id}/runs

ワークフローを手動実行（キューに積む）。

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/spotify_ingest_workflow/runs"
```

**Response 201:**
```json
{
  "run_id": "new-uuid-here",
  "workflow_id": "spotify_ingest_workflow",
  "trigger_type": "manual",
  "queued_reason": "manual_request",
  "status": "queued",
  "scheduled_at": null,
  "queued_at": "2026-05-16T10:00:00",
  "started_at": null,
  "finished_at": null,
  "last_error_message": null,
  "requested_by": "api",
  "parent_run_id": null,
  "result_summary": null
}
```

**Response 400:** workflowが無効、存在しない等

---

### POST /v1/workflows/{workflow_id}/enable

ワークフローのスケジュールを有効化。

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/spotify_ingest_workflow/enable"
```

**Response 200:** ワークフロー詳細オブジェクト

---

### POST /v1/workflows/{workflow_id}/disable

ワークフローのスケジュールを無効化。

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/spotify_ingest_workflow/disable"
```

---

### GET /v1/runs

全run一覧（新しい順）。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs"
```

**Response 200:** WorkflowRunオブジェクトの配列（`/v1/workflows/{id}/runs`と同形式）

---

### GET /v1/runs/{run_id}

run詳細とstep一覧。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/722e2f38-def8-4bba-9283-bfe07459935c"
```

**Response 200:**
```json
{
  "run": {
    "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
    "workflow_id": "spotify_ingest_workflow",
    "trigger_type": "schedule",
    "queued_reason": "schedule_tick",
    "status": "succeeded",
    "scheduled_at": "2026-05-16T04:00:00",
    "queued_at": "2026-05-16T04:00:00",
    "started_at": "2026-05-16T04:00:01",
    "finished_at": "2026-05-16T04:02:15",
    "last_error_message": null,
    "requested_by": "system",
    "parent_run_id": null,
    "result_summary": {"tracks_count": 42}
  },
  "steps": [
    {
      "step_run_id": "step-uuid-1",
      "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
      "step_id": "run_spotify_ingest",
      "step_name": "Spotify ingest",
      "sequence_no": 1,
      "attempt_no": 1,
      "command": "pipelines.sources.spotify.pipeline:ingest",
      "status": "succeeded",
      "started_at": "2026-05-16T04:00:01",
      "finished_at": "2026-05-16T04:01:30",
      "exit_code": null,
      "stdout_tail": "Ingested 42 tracks",
      "stderr_tail": "",
      "log_path": "/var/log/pipelines/spotify/xxx.log",
      "result_summary": {"tracks_count": 42}
    },
    {
      "step_run_id": "step-uuid-2",
      "run_id": "722e2f38-def8-4bba-9283-bfe07459935c",
      "step_id": "run_spotify_compact",
      "step_name": "Spotify compact",
      "sequence_no": 2,
      "attempt_no": 1,
      "command": "pipelines.sources.spotify.pipeline:compact",
      "status": "succeeded",
      "started_at": "2026-05-16T04:01:30",
      "finished_at": "2026-05-16T04:02:15",
      "exit_code": null,
      "stdout_tail": "Compacted 3 files",
      "stderr_tail": "",
      "log_path": "/var/log/pipelines/spotify/xxx.log",
      "result_summary": null
    }
  ]
}
```

**Response 404:**
```json
{"detail": "run not found: xxx"}
```

---

### GET /v1/runs/{run_id}/steps/{step_id}/log

stepのログ全文（text/plain）。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/722e2f38-def8-4bba-9283-bfe07459935c/steps/run_spotify_ingest/log"
```

**Response 200:** ログ全文（text/plain）

**Response 404:**
```json
{"detail": "step log not found: xxx/yyy"}
```

---

### POST /v1/runs/{run_id}/retry

失敗したrunを再実行（新規runとしてキュー）。

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/722e2f38-def8-4bba-9283-bfe07459935c/retry"
```

**Response 201:** 新規runオブジェクト（`trigger_type: "retry"`, `parent_run_id` に元runのID）

**Response 400:** 対象runが存在しない等

---

### POST /v1/runs/{run_id}/cancel

queued状態のrunをキャンセル。

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/722e2f38-def8-4bba-9283-bfe07459935c/cancel"
```

**Response 200:** 更新後のrunオブジェクト（`status: "canceled"`）

**Response 400:** queued以外をcancelしようとした等

---

## レスポンススキーマ

### WorkflowRun

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `run_id` | string (UUID) | runの一意なID |
| `workflow_id` | string | ワークフローID |
| `trigger_type` | string | `schedule` / `manual` / `retry` / `event` / `reconcile` |
| `queued_reason` | string | `schedule_tick` / `manual_request` / `retry_request` / `startup_reconcile` / `event_enqueue` |
| `status` | string | `queued` / `running` / `succeeded` / `failed` / `canceled` |
| `scheduled_at` | string\|null | スケジュール時刻（ISO 8601） |
| `queued_at` | string | キュー投入時刻（ISO 8601） |
| `started_at` | string\|null | 実行開始時刻（ISO 8601） |
| `finished_at` | string\|null | 実行完了時刻（ISO 8601） |
| `last_error_message` | string\|null | エラーメッセージ |
| `requested_by` | string | 実行者（`system` / `api`） |
| `parent_run_id` | string\|null | リトライ元のrun_id |
| `result_summary` | object\|null | 実行結果の要約（データ件数等） |

### StepRun

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `step_run_id` | string (UUID) | step runの一意なID |
| `run_id` | string | 親runのID |
| `step_id` | string | step定義ID |
| `step_name` | string | step名 |
| `sequence_no` | int | 実行順序 |
| `attempt_no` | int | リトライ試行回数（1始まり） |
| `command` | string | 実行コマンド/関数参照 |
| `status` | string | `queued` / `running` / `succeeded` / `failed` / `skipped` |
| `started_at` | string\|null | 開始時刻 |
| `finished_at` | string\|null | 完了時刻 |
| `exit_code` | int\|null | 終了コード（subprocessのみ） |
| `stdout_tail` | string\|null | 標準出力末尾 |
| `stderr_tail` | string\|null | 標準エラー出力末尾 |
| `log_path` | string\|null | ログファイルパス |
| `result_summary` | object\|null | step実行結果の要約 |

---

## 監視レシピ

### 1. サービス死活確認

```bash
curl -sf "${API_BASE}/v1/health" && echo "OK" || echo "DOWN"
```

### 2. 全ワークフローのステータス一括確認

既存スクリプトを使用:
```bash
./.claude/skills/pipelines-debug/check-workflows.sh "$API_BASE" "$PIPELINES_API_KEY"
```

またはAPI直接実行:
```bash
# 各workflowの直近runを取得
for wf in spotify_ingest_workflow github_ingest_workflow \
          google_activity_ingest_workflow local_mirror_sync_workflow \
          browser_history_compact_workflow browser_history_compact_maintenance_workflow; do
  echo "=== $wf ==="
  curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
    "${API_BASE}/v1/workflows/${wf}/runs" | \
    python3 -c "
import sys, json
runs = json.load(sys.stdin)
if not runs:
    print('  NO_RUNS')
    sys.exit()
r = runs[0]
print(f'  status: {r[\"status\"]}')
print(f'  finished: {r.get(\"finished_at\", \"N/A\")}')
if r.get(\"last_error_message\"):
    print(f'  error: {r[\"last_error_message\"]}')
"
done
```

### 3. データ鮮度チェック（最終成功時刻）

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | \
  python3 -c "
import sys, json
from datetime import datetime, timezone

runs = json.load(sys.stdin)
# workflowごとに最新のsucceeded runを見つける
latest = {}
for r in runs:
    wf = r['workflow_id']
    if r['status'] == 'succeeded' and wf not in latest:
        latest[wf] = r

for wf, r in sorted(latest.items()):
    finished = r.get('finished_at', 'N/A')
    print(f'{wf}: last succeeded at {finished}')
"
```

### 4. キュー詰まり検知

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | \
  python3 -c "
import sys, json
runs = json.load(sys.stdin)
queued = [r for r in runs if r['status'] == 'queued']
if queued:
    print(f'WARNING: {len(queued)} run(s) stuck in queue')
    for r in queued:
        print(f'  - {r[\"workflow_id\"]} (queued at {r[\"queued_at\"]})')
else:
    print('Queue is clear')
"
```

### 5. 直近の失敗一覧

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | \
  python3 -c "
import sys, json
runs = json.load(sys.stdin)
failed = [r for r in runs if r['status'] == 'failed'][:10]
if not failed:
    print('No recent failures')
else:
    print(f'{len(failed)} recent failure(s):')
    for r in failed:
        print(f'  [{r[\"workflow_id\"]}] {r[\"run_id\"]}')
        print(f'    finished: {r.get(\"finished_at\", \"N/A\")}')
        print(f'    error: {r.get(\"last_error_message\", \"N/A\")}')
        print()
"
```

### 6. 成功率の算出（直近50run）

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | \
  python3 -c "
import sys, json
runs = json.load(sys.stdin)[:50]
total = len(runs)
succeeded = sum(1 for r in runs if r['status'] == 'succeeded')
failed = sum(1 for r in runs if r['status'] == 'failed')
print(f'Last {total} runs: {succeeded} succeeded, {failed} failed')
print(f'Success rate: {succeeded/total*100:.1f}%')
"
```

### 7. 失敗runのリトライ

```bash
RUN_ID="<run_id>"
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/${RUN_ID}/retry"
```

### 8. 実行中のrun確認

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | \
  python3 -c "
import sys, json
runs = json.load(sys.stdin)
running = [r for r in runs if r['status'] == 'running']
if running:
    for r in running:
        print(f'{r[\"workflow_id\"]} started at {r[\"started_at\"]}')
else:
    print('No running workflows')
"
```

---

## 登録済みワークフロー一覧

| workflow_id | トリガー | 説明 |
|-------------|---------|------|
| `spotify_ingest_workflow` | CRON 6回/日 | Spotify再生履歴の収集→compact |
| `github_ingest_workflow` | CRON 1回/日 | GitHubアクティビティの収集→compact |
| `google_activity_ingest_workflow` | CRON 1回/日 | Google MyActivity（YouTube視聴履歴）収集 |
| `local_mirror_sync_workflow` | INTERVAL 6時間 | R2→ローカルのParquet同期 |
| `browser_history_compact_workflow` | イベント駆動 | ブラウザ履歴のcompact（ingest後に自動トリガー） |
| `browser_history_compact_maintenance_workflow` | INTERVAL 6時間 | ブラウザ履歴の定期compactメンテナンス |

---

## エラーレスポンス

| ステータス | 意味 |
|-----------|------|
| `400` | リクエスト不正（無効なworkflow_id、queued以外へのcancel等） |
| `401` | APIキー未設定または不正 |
| `404` | リソース未存在（workflow/run/log not found） |

---

## ガードレール

- APIキーをログ・出力に含めない
- 本番環境での手動トリガーは慎重に
- リトライは原因確認後に実行
- `/v1/health` は認証不要。それ以外は全て `X-API-Key` 必須
