# FCM Token Management - Production Design

## 本番環境での一般的な設計

### 現状の課題

- **開発環境**: Logcatでトークン確認（開発者のみ）
- **本番環境**: トークンが見えない、管理できない

---

## 一般的な設計パターン

### パターン1: 自動登録 + 管理画面（推奨）

**フロー:**
```text
1. アプリ起動 → FCMトークン取得
2. 自動でGatewayに登録
3. 管理画面でトークン一覧を確認
4. 通知テスト機能で動作確認
```

**実装:**
- Androidアプリ: 現在の自動登録を維持
- Gateway: 管理用APIエンドポイントを追加
- 管理画面: トークン一覧・削除・テスト通知機能

### パターン2: ダッシュボード + 監視

**フロー:**
```text
1. アプリで自動登録
2. 管理ダッシュボードで登録状況を可視化
3. 通知送信数・成功率をモニタリング
4. エラートークンを自動検出
```

**実装:**
- Grafana + Prometheus で監視
- GatewayのDBを直接参照

### パターン3: ユーザー管理画面

**フロー:**
```
1. ユーザーがWeb画面で自身のデバイスを管理
2. デバイス名を変更・削除
3. 通知設定をON/OFF
4. 通知履歴を確認
```

---

## 推奨実装：管理APIの追加

### Gatewayに管理用エンドポイントを追加

#### GET /v1/push/devices

登録済みデバイス一覧を取得

```bash
curl -X GET http://localhost:8001/v1/push/devices \
  -H "X-API-Key: $GATEWAY_API_KEY"
```

**レスポンス:**
```json
{
  "devices": [
    {
      "id": 1,
      "user_id": "default_user",
      "device_name": "Pixel 6",
      "platform": "android",
      "enabled": true,
      "last_seen_at": "2026-02-25T14:00:00",
      "created_at": "2026-02-25T10:00:00"
    }
  ],
  "total": 1
}
```

#### DELETE /v1/push/devices/:id

デバイスを削除

```bash
curl -X DELETE http://localhost:8001/v1/push/devices/1 \
  -H "X-API-Key: $GATEWAY_API_KEY"
```

#### POST /v1/push/test

テスト通知を送信

```bash
curl -X POST http://localhost:8001/v1/push/test \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $GATEWAY_API_KEY" \
  -d '{
    "title": "テスト通知",
    "body": "これはテストです"
  }'
```

---

## Android側の改善

### 1. トークン登録成功時のUI通知

```kotlin
// FcmTokenManager.kt
private fun registerTokenWithRetry(...) {
    while (attempt < MAX_RETRY_COUNT) {
        try {
            sendTokenToGateway(token, deviceName)
            currentToken = token
            Log.i(TAG, "FCM token registered successfully")

            // ユーザーに通知（初回登録時のみ）
            if (attempt == 0) {
                showTokenRegisteredNotification()
            }
            return
        } catch (e: IOException) {
            // リトライ処理
        }
    }
}

private fun showTokenRegisteredNotification() {
    // 通知チャンネルで「プッシュ通知が有効になりました」と表示
}
```

### 2. 設定画面でトークン状態を表示

```kotlin
// GatewaySettingsScreen.kt
@Composable
fun PushNotificationStatus() {
    val isRegistered = remember { mutableStateOf(false) }

    Column {
        Text("プッシュ通知: ${if (isRegistered.value) "有効" else "無効"}")

        if (!isRegistered.value) {
            Button(onClick = { /* トークン再取得 */ }) {
                Text("有効化する")
            }
        }
    }
}
```

---

## 本番環境での運用フロー

### 初期セットアップ

1. **アプリをインストール**
   - 初回起動時にFCMトークンを自動取得
   - Gatewayに自動登録
   - 通知で「プッシュ通知が有効になりました」を表示

2. **管理者が確認**
   - 管理APIで登録済みデバイスを確認
   - テスト通知を送信して動作確認

3. **監視**
   - 通知送信成功率をモニタリング
   - 失敗したトークンを自動検出

### 運用中の管理

**定期タスク:**
- 週1回: アクティブデバイス数を確認
- 月1回: 未使用デバイス（30日以上アクセスなし）を削除
- エラートークンが増えたら調査

**トラブルシューティング:**
- 通知が届かない: 管理画面でデバイスが有効か確認
- トークン無効エラー: アプリを再起動して再登録

---

## セキュリティ考慮事項

### FCMトークンの取り扱い

**FCMトークンは機密情報ではありませんが、以下の点に注意:**

- ✅ トークンをログに出力してもOK（開発時のみ）
- ❌ 本番環境のログに出力しない
- ✅ データベースに暗号化せず保存してOK
- ❌ ログファイルを外部に公開しない

**理由:**
- FCMトークンは公開情報で、誰でも取得可能
- ただし、トークンがあれば誰でも通知を送れる可能性がある
- そのため、Gateway API Keyで保護する必要がある

### アクセス制御

```python
# 管理APIはGateway API Keyで保護
async def list_devices(request: Request):
    await verify_gateway_request(request)  # X-API-Key チェック

    # 管理者のみアクセス可能にする場合
    # user_id = get_user_id_from_token(request)
    # if user_id != "admin":
    #     raise HTTPException(403, "Admin only")
```

---

## 他社事例

### Slack

- ユーザー設定画面で「モバイル通知」をON/OFF
- デバイス管理画面で登録済みデバイスを一覧表示
- 各デバイスからテスト通知を送信可能

### Discord

- ユーザー設定で通知設定を管理
- サーバーごとに通知設定を変更可能
- 通知履歴を確認可能

### GitHub

- Settings > Notifications で通知設定を管理
- デバイスは非公開（裏で自動登録）
- 通知が届かない場合のトラブルシューティングガイドあり

---

## 推奨アーキテクチャ

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Android    │────────→│  Gateway API │────────→│   FCM       │
│   App       │  Token  │              │  Push   │             │
└─────────────┘         └──────────────┘         └─────────────┘
                              ↑
                              │ Admin API
                              │
                       ┌──────┴──────┐
                       │ Admin Panel │
                       │ (Optional)  │
                       └─────────────┘
```

**フェーズ1（現在）:** 基本機能
- ✅ 自動トークン登録
- ✅ Webhookで通知送信

**フェーズ2（推奨）:** 管理機能
- 🔲 管理用APIエンドポイント
- 🔲 デバイス一覧確認
- 🔲 テスト通知機能

**フェーズ3（将来的）:** ユーザー管理
- 🔲 Web管理画面
- 🔲 ユーザー設定画面
- 🔲 通知履歴表示
