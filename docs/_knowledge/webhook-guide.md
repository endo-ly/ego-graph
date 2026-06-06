# Webhook & Push Notification ガイド

このドキュメントは Webhook の基礎概念と EgoGraph でのプッシュ通知仕組み、セキュリティについて説明します。

---

## パート1: Webhook とは

Webhook（ウェブフック）は「イベント通知を HTTP 経由で送信する仕組み」です。「逆ポーリング」とも呼ばれ、サーバーからクライアントへの能動的な通知を実現します。

### ポーリング vs Webhook

```
┌─────────────────────────────────────────────────────────────────────┐
│ 【ポーリング方式（従来）】                                            │
│                                                                     │
│  クライアント                    サーバー                             │
│    │                              │                                  │
│    │ 「何か新しいことある？」        │                                  │
│    ├────────────────────────────→│                                  │
│    │                              │ 「ないよ」                        │
│    │←─────────────────────────────│                                  │
│    │     （数秒後）                                                  │
│    │                              │                                  │
│    │ 「何か新しいことある？」        │                                  │
│    ├────────────────────────────→│                                  │
│    │                              │ 「ないよ」                        │
│    │←─────────────────────────────│                                  │
│                                                                     │
│  ※ 無駄な通信が多く、リアルタイム性に欠ける                               │
├─────────────────────────────────────────────────────────────────────┤
│ 【Webhook 方式】                                                      │
│                                                                     │
│  サービスA                      サービスB                            │
│    │                              │                                  │
│    │ イベント発生！                  │                                  │
│    │                              │                                  │
│    │ 「通知をおく！」                  │                                  │
│    ├────────────────────────────→│  POST /webhook                   │
│    │     Body: {"event": "..."}  │                                  │
│    │                              │  処理実行                         │
│    │                              │                                  │
│  ※ イベント発生時に即座に通知                                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 一般的な Webhook フロー

1. **Webhook URL 登録**: 受信側が Webhook URL を通知元に登録
2. **イベント発生**: 通知元でイベント発生
3. **HTTP POST 送信**: 通知元が Webhook URL へ POST リクエスト
4. **処理実行**: 受信側がリクエストを処理
5. **レスポンス返却**: 受信側が `2xx` ステータスを返す

---

## パート2: EgoGraph での使用

### 使用目的

- **タスク完了通知**: tmux セッション内のエージェント処理完了をプッシュ通知
- **イベント配信**: 任意のイベントをモバイルアプリに通知

### エンドポイント

```
POST /v1/push/webhook
```

### 認証

`X-Webhook-Secret` ヘッダーを使用したシークレット認証：

```bash
curl -X POST http://gateway:8001/v1/push/webhook \
  -H "X-Webhook-Secret: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "task_completed",
    "session_id": "agent-0001",
    "title": "完了",
    "body": "タスクが完了しました"
  }'
```

### リクエスト形式

| フィールド | 型 | 必須 | 説明 |
|----------|------|------|------|
| `type` | string | ✓ | イベントタイプ（例: `task_completed`, `chat_completed`） |
| `session_id` | string | ✓ | セッションID（例: `agent-0001`） |
| `title` | string | ✓ | 通知タイトル（1-100文字） |
| `body` | string | ✓ | 通知本文（1-500文字） |

### レスポンス形式

成功時（200 OK）：

```json
{
  "success_count": 1,
  "failure_count": 0,
  "invalid_tokens": []
}
```

### Webhookペイロードのフィールド

| フィールド | タイプ | 必須 | 説明 | 例 |
|-----------|--------|------|------|-----|
| `type` | string | ✓ | イベントタイプ | `task_completed`, `error`, `info` |
| `session_id` | string | ✓ | セッションID | `agent-0001`, `backend-worker` |
| `title` | string | ✓ | 通知タイトル（1-100文字） | `タスク完了` |
| `body` | string | ✓ | 通知本文（1-500文字） | `処理が完了しました` |

---

## パート3: 実装ユースケース

### ケース1: Claude Code セッション完了通知

Claude Code の Stop Hook から Webhook を送信：

```python
# /root/.claude/hooks/send-webhook-on-stop.py
import httpx
import os

async def send_webhook():
    await httpx.post(
        "http://localhost:8001/v1/push/webhook",
        headers={"X-Webhook-Secret": os.getenv("GATEWAY_WEBHOOK_SECRET")},
        json={
            "type": "claude_session_stopped",
            "session_id": "claude-code",
            "title": "Claude Code 完了",
            "body": "セッションが終了しました"
        }
    )
