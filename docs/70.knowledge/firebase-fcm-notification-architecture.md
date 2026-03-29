# Firebase / FCM 通知アーキテクチャ

このドキュメントは、EgoGraph の通知機能における Firebase / FCM の役割と、実装上の責務分離を整理したものです。
Webhook の手順詳細は `docs/70.knowledge/webhook-guide.md` を参照してください。

## Firebase とは

Firebase は Google が提供する BaaS 群です。
本プロジェクトでは、そのうち **Firebase Cloud Messaging (FCM)** を通知配信経路として利用しています。

## なぜこのプロジェクトで FCM を使うか

- Android 端末へのプッシュ通知配信を標準経路で実現できる
- 端末トークンを使ったサーバー送信モデルに適合している
- Gateway 側で通知送信を一元化でき、Webhook イベントと接続しやすい

## セキュリティ境界（重要）

### Frontend 側

- ファイル: `frontend/androidApp/google-services.json`
- 用途: クライアント SDK 初期化、FCM トークン取得
- 注意: これは **Admin 権限キーではない**

### Gateway 側

- ファイル: `gateway/firebase-service-account.json`（既定）
- 環境変数: `FCM_CREDENTIALS_PATH`
- 用途: Firebase Admin SDK による通知送信
- 注意: これは **秘密鍵を含む機密情報**（Git 管理禁止）

結論:

- `google-services.json` とサービスアカウント JSON は別物
- フロントとバックに同じ鍵を置く設計は不可

## このリポジトリでの通知フロー

### 1) 端末トークン登録

1. Android アプリが FCM トークンを取得
2. `PUT /v1/push/token` へ登録（`X-API-Key` 必須）
3. Gateway が `push_devices` テーブルへ保存

関連実装:

- `frontend/androidApp/src/main/kotlin/dev/egograph/android/fcm/FcmService.kt`
- `frontend/androidApp/src/main/kotlin/dev/egograph/android/fcm/FcmTokenManager.kt`
- `gateway/api/push.py` (`register_token`)
- `gateway/infrastructure/repositories.py` (`PushTokenRepository.save_token`)

### 2) Webhook から通知送信

1. 外部システムが `POST /v1/push/webhook` を呼ぶ（`X-Webhook-Secret` 必須）
2. Gateway が有効トークンを取得
3. `FcmService` が Firebase Admin SDK で送信
4. 失敗トークンは無効化処理に回す

関連実装:

- `gateway/api/push.py` (`send_webhook`)
- `gateway/services/fcm_service.py`
- `gateway/domain/models.py`

## 必須/重要な環境変数

- `GATEWAY_API_KEY`: 端末トークン登録 API の認証
- `GATEWAY_WEBHOOK_SECRET`: Webhook API の認証
- `FCM_PROJECT_ID`: Firebase プロジェクト ID
- `FCM_CREDENTIALS_PATH`: サービスアカウント JSON パス（既定: `gateway/firebase-service-account.json`）
- `GATEWAY_HOST`, `GATEWAY_PORT`: Gateway バインド設定
- `GATEWAY_RELOAD`: 開発時のみ `true`（通常運用は `false`）

## よくある障害と切り分け

### `success_count=0, failure_count=0`

- 有効トークン未登録の可能性が高い
- `push_devices` の `enabled=TRUE` を確認

### `failure_count` がトークン数ぶん増える

- FCM 未初期化、または認証情報不備
- Gateway ログで以下を確認:
  - `FCM project ID not configured`
  - `Failed to initialize Firebase Admin SDK`

### Gateway が固まる / health timeout

- `GATEWAY_RELOAD=true` による監視負荷を疑う
- 運用では `GATEWAY_RELOAD=false` を使用

## 運用メモ

- 起動は `uv run python -m gateway.main` を使用（実行ディレクトリを固定）
- キー更新時は `GATEWAY_API_KEY` / `GATEWAY_WEBHOOK_SECRET` を同時ローテーション
- サービスアカウント JSON はリポジトリ外管理を推奨
