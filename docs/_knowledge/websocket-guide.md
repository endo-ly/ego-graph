# WebSocket & Terminal Gateway ガイド

このドキュメントは WebSocket の基礎概念と EgoGraph Gateway（Terminal Gateway）のアーキテクチャ、セキュリティについて説明します。

---

## パート1: WebSocket とは

WebSocket は「双方向リアルタイム通信」を実現するプロトコルです。HTTP を拡張した規格で、一度接続すればクライアント・サーバーどちらからでもメッセージを送信できます。

### HTTP との違い

| 特徴 | HTTP | WebSocket |
|------|------|-----------|
| 通信方向 | 一方向（リクエスト→レスポンス） | 双方向（いつでも送信可能） |
| 接続 | 毎回確立・切断 | 一度接続すれば維持 |
| リアルタイム性 | 低い（ポーリング必要） | 高い（即時送信） |
| オーバーヘッド | 接続毎に発生 | 初回ハンドシェイクのみ |

### 通信フロー

```
クライアント                    サーバー
   │                             │
   │  ① HTTP アップグレード要求      │
   ├────────────────────────────→│  GET /ws
   │     Upgrade: websocket        │
   │                             │
   │  ② スイッチ同意               │
   │←────────────────────────────│  101 Switching Protocols
   │                             │
   │  ═════════════════════════════════════════
   │  ║     WebSocket 接続確立（双方向通信可能）    ║
   │  ║                                           ║
   │  ║  "hello!" ───────────────────────────→    ║
   │  ║                                           ║
   │  ║  "hi!" ←────────────────────────────────  ║
   │  ║                                           ║
   │  ═════════════════════════════════════════
```

---

## パート2: EgoGraph Gateway とは

Gateway（ゲートウェイ）は「入り口」「玄関」を意味する言葉で、クライアントとバックエンドサービスの間に立って仲介・翻訳・保護を行うコンポーネントです。

### Gateway の役割

| 役割 | 説明 |
|------|------|
| **認証・認可** | 誰がアクセスして良いかを判断 |
| **ルーティング** | リクエストを適切なサービスへ転送 |
| **プロトコル変換** | HTTP → WebSocket、逆も可 |
| **レート制限** | アクセス数の制限 |
| **CORS 処理** | クロスオリジンリクエストの扱い |

### EgoGraph Gateway の特徴

**Starlette** フレームワークを使用した軽量 Gateway です。

| 機能 | エンドポイント/機能 | 説明 |
|------|-------------------|------|
| **WebSocket 接続** | `ws://gateway:8001/ws/terminal` | tmux セッションとの双方向通信 |
| **セッション管理** | `/api/v1/terminal/sessions` | tmux セッション一覧取得 |
| **ヘルスチェック** | `/health` | サーバー状態確認 |

### アーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│                      EgoGraph Gateway                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────┐      │
│  │  WebSocket Handler                                │      │
│  │  • クライアント接続管理                             │      │
│  │  • 認証 (API Key)                                 │      │
│  │  • メッセージ中継                                   │      │
│  └────────────────────────────────────────────────────┘      │
│                          ↓                                   │
│  ┌────────────────────────────────────────────────────┐      │
│  │  PTY Manager (libtmux)                            │      │
│  │  • tmux セッション制御                              │      │
│  │  • 疑似端末 (PTY) 入出力                            │      │
│  └────────────────────────────────────────────────────┘      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│                   tmux セッション領域                         │
│                                                              │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│   │ agent-0001 │  │ agent-0002 │  │ agent-0003 │            │
│   │ (Claude)   │  │ (batch)    │  │ (debug)    │            │
│   └────────────┘  └────────────┘  └────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

---

## パート3: EgoGraph での使用方法

### 使用目的

- **モバイルアプリと tmux セッションの双方向通信**
- キー入力をスマホからサーバーの仮想端末へ送信
- 仮想端末の出力をスマホの画面にリアルタイム表示

### 接続エンドポイント

```
ws://gateway:8001/ws/terminal?session_id=agent-0001
```

### 認証方式

**WebSocket**: 最初のメッセージで認証
```json
{"type": "auth", "api_key": "your-api-key"}
```

**REST API**: HTTP ヘッダーで認証
```
X-API-Key: your-api-key
```

### 認証フロー

1. WebSocket 接続確立
2. 最初のメッセージで認証（10秒以内）
3. 認証成功で双方向通信開始
4. 10秒以内に認証できない場合、接続切断

### tmux セッション命名規則

セッションID は以下の正規表現でバリデーションされます：

```
^agent-[0-9]{4}$
```

例: `agent-0001`, `agent-1234`

### メッセージ形式

**クライアント → サーバー:**

```json
{"type": "input", "data_b64": "bHMK"}      // キー入力 (Base64)
{"type": "resize", "cols": 120, "rows": 30} // 画面サイズ変更
{"type": "ping"}                            // ハートビート
```

**サーバー → クライアント:**

```json
{"type": "output", "data_b64": "...", "is_snapshot": true} // 画面出力
{"type": "status", "state": "connected"}                      // 接続状態
{"type": "pong"}                                               // ハートビート応答
{"type": "error", "code": "...", "message": "..."}            // エラー通知
```

### ハートビート設定

- **Ping 間隔**: 30秒
- **Ping タイムアウト**: 20秒

---

## パート4: 環境設定と運用

### 環境変数設定

`.env` で設定する項目：