```

`~/.claude/settings.json` に設定：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /root/.claude/hooks/send-webhook-on-stop.py"
          }
        ]
      }
    ]
  }
}
```

### ケース2: ラッパースクリプト

エージェント完了後に通知を送るラッパー：

```bash
#!/bin/bash
# agent-run スクリプト

SESSION_NAME="agent-$(date +%Y%m%d-%H%M%S)"

# tmux セッションでエージェント起動
tmux new-session -d -s "$SESSION_NAME" "$@"

# セッション終了待機
while tmux has-session -t "$SESSION_NAME" 2>/dev/null; do
    sleep 1
done

# 完了通知
python -m gateway.cli \
  --secret "$GATEWAY_WEBHOOK_SECRET" \
  --session "$SESSION_NAME" \
  --title "エージェント完了" \
  --body "タスクが完了しました"
```

### ケース3: 専用通知コマンド

```python
# gateway/cli.py
import asyncio
import httpx

async def send_webhook(
    webhook_url: str,
    webhook_secret: str,
    event_type: str,
    session_id: str,
    title: str,
    body: str,
) -> None:
    payload = {
        "type": event_type,
        "session_id": session_id,
        "title": title,
        "body": body,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            webhook_url,
            json=payload,
            headers={
                "X-Webhook-Secret": webhook_secret,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        response.raise_for_status()
```

使用例：

```bash
python -m gateway.cli \
  --secret "$GATEWAY_WEBHOOK_SECRET" \
  --session "agent-0001" \
  --title "バッチ完了" \
  --body "データ処理が完了しました"
```

---

## パート4: セキュリティ

### 実施済みセキュリティ対策

| 対策 | 状態 | 評価 |
|-----|------|------|
| Webhook Secret 認証 | ✅ 実装済み | ⭐⭐⭐⭐⭐ |
| Timing Attack 対策 | ✅ `secrets.compare_digest()` | ⭐⭐⭐⭐⭐ |
| Pydantic 入力検証 | ✅ 実装済み | ⭐⭐⭐⭐⭐ |

### Webhook セキュリティリスクと対策

| リスク | 対策 | 実装状況 |
|--------|------|---------|
| 認証なし | シークレット認証 | ✅ 実装済み |
| 弱いシークレット | 32バイト以上のランダム文字列 | ✅ ドキュメント化済み |
| Timing Attack | `secrets.compare_digest()` | ✅ 実装済み |
| リプレイ攻撃 | タイムスタンプ検証 | ⚠️ 未実装 |
| DoS 攻撃 | レート制限 | ⚠️ 未実装 |
| ヘッダーインジェクション | 入力値検証 | ✅ 実装済み |

### Timing Attack 対策

シークレット比較には必ず `secrets.compare_digest()` を使用します。

```python
# gateway/dependencies.py
import secrets

if not secrets.compare_digest(webhook_secret, expected_secret):
    raise HTTPException(status_code=401, detail="Invalid webhook secret")
```

**なぜ `==` ではダメなのか？**

`==` 演算子は先頭から1文字ずつ比較するため、処理時間の差からシークレットが推測される可能性があります（Timing Attack）。`compare_digest()` は常に一定時間で比較します。

### 🟡 優先度中: リプレイ攻撃対策

**現状**: Webhook でタイムスタンプ検証なし
**リスク**: 同一リクエストの再送により二重処理

**推奨対策**: タイムスタンプ検証の追加

```python
class WebhookPayload(BaseModel):
    timestamp: int  # Unix タイムスタンプ追加
    type: str
    session_id: str
    title: str
    body: str

# 検証（許容差5分）
if abs(time.time() - payload.timestamp) > 300:
    raise HTTPException(status_code=400, detail="Expired timestamp")
```

### 🟡 優先度中: レート制限

**推奨対策**: slowapi 等を使用したレート制限

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/v1/push/webhook")
@limiter.limit("10/minute")  # 1分間に10回
async def send_webhook(...):
    ...
```

### セキュリティ評価サマリー

```
認証・認可         ████████████████████░░  90%  ⭐⭐⭐⭐⭐
入力バリデーション   ████████████████████░░  90%  ⭐⭐⭐⭐⭐
リプレイ攻撃対策    ████░░░░░░░░░░░░░░░░░  20%  ⭐⭐
DoS 対策          ████░░░░░░░░░░░░░░░░░  20%  ⭐⭐

Webhook全体       ██████████████████░░░  80%  ⭐⭐⭐⭐
```

### 推奨本番構成

```
┌─────────────────────────────────────────────────────────────┐
│                    インターネット                            │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTPS (443)
                          ↓
