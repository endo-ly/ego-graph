# Terminal 機能設計

## 画面構成

セッション一覧画面（AgentListScreen）+ ターミナル画面（TerminalScreen）

---

## AgentListScreen: セッション一覧

### 起動時

1. Gateway APIからアクティブなtmuxセッション一覧を取得
2. セッション名、ID、ステータスを表示

### 操作

- セッション選択 → TerminalScreenへ遷移（セッションIDを渡す）
- リフレッシュボタン → セッション一覧を再取得
- Gateway設定ボタン → GatewaySettings画面へ遷移

---

## TerminalScreen: ターミナルセッション

### 接続フロー

1. 画面表示時、WebSocket URLとAPIキーを設定から取得
2. WebView内のxterm.jsがWebSocket接続を確立
3. 接続状態を監視（Flow<Boolean>）
4. 切断時は自動再接続を試みる

### キーボード対応

- ソフトウェアキーボード表示時、画面下部に入力欄へフォーカス
- `SpecialKeysBar` で特殊キー送信: Ctrl, Alt, Tab, Esc, 矢印キー
- これらはモバイルで通常入力できないキーを補完

### エラーハンドリング

- 接続エラー時、ヘッダーにエラーメッセージを表示
- Gateway URL/キーが未設定の場合はGatewaySettingsへ誘導