| 環境変数 | 必須 | デフォルト | 説明 |
|---------|------|----------|------|
| `GATEWAY_HOST` | - | `0.0.0.0` | リッスンアドレス |
| `GATEWAY_PORT` | - | `8001` | リッスンポート |
| `GATEWAY_API_KEY` | ✓ | - | API 認証キー（32バイト以上推奨） |
| `CORS_ORIGINS` | - | `*` | CORS 許可オリジン（カンマ区切り） |
| `LOG_LEVEL` | - | `INFO` | ログレベル |

### シークレット生成

```bash
# 32バイト以上のランダム文字列を生成
openssl rand -base64 32
```

### 起動方法

```bash
# tmux セッションで起動（推奨）
tmux new-session -d -s egograph-gateway \
  'uv run uvicorn gateway.main:app --host 0.0.0.0 --port 8001'

# ログ確認
tmux capture-pane -p -S -120 -t egograph-gateway

# セッション停止
tmux kill-session -t egograph-gateway
```

---

## パート5: セキュリティ

### 実施済みセキュリティ対策

| 対策 | 状態 | 評価 |
|-----|------|------|
| API Key 認証 | ✅ 実装済み | ⭐⭐⭐⭐⭐ |
| 初回メッセージ認証 | ✅ 実装済み | ⭐⭐⭐⭐⭐ |
| 認証タイムアウト (10秒) | ✅ 実装済み | ⭐⭐⭐⭐⭐ |
| Pydantic 入力検証 | ✅ 実装済み | ⭐⭐⭐⭐⭐ |
| セッションID パターン制限 | ✅ 実装済み | ⭐⭐⭐⭐ |
| Ping/Pong ハートビート | ✅ 実装済み | ⭐⭐⭐⭐ |

### WebSocket セキュリティリスクと対策

| リスク | 対策 | 実装状況 |
|--------|------|---------|
| 認証不備 | 初回メッセージで強制認証 | ✅ 実装済み |
| CSRF | Origin ヘッダー検証 | ⚠️ 未実装 |
| 入力検証不足 | Pydantic バリデーション | ✅ 実装済み |
| DoS 攻撃 | 接続数制限 | ⚠️ 未実装 |
| 機密性欠如 | TLS/WSS 使用 | ⚠️ 要実装 |
| メッセージ注入 | 厳密なJSONパース | ✅ 実装済み |

### 🔴 優先度高: TLS/WSS 未使用

**現状**: HTTP/WS 平文通信のみ
**リスク**: 通信内容が盗聴・改ざんされる可能性

**推奨対策**: Gateway 前段に Nginx/Caddy 等のリバースプロキシを配置

```nginx
# nginx.conf 例
server {
    listen 443 ssl;
    server_name gateway.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 🟡 優先度中: レート制限未実装

**現状**: 接続数・リクエスト数の制限なし
**推奨対策**: slowapi 等を使用したレート制限

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.websocket("/ws/terminal")
@limiter.limit("10/minute")  # 接続数制限
async def terminal_websocket(...):
    ...
```

### 🟡 優先度中: Origin ヘッダー未検証

**現状**: WebSocket で Origin ヘッダーを検証していない
**推奨対策**: 許可オリジンのリストと照合

```python
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")

async def terminal_websocket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008, reason="Origin not allowed")
        return
```

### セキュリティ評価サマリー

```
認証・認可         ████████████████████░░  90%  ⭐⭐⭐⭐⭐
入力バリデーション   ████████████████████░░  90%  ⭐⭐⭐⭐⭐
通信セキュリティ     ████░░░░░░░░░░░░░░░░░░  20%  ⭐⭐
DoS 対策          ██████░░░░░░░░░░░░░░░░  30%  ⭐⭐⭐
CSRF 対策         ██████░░░░░░░░░░░░░░░░  30%  ⭐⭐⭐

WebSocket全体     ██████████████████░░░  80%  ⭐⭐⭐⭐
```

### 推奨本番構成

```
┌─────────────────────────────────────────────────────────────┐
│                    インターネット                            │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTPS (443) / WSS (443)
                          ↓
┌─────────────────────────────────────────────────────────────┐
│              [リバースプロキシ]                              │
│  • Nginx / Caddy / Traefik                                  │
│  • TLS 終端処理 (Let's Encrypt)                              │
│  • レート制限                                                │
│  • IP フィルタリング                                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTP (8080) / WS (8080)
                          ↓  (内部ネットワーク - 平文で可)
┌─────────────────────────────────────────────────────────────┐
│                   Gateway (:8001)                           │
│  • WebSocket 認証                                           │
│  • 入力バリデーション                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 関連ファイル

- `gateway/main.py` - アプリケーションエントリポイント
- `gateway/api/terminal.py` - WebSocket エンドポイント
- `gateway/services/websocket_handler.py` - ハンドラー実装
- `gateway/services/pty_manager.py` - tmux/PTY 操作
- `gateway/infrastructure/tmux.py` - tmux 操作
- `gateway/domain/models.py` - メッセージモデル定義
- `gateway/config.py` - 設定管理

## 参考資料

- [RFC 6455 - WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
- [MDN - WebSocket API](https://developer.mozilla.org/ja/docs/Web/API/WebSocket)
- [OWASP WebSocket Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html)
- [Starlette Documentation](https://www.starlette.io/)
- [libtmux Documentation](https://libtmux.git-pull.com/)
