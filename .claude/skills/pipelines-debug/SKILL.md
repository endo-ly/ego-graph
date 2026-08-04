---
name: "pipelines-debug"
description: "Pipelines Service のデバッグワークフロー。API経由でワークフロー状態確認、失敗原因の特定、stepログの取得、手動リトライを行う。"
allowed-tools: "Bash, Read"
---

# Pipelines Debug

Pipelines Service のワークフロー状態確認・失敗調査・デバッグを行うスキル。全操作を API 経由で実行する。

## ワークフロー

### 0. 環境変数セット

```bash
export API_BASE="http://localhost:8001"
export PIPELINES_API_KEY="<your-api-key>"
```

### 1. ヘルスチェック

```bash
curl -s http://localhost:8001/v1/health
```

### 2. 全ワークフローのステータス確認

```bash
./.claude/skills/pipelines-debug/check-workflows.sh "$API_BASE" "$PIPELINES_API_KEY"
```

### 3. 失敗ワークフローの run ID を特定

```bash
# 特定ワークフローの直近 run 一覧
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/workflows/local_mirror_sync_workflow/runs" | jq '.[0]'

# 全 run 一覧（新しい順）
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs" | jq '.[] | {run_id, status, workflow_id, started_at}'
```

### 4. run の詳細を確認（step ごとのステータス・エラー）

```bash
RUN_ID="<run_id>"
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/${RUN_ID}" | jq .
# レスポンス: {"run": {...}, "steps": [...]}
# steps[].status と steps[].last_error_message を確認
```

### 5. 失敗 step のログを取得

```bash
RUN_ID="<run_id>"
STEP_ID="<step_id>"
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/${RUN_ID}/steps/${STEP_ID}/log"
```

### 6. 手動リトライ

```bash
curl -s -X POST -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/runs/${RUN_ID}/retry" | jq .
```

### 7. 指定 dataset の再コンパクト

まず dataset catalog で正式な `dataset_id` を確認し、対象 partition を明示して
manual compaction run を作成する。`workflow_id` は指定しない。

```bash
curl -s -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "${API_BASE}/v1/datasets" | jq .

curl -s -X POST \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"targets":[{"dataset_id":"github.commits","year":2026,"month":7},{"dataset_id":"github.pull_requests","year":2026,"month":7}]}' \
  "${API_BASE}/v1/compaction/runs" | jq .
```

レスポンスの `run_id` を使い、通常の run 詳細・step log・retry APIで実行を追跡する。
対象は月次 `APPEND_DEDUPE` datasetで、1つのrunには同じproviderのdatasetだけを指定する。

## API エンドポイント一覧

`PIPELINES_API_KEY` が設定されている環境では、`/v1/health` を除く全エンドポイントに
`X-API-Key` ヘッダーが必要。`PIPELINES_API_KEY` を設定しないローカル開発環境では、
認証なしでアクセスできる。

| Method | Path | 説明 |
|--------|------|------|
| `GET` | `/v1/health` | ヘルスチェック |
| `GET` | `/v1/datasets` | dataset catalog 一覧 |
| `POST` | `/v1/compaction/runs` | 指定dataset partitionのmanual compact run作成 |
| `GET` | `/v1/workflows` | ワークフロー一覧 |
| `GET` | `/v1/workflows/{workflow_id}` | ワークフロー詳細 |
| `GET` | `/v1/workflows/{workflow_id}/runs` | ワークフローの run 一覧 |
| `POST` | `/v1/workflows/{workflow_id}/runs` | 手動トリガー |
| `POST` | `/v1/workflows/{workflow_id}/enable` | スケジュール有効化 |
| `POST` | `/v1/workflows/{workflow_id}/disable` | スケジュール無効化 |
| `GET` | `/v1/runs` | 全 run 一覧 |
| `GET` | `/v1/runs/{run_id}` | run 詳細（steps 含む） |
| `GET` | `/v1/runs/{run_id}/steps/{step_id}/log` | step ログ（text/plain） |
| `POST` | `/v1/runs/{run_id}/retry` | リトライ |
| `POST` | `/v1/runs/{run_id}/cancel` | キュー済み run をキャンセル |

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `API_BASE` | Pipelines API のベース URL | `http://localhost:8001` |
| `PIPELINES_API_KEY` | API 認証キー（必須） | - |

## ガードレール

- API キーやシークレットをレスポンスやログに含めない
- リトライは原因究明後に行う
- 本番環境への操作は慎重に
