# Settings 機能設計

## 画面構成

テーマ選択 + API設定

---

## テーマ設定

- LIGHT / DARK / SYSTEM から選択
- 選択はローカルに永続化（PlatformPreferences）
- SYSTEM選択時はシステムのダークモード設定に従う

---

## API設定

- **API URL**: バックエンドAPIのベースURL（例: `https://api.egograph.dev`）
- **API Key**: 認証用キー（パスワードマスク表示、表示切替可能）

### 保存動作

- Saveボタン押下でローカルに永続化
- 即座に全APIリクエストで新しい設定が使用される

---

## SystemPrompt 画面

### 画面構成

タブ切り替え + テキストエディタ + 保存ボタン

### タブ定義

| タブ | 説明 |
|------|------|
| USER | ユーザー定義のカスタムプロンプト |
| DEFAULT | システムデフォルトプロンプト（参照用） |
| PROJECT | プロジェクト固有プロンプト |

### 編集フロー

1. タブ選択 → APIから該当プロンプトを取得
2. `originalContent`（元の値）と `draftContent`（編集中）に保存
3. ユーザーがテキストを編集 → `draftContent` が更新
4. **変更がない場合**: Saveボタンは無効
5. Save押下 → APIに更新リクエスト送信
6. 成功時 → `originalContent` を更新、Snackbarで完了通知

### 注意点

- DEFAULT/PROJECTタブは参照用（編集不可の場合あり）
- 読み込み中はローディング表示
- ネットワークエラー時はエラー表示

---

## Sidebar（サイドバー）

### 画面構成

Drawer（左）+ メインコンテンツ（右）

### Drawer（左パネル）

#### 履歴セクション

- スレッド一覧を表示（最新順）
- 下スクロールでさらに読み込み（ページネーション）
- スレッド選択 → Chat画面でそのスレッドを開く

#### フッターアクション

| ボタン | 動作 |
|--------|------|
| New Chat | Chat画面へ遷移 + スレッド選択解除 |
| Settings | Settings画面へ遷移 |
| Terminal | Terminal画面へ遷移 |
| SystemPrompt | SystemPrompt画面へ遷移 |

### ジェスチャー制御

- Chat/TerminalSession画面で左スワイプ → Drawerを開く
- 他の画面ではジェスチャー無効
- Drawerオープン時にキーボードを閉じる

### メインコンテンツ

`MainNavigationHost` が現在の `MainView` に応じた画面を表示:
- Chat, Terminal, TerminalSession, Settings, SystemPrompt, GatewaySettings