┌─────────────────────────────────────────────────────────────┐
│              [リバースプロキシ]                              │
│  • Nginx / Caddy / Traefik                                  │
│  • TLS 終端処理                                               │
│  • レート制限                                                │
│  • IP フィルタリング                                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTP (8080)
                          ↓  (内部ネットワーク - 平文で可)
┌─────────────────────────────────────────────────────────────┐
│                   Gateway (:8001)                           │
│  • Webhook 認証                                             │
│  • FCM 送信                                                 │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                   Firebase FCM                              │
└─────────────────────────────────────────────────────────────┘
```

---

## パート5: 環境設定

### 環境変数設定

`.env` で設定する項目：

| 環境変数 | 必須 | デフォルト | 説明 |
|---------|------|----------|------|
| `GATEWAY_WEBHOOK_SECRET` | ✓ | - | Webhook シークレット（32バイト以上推奨） |
| `GCM_PROJECT_ID` | - | - | Firebase プロジェクト ID |
| `FCM_CREDENTIALS_PATH` | - | - | Firebase サービスアカウントキーのパス |

### シークレット生成

```bash
# 32バイト以上のランダム文字列を生成
openssl rand -base64 32
```

---

## 前提条件

1. **Gateway**: 起動済み（tmuxセッション: `egograph-gateway`）
2. **Androidアプリ**: EgoGraphアプリをインストール済み
3. **FCM設定**: `gateway/.env` に `FCM_PROJECT_ID` が設定済み
4. **Webhook Secret**: `gateway/.env` に `GATEWAY_WEBHOOK_SECRET` が設定済み

---

## 手順1: FCMトークンの取得

Androidアプリは起動時に自動的にFCMトークンを取得・登録しますが、**トークンはLogcatに出力されます**。

### エミュレータでトークンを取得

```bash
# 1. Androidアプリを起動
# 2. LogcatでFCMトークンを確認
adb logcat | grep -E "FcmTokenManager"

# 出力例:
# FcmTokenManager: Registering FCM token: AAAA...
# FcmTokenManager: FCM token registered successfully
```

**※ 完全なトークンを表示するには:**

一時的にデバッグログを追加します：

```kotlin
// FcmService.kt の onCreate() メソッド内
FirebaseMessaging.getInstance().token
    .addOnSuccessListener { token ->
        if (!token.isNullOrBlank()) {
            // デバッグ用: トークン全体をLogcatに出力
            Log.d("FcmService", "FCM Token (DEBUG): $token")

            getTokenManager()?.registerToken(
                token = token,
                deviceName = android.os.Build.MODEL,
            )
        }
    }
```

再ビルド後、Logcatで完全なトークンを確認します：

```bash
adb logcat | grep "FCM Token (DEBUG)"
```

### 実機でトークンを取得

```bash
# 1. 実機をUSB接続
# 2. デバイスIDを確認
adb devices

# 3. Logcatを確認
adb -s <デバイスID> logcat | grep -E "FcmTokenManager"
```

---

## 手順2: デバイストークンの登録

Androidアプリはトークンを自動登録しますが、手動で登録する場合：

### 方法1: curlで登録（推奨）

```bash
# Gateway API Keyとデバイストークンを準備
GATEWAY_API_KEY="your_gateway_api_key_from_.env"
DEVICE_TOKEN="fcm_token_from_logcat"

# トークンを登録
curl -X PUT http://localhost:8001/v1/push/token \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d "{
    \"device_token\": \"$DEVICE_TOKEN\",
    \"platform\": \"android\",
    \"device_name\": \"Pixel 6 Emulator\"
  }"
```

**レスポンス:**
```json
{
  "id": 1,
  "user_id": "default_user",
  "device_token": "AAAA...",
  "platform": "android",
  "device_name": "Pixel 6 Emulator",
  "enabled": true,
  "last_seen_at": "2026-02-25T14:00:00",
  "created_at": "2026-02-25T14:00:00"
}
```

### 方法2: Androidアプリで自動登録

アプリの設定画面で以下を設定します：
1. **Gateway API URL**: `http://<YOUR_IP>:8001`
2. **Gateway API Key**: `.env` の `GATEWAY_API_KEY`

設定後、アプリ起動時に自動登録されます。

---

## 手順3: Webhookで通知を送信

### 基本的なWebhook送信

```bash
# Webhook Secretを準備
WEBHOOK_SECRET="your_webhook_secret_from_.env"

# 通知を送信
curl -X POST http://localhost:8001/v1/push/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -d '{
    "type": "task_completed",
    "session_id": "agent-0001",
    "title": "タスク完了",
    "body": "エージェントがタスクを完了しました"
  }'
```

