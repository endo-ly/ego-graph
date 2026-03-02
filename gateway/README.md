# Gateway - Mobile Terminal Gateway

tmux セッションへの WebSocket 接続とプッシュ通知を提供する独立サービスです。

## 機能

- **tmux セッション管理**: `agent-XXXX` 形式の tmux セッションを列挙・管理
- **WebSocket 接続**: 端末入出力の双方向通信（予定）
- **プッシュ通知**: FCM 経由の通知送信（予定）
- **認証**: API Key と Webhook シークレットによる認証

## 開発

### 依存関係のインストール

```bash
cd /root/workspace/ego-graph
uv sync
```

### 環境変数設定

`.env.example` をコピーして `.env` を作成し、必要な環境変数を設定してください。

```bash
cp gateway/.env.example gateway/.env
```

必須環境変数:
- `GATEWAY_API_KEY`: Gateway API Key（32バイト以上推奨）
- `GATEWAY_WEBHOOK_SECRET`: Webhook シークレット（32バイト以上推奨）
- `CORS_ORIGINS`: ブラウザアクセスを許可する Origin（本番は `https://<host>.ts.net` を明示）

`CORS_ORIGINS` の設定指針:
- 本番: `https://<host>.ts.net` を必要数だけカンマ区切りで指定
- 開発: 一時的に `*` も利用可能（ただし本番非推奨）

プッシュ通知利用時に必要な環境変数:
- `FCM_PROJECT_ID`: Firebase プロジェクト ID
- `FCM_CREDENTIALS_PATH`: Firebase サービスアカウント JSON パス（省略時 `gateway/firebase-service-account.json`）

### サーバー起動

```bash
cd gateway
uv run python -m gateway.main
```

`uvicorn gateway.main:app` を直接使うと `GATEWAY_HOST` / `GATEWAY_PORT` が反映されないため、
設定値で起動したい場合は `python -m gateway.main` を使用してください。
`GATEWAY_RELOAD` はデフォルトで `false` です。開発時のみ `true` にしてください。

uvicorn を直接使用する場合:

```bash
uvicorn gateway.main:app --host 127.0.0.1 --port 8001 --reload
```

### テスト実行

```bash
cd gateway
uv run pytest tests/ -v
```

単体テストのみ:

```bash
uv run pytest tests/unit/ -v
```

## API エンドポイント

### `GET /health`

ヘルスチェック

### `GET /api/v1/terminal/sessions`

tmux セッション一覧を取得

認証: X-API-Key 必須

### Terminal WebSocket トークン運用上の注意

- `terminal_ws_token_store` は in-memory 実装です。
- `POST /api/v1/terminal/sessions/{session_id}/ws-token` で発行したトークンは、同じプロセスでの `terminal_ws_token_store.consume` でのみ検証できます。
- マルチプロセス/マルチPod構成では、sticky-session で同一インスタンスへ到達させるか、共有ストア実装（例: Redis）に置き換えてください。

## プロジェクト構成

```
gateway/
├── api/              # API ルート
├── domain/           # ドメインモデル
├── infrastructure/   # インフラストラクチャ（DB、tmux）
├── tests/            # テスト
├── config.py         # 設定管理
├── dependencies.py   # 依存関数（認証など）
└── main.py           # アプリケーションエントリーポイント
```

## ライセンス

本プロジェクトの一部として、同じライセンスが適用されます。