**レスポンス:**
```json
{
  "success_count": 1,
  "failure_count": 0,
  "invalid_tokens": []
}
```

### 通知フロー

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    EgoGraph Webhook 通知フロー                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [外部サービス]         [Gateway]                  [Firebase]            │
│  (Agent等)           (Webhook受信+FCM送信)        (FCMサービス)          │
│       │                      │                            │             │
│       │ ① イベント発生         │                            │             │
│       │                      │                            │             │
│       │ ② POST /v1/push/webhook                       │             │
│       ├─────────────────────→│                            │             │
│       │   X-Webhook-Secret   │                            │             │
│       │                      │                            │             │
│       │                  ③ 認証検証                       │             │
│       │                  ④ ペイロード検証                   │             │
│       │                  ⑤ FCMトークン取得                │             │
│       │                      │                            │             │
│       │                  ⑥ FCM送信                      │             │
│       │                      ├────────────────────────────→│             │
│       │                      │                            │             │
│       │                      │                        ⑦ プッシュ通知     │
│       │                      │                            ├───→ [ユーザー端末]
│       │                      │                            │             │
│       │  ⑧ レスポンス         │                            │             │
│       │←─────────────────────│                            │             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## トラブルシューティング

### 通知が届かない

1. **Gatewayのログを確認**
   ```bash
   tmux capture-pane -p -t egograph-gateway | grep -E "webhook|FCM"
   ```

2. **デバイスが登録されているか確認**
   ```bash
   # Gatewayのデータベースを確認
   cd /root/workspace/ego-graph/wt1/gateway
   uv run python -c "
   import sqlite3
   conn = sqlite3.connect('gateway.db')
   result = conn.execute('SELECT * FROM push_devices').fetchall()
   for row in result:
       print(row)
   "
   ```

3. **FCM初期化を確認**
   ```bash
   tmux capture-pane -p -t egograph-gateway | grep "Firebase"
   ```

   正常に初期化されている場合：
   ```text
   Firebase Admin SDK initialized with project: your-project-id
   ```

   未設定の場合：
   ```text
   FCM project ID not configured. Push notifications disabled
   ```

### success_count: 0, failure_count: 0

**原因:** デバイストークンが登録されていません

**解決策:** 手順2でトークンを登録してください。

### 401 Unauthorized

**原因:** Webhook Secretが間違っています

**解決策:** `gateway/.env` の `GATEWAY_WEBHOOK_SECRET` を確認してください。

### Gatewayが固まる

**原因:** 古いバージョンのデッドロックバグ（既に修正済み）

**解決策:** Gatewayを再起動してください
```bash
tmux kill-session -t egograph-gateway
tmux new-session -d -s egograph-gateway 'cd /root/workspace/ego-graph/wt1 && uv run python -m gateway.main'
```

---

## APIエンドポイント一覧

### POST /v1/push/webhook

Webhookでプッシュ通知を送信します。

**Headers:**
- `X-Webhook-Secret`: Webhookシークレット（32バイト以上）

**Request Body:**
```json
{
  "type": "task_completed",
  "session_id": "agent-0001",
  "title": "完了",
  "body": "タスク完了"
}
```

**Response:** `200 OK`
```json
{
  "success_count": 1,
  "failure_count": 0,
  "invalid_tokens": []
}
```

### PUT /v1/push/token

FCMデバイストークンを登録します。

**Headers:**
- `X-API-Key`: Gateway API Key

**Request Body:**
```json
{
  "device_token": "AAAA...",
  "platform": "android",
  "device_name": "My Device"
}
```

**Response:** `200 OK`
```json
{
  "id": 1,
  "user_id": "default_user",
  "device_token": "AAAA...",
  "platform": "android",
  "device_name": "My Device",
  "enabled": true,
  "last_seen_at": "2026-02-25T14:00:00",
  "created_at": "2026-02-25T14:00:00"
}
```

---

## 関連ファイル

- `gateway/api/push.py` - Webhook エンドポイント実装
- `gateway/services/fcm_service.py` - FCM サービス
- `gateway/domain/models.py` - データモデル定義
- `gateway/dependencies.py` - 認証処理

## 参考資料

- [Firebase Cloud Messaging](https://firebase.google.com/docs/cloud-messaging)
- [OWASP Webhook Security Guidelines](https://github.com/OWASP/GitHub-Security-Whitepaper)
- [Webhook Best Practices](https://sendgrid.com/blog/webhooks-vs-api-the-difference/)
