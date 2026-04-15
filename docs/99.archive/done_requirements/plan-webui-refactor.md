# Plan: EgoPulse WebUI リファクタリング + レスポンシブデザイン対応

単一ファイル（main.tsx 1145行 / styles.css 587行）に集約された WebUI を、コンポーネント分割・カスタムフック抽出・Tailwind CSS v4 導入により保守可能な構造へリファクタリングし、併せてモバイルファーストのレスポンシブデザインと UX 改善（Markdown レンダリング等）を導入する。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **単一責任の原則**: 1ファイル = 1コンポーネント / 1フック。App コンポーネントは構成要素のオーケストレーションのみ担当
- **Tailwind CSS v4**: `@tailwindcss/vite` プラグイン + CSS-first 設定（`@theme` ディレクティブ）でダークテーマカスタム変数を定義。ユーティリティファーストでレスポンシブも容易
- **モバイルファースト**: ベーススタイルをモバイル（< 768px）とし、`min-width` メディアクエリでタブレット・デスクトップへ拡張。モバイルではサイドバーをドロワー化
- **既存機能の動作保証**: リファクタリング前後で API 通信・SSE ストリーミング・WebSocket・認証フローの振る舞いを維持。ビルド成果物（dist/）の Rust 埋め込み互換性を維持
- **UX 改善は段階導入**: Markdown レンダリング・シンタックスハイライト等は後段 Step で追加。構造改善が先行

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 現状 | 変更後 |
|---|---|---|
| `web/src/main.tsx` | 1145行・全て詰め込み | エントリポイントのみ（~10行） |
| `web/src/styles.css` | 587行・グローバルCSS | 削除 → Tailwind v4 + `app.css` に集約 |
| 型定義 | main.tsx 内 inline | `types.ts` |
| API/SSE/WS/Auth ロジック | App 内関数 | カスタムフック（6個） |
| UI コンポーネント | App 内 JSX | 8コンポーネントに分割 |
| レスポンシブ | @media 1箇所のみ | モバイルファースト3ブレークポイント |
| UX | プレーンテキストのみ | Markdown + コードハイライト |

### 目標ファイル構成

```
web/src/
  types.ts
  api.ts
  hooks/
    useAuth.ts
    useWebSocket.ts
    useConfig.ts
    useSessions.ts
    useStream.ts
  components/
    App.tsx
    Sidebar.tsx
    ChatPanel.tsx
    MessageBubble.tsx
    Composer.tsx
    AuthModal.tsx
    SettingsModal.tsx
    Modal.tsx
    StatusBadge.tsx
  app.css
  main.tsx
```

---

## Step 0: Worktree 作成

`worktree-create` スキルでブランチ `refactor/webui` の WT を作成。

---

## Step 1: テスト基盤構築 + 型定義・ユーティリティ抽出 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `api_sets_auth_header` | authToken が Authorization ヘッダーに設定される |
| `api_throws_on_401` | 401 レスポンスで AuthRequiredError が投げられる |
| `api_throws_on_network_error` | ネットワークエラーで Error が投げられる |
| `api_throws_on_http_error` | 400+ で Error が投げられる |
| `parseSseFrames_yields_events` | 正常な SSE フレームを正しくパースする |
| `parseSseFrames_handles_multiline_data` | 複数 data: 行の結合を検証 |
| `parseSseFrames_handles_empty_lines` | 空行でイベントが flush される |
| `parseSseFrames_ignores_comments` | `:` コメント行が無視される |
| `parseSseFrames_stops_on_abort` | AbortSignal でジェネレータが終了する |
| `loadAuthToken_returns_stored_value` | localStorage からトークンを読み取る |
| `persistAuthToken_saves_and_removes` | 保存と空文字での削除を検証 |
| `sessionKeyNow_formats_correctly` | タイムスタンプ形式の検証 |
| `webSessionKey_normalizes` | 空/プレフィックス付き/前後空白の正規化 |
| `makeId_generates_unique` | 呼び出しごとに一意 ID を生成 |

### GREEN: 実装

- `vitest` + `@testing-library/react` + `jsdom` を devDependencies に追加
- `@tailwindcss/vite` + `tailwindcss` v4 を devDependencies に追加
- `web/src/app.css` — Tailwind v4 `@import "tailwindcss"` + `@theme` でカスタム変数定義（現行 CSS Variables を移行）
- `vitest.config.ts` を作成（jsdom 環境、setup ファイル指定）
- `web/src/types.ts` — 全型定義を抽出（SessionItem, MessageItem, ConfigPayload 等）
- `web/src/api.ts` — api 関数、AuthRequiredError クラス、parseSseFrames、auth helpers、utility 関数を集約

### コミット

`chore(web): add test infrastructure and extract types/utilities`

---

## Step 2: カスタムフック抽出 — 認証・API・WebSocket (TDD)

前提: Step 1

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `useAuth_initializes_from_storage` | 初期値が localStorage の値 |
| `useAuth_save_updates_token` | handleSaveAuthToken が state と localStorage を更新 |
| `useApi_calls_with_current_token` | api 呼び出しに現在の authToken が使われる |
| `useApi_wraps_auth_error` | 401 で setShowAuth(true) が発火 |
| `useWebSocket_initial_state` | 初期 wsState は "connecting" |
| `useWebSocket_connects_on_mount` | マウント時に WebSocket 接続を試行 |
| `useWebSocket_handles_challenge` | connect.challenge → connect レスポンス送信 |
| `useWebSocket_sets_open_on_success` | 接続成功で wsState="open" |
| `useWebSocket_sets_closed_on_error` | エラーで wsState="closed" |
| `useWebSocket_closes_on_unmount` | アンマウントで socket.close() |

### GREEN: 実装

- `web/src/hooks/useAuth.ts` — authToken, authDraft, showAuth の状態管理、loadAuthToken, persistAuthToken も含む
- `web/src/hooks/useWebSocket.ts` — WebSocket 接続ライフサイクル、challenge-response 認証、再接続ロジック

### コミット

`refactor(web): extract auth, api, and websocket hooks`

---

## Step 3: カスタムフック抽出 — Config・Sessions・Stream (TDD)

前提: Step 2

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `useConfig_loads_initial` | 初回マウントで config を取得 |
| `useConfig_save_updates_state` | handleSaveConfig が API を呼び config を更新 |
| `useConfig_save_sends_api_key` | api_key がペイロードに含まれる |
| `useConfig_clear_api_key` | "*CLEAR*" で api_key をクリア |
| `useSessions_loads_list` | セッション一覧を取得 |
| `useSessions_selects_first` | 初期選択が最初のセッション |
| `useSessions_creates_new` | handleNewSession でリストに追加 |
| `useSessions_switches_session` | セッション切替で履歴を再読込 |
| `useStream_sends_message` | handleSend が send_stream API を呼ぶ |
| `useStream_appends_delta` | SSE delta イベントでメッセージが更新される |
| `useStream_handles_done` | done イベントでストリームが終了する |
| `useStream_handles_error` | SSE error でエラーステータス表示 |
| `useStream_aborts_previous` | 新規送信で前の AbortController が abort される |

### GREEN: 実装

- `web/src/hooks/useConfig.ts` — config 状態、refreshConfig、handleSaveConfig、selectedProvider、withAuthHandling の導出
- `web/src/hooks/useSessions.ts` — sessions/selectedSession/messages 状態、refreshSessions、loadHistory、handleNewSession
- `web/src/hooks/useStream.ts` — handleSend、SSE ストリーミング処理、abort 制御、status 管理

### コミット

`refactor(web): extract config, sessions, and stream hooks`

---

## Step 4: 共通 UI コンポーネント + Sidebar・AuthModal 抽出 (TDD)

前提: Step 3

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `StatusBadge_renders_tone` | tone クラスが適用される |
| `StatusBadge_renders_text` | テキストが表示される |
| `Modal_renders_backdrop` | backdrop が存在する |
| `Modal_closes_on_backdrop_click` | 背景クリックで onClose が呼ばれる |
| `Modal_closes_on_escape` | Escape キーで onClose が呼ばれる |
| `Sidebar_renders_sessions` | セッション一覧が表示される |
| `Sidebar_highlights_active` | 選択中セッションに active クラス |
| `Sidebar_calls_onNewSession` | New Session ボタンでコールバック発火 |
| `Sidebar_calls_onSelectSession` | セッションアイテムクリックでコールバック |
| `Sidebar_calls_onOpenSettings` | Config ボタンでコールバック |
| `AuthModal_renders_form` | トークン入力フォームが表示される |
| `AuthModal_submits_token` | フォーム送信で onSave が呼ばれる |

### GREEN: 実装

- `web/src/components/StatusBadge.tsx` — ステータスバッジ
- `web/src/components/Modal.tsx` — モーダル Backdrop + Card の共通ラッパー
- `web/src/components/Sidebar.tsx` — ブランド、ボタン、セッションリスト
- `web/src/components/AuthModal.tsx` — 認証トークン入力モーダル

### コミット

`refactor(web): extract Sidebar and AuthModal components`

---

## Step 5: ChatPanel・MessageBubble・Composer 抽出 (TDD)

前提: Step 4

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `ChatPanel_renders_header` | セッション名とステータスが表示 |
| `ChatPanel_renders_messages` | メッセージ一覧が表示 |
| `ChatPanel_renders_composer` | 入力フォームが表示 |
| `MessageBubble_bot_style` | is_from_bot=true で bot クラス |
| `MessageBubble_user_style` | is_from_bot=false で user クラス |
| `MessageBubble_renders_timestamp` | タイムスタンプが表示 |
| `Composer_updates_draft` | 入力で draft が更新 |
| `Composer_submits_on_button` | 送信ボタンで onSubmit 発火 |
| `Composer_submits_on_ctrl_enter` | Ctrl+Enter で onSubmit 発火 |
| `Composer_prevents_empty_send` | 空文字で送信されない |

### GREEN: 実装

- `web/src/components/ChatPanel.tsx` — ヘッダー + メッセージエリア + コンポーザーの統合
- `web/src/components/MessageBubble.tsx` — メッセージバブル（送信者名、時刻、内容）
- `web/src/components/Composer.tsx` — textarea + 送信ボタン

### コミット

`refactor(web): extract ChatPanel, MessageBubble, and Composer components`

---

## Step 6: SettingsModal 抽出 + App 整合 (TDD)

前提: Step 5

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `SettingsModal_renders_providers` | プロバイダ一覧が表示 |
| `SettingsModal_selects_provider` | Provider セレクトで default_provider が更新 |
| `SettingsModal_shows_api_key_status` | has_api_key に応じて表示が変わる |
| `SettingsModal_clears_api_key` | Clear ボタンで "*CLEAR*" が設定 |
| `SettingsModal_toggles_web_enabled` | チェックボックスで web_enabled が更新 |
| `SettingsModal_saves_on_submit` | Save ボタンで onSaveConfig 発火 |
| `SettingsModal_closes_on_escape` | Escape で onClose |
| `App_renders_without_crash` | App コンポーネントがクラッシュせず描画 |
| `App_initializes_auth` | 初回マウントで認証フローが開始 |
| `App_connects_gateway` | 初回マウントで WebSocket 接続 |

### GREEN: 実装

- `web/src/components/SettingsModal.tsx` — プロバイダ選択、モデル設定、API Key 管理、チャネルオーバーライド
- `web/src/components/App.tsx` — 各フック・コンポーネントを統合。JSX は構成のみ
- `web/src/main.tsx` — React ルートマウントのみに瘦身

旧 `main.tsx` と `styles.css` を削除。

### コミット

`refactor(web): extract SettingsModal and wire up App component`

---

## Step 7: モバイルファースト レスポンシブデザイン (TDD)

前提: Step 6

> **注意**: CSS media query の描画結果は jsdom では検証不可。本 Step のユニットテストは DOM 構造・クラス名・props の確認に留め、実際のビジュアルレイアウトは Step 9 のブラウザ実機確認で担保する。

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `Sidebar_renders_hamburger_button` | ハンバーガートグルボタンが DOM に存在 |
| `Sidebar_toggles_open_state` | onToggle コールバックで isOpen が切り替わる |
| `Sidebar_overlay_closes_on_click` | オーバーレイ要素の onClick で onClose が発火 |
| `Sidebar_has_drawer_class_when_open` | isOpen=true でドロワー用クラスが付与 |
| `ChatPanel_renders_menu_button` | ヘッダーにサイドバートグルボタンが存在 |

### GREEN: 実装

ブレークポイント設計:
- **Mobile**: `< 768px` — ドロワーサイドバー、全画面モーダル、縦並びコンポーザー
- **Tablet**: `768px - 1024px` — 折りたたみ可能サイドバー
- **Desktop**: `> 1024px` — 固定サイドバー（現行レイアウトベース）

実装内容:
- CSS Modules 内で `@media (min-width: 768px)` / `(min-width: 1024px)` を使用
- Sidebar に `isOpen` / `onToggle` props を追加。モバイルではオーバーレイドロワー
- ChatPanel ヘッダーにハンバーガーアイコン（CSS-only hamburger または SVG）
- Composer はモバイルで grid-template-columns: 1fr に変更
- Modal はモバイルで border-radius: 0、inset: 0

### コミット

`feat(web): add mobile-first responsive design`

---

## Step 8: UX 改善 — Markdown レンダリング・ストリーミング表示 (TDD)

前提: Step 7

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `MessageBubble_renders_markdown` | bot メッセージが Markdown として描画される |
| `MessageBubble_renders_code_block` | コードブロックに pre/code タグが使用される |
| `MessageBubble_renders_inline_code` | インラインコードに code タグが使用される |
| `MessageBubble_renders_links` | リンクが a タグとして描画 |
| `MessageBubble_user_shows_plain_text` | ユーザーメッセージはプレーンテキストのまま |
| `MessageBubble_streaming_indicator` | ストリーミング中にインジケータが表示 |

### GREEN: 実装

- `react-markdown` + `remark-gfm` を dependencies に追加
- `MessageBubble` の bot メッセージを `<ReactMarkdown>` でラップ
- ストリーミング中（ID に `draft:` を含む）のメッセージにカーソル点滅アニメーション追加
- コードブロック用のスタイル追加（highlight.js の CSS テーマをインポート、または簡易スタイル）

### コミット

`feat(web): add markdown rendering and streaming indicator`

---

## Step 9: ビルド検証 + E2E ブラウザ実動作確認

### ビルド検証

- `npm run build --prefix egopulse/web` が成功すること
- 生成された `dist/` のファイル構造が Rust 側 `include!(concat!(env!("OUT_DIR"), "/web_assets.rs"))` と互換であること
- `cargo check -p egopulse` が通ること
- 全ユニットテスト通過: `npm run test --prefix egopulse/web`
- 型チェック: `tsc --noEmit`

### E2E ブラウザ実動作確認

`cargo run -p egopulse -- run` で実サーバを立て、以下をブラウザで手動確認。

| 確認項目 | 手順 |
|---|---|
| 認証なしアクセス | auth_token 未設定時、AuthModal が表示され API 呼び出しが 401 でブロックされる |
| 認証ありアクセス | トークン入力 → localStorage 保存 → API 全通り |
| SSE ストリーミング完走 | メッセージ送信 → delta → done まで完走。ストリーミングインジケータ表示 |
| SSE エラーハンドリング | 不正なリクエストで error イベント → エラーステータス表示 |
| WebSocket 接続 | Gateway: open 表示。challenge-response 認証成功 |
| WebSocket 接続失敗 | 不正トークン → closed + AuthModal 再表示 |
| セッション切替 | サイドバーで別セッション選択 → 履歴読み込み → メッセージ表示 |
| 新規セッション作成 | New Session → 空メッセージエリア → 送信可能 |
| 設定保存 | Runtime Config → Provider/Model 変更 → Save → 反映確認 |
| モバイルレイアウト | DevTools で 375px ビューポート → ドロワーサイドバー、全画面モーダル、縦並びコンポーザー |
| タブレットレイアウト | 768px ビューポート → 折りたたみサイドバー、適切なレイアウト |
| デスクトップレイアウト | 1280px ビューポート → 固定サイドバー、現行レイアウト互換 |
| Markdown レンダリング | bot レスポンスの見出し・リスト・コードブロック・リンクが正しく描画 |
| Rust 埋め込みビルド | `cargo build -p egopulse` → バイナリに WebUI が正しく埋め込まれ `/` で配信される |

### コミット

`test(web): verify build, E2E browser smoke, and responsive layouts`

---

## Step 10: PR 作成

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/web/package.json` | 変更 | テスト・Tailwind v4・Markdown 依存追加 |
| `egopulse/web/vite.config.ts` | 変更 | Tailwind Vite プラグイン追加 |
| `egopulse/web/vitest.config.ts` | **新規** | Vitest 設定 |
| `egopulse/web/tsconfig.json` | 変更 | テスト型設定追加（必要に応じて） |
| `egopulse/web/src/main.tsx` | 変更 | エントリポイントのみに瘦身 |
| `egopulse/web/src/app.css` | **新規** | Tailwind v4 `@import` + `@theme` でカスタム変数定義 |
| `egopulse/web/src/styles.css` | **削除** | → `app.css` + Tailwind ユーティリティに置換 |
| `egopulse/web/src/types.ts` | **新規** | 型定義集約 |
| `egopulse/web/src/api.ts` | **新規** | API 通信・SSE パーサー・Auth・ヘルパー関数 |
| `egopulse/web/src/hooks/useAuth.ts` | **新規** | 認証フック |
| `egopulse/web/src/hooks/useWebSocket.ts` | **新規** | WebSocket フック |
| `egopulse/web/src/hooks/useConfig.ts` | **新規** | 設定管理フック |
| `egopulse/web/src/hooks/useSessions.ts` | **新規** | セッション管理フック |
| `egopulse/web/src/hooks/useStream.ts` | **新規** | ストリーミングフック |
| `egopulse/web/src/components/App.tsx` | **新規** | App オーケストレーター |
| `egopulse/web/src/components/Sidebar.tsx` | **新規** | サイドバーコンポーネント |
| `egopulse/web/src/components/ChatPanel.tsx` | **新規** | チャットパネル |
| `egopulse/web/src/components/MessageBubble.tsx` | **新規** | メッセージバブル |
| `egopulse/web/src/components/Composer.tsx` | **新規** | メッセージ入力 |
| `egopulse/web/src/components/AuthModal.tsx` | **新規** | 認証モーダル |
| `egopulse/web/src/components/SettingsModal.tsx` | **新規** | 設定モーダル |
| `egopulse/web/src/components/Modal.tsx` | **新規** | 共通モーダルラッパー |
| `egopulse/web/src/components/StatusBadge.tsx` | **新規** | ステータスバッジ |

---

## コミット分割

1. `chore(web): add Tailwind v4, Vitest, and extract types/utilities`
2. `refactor(web): extract auth and websocket hooks`
3. `refactor(web): extract config, sessions, and stream hooks`
4. `refactor(web): extract Sidebar, AuthModal, and shared UI components`
5. `refactor(web): extract ChatPanel, MessageBubble, and Composer`
6. `refactor(web): extract SettingsModal and wire up App component`
7. `feat(web): add mobile-first responsive design`
8. `feat(web): add markdown rendering and streaming indicator`
9. `test(web): verify build, E2E browser smoke, and responsive layouts`

---

## テストケース一覧（全 61 件）

### api.ts (14)
1. `api_sets_auth_header` — authToken が Authorization ヘッダーに設定される
2. `api_throws_on_401` — 401 で AuthRequiredError
3. `api_throws_on_network_error` — ネットワークエラーで Error
4. `api_throws_on_http_error` — 400+ で Error
5. `parseSseFrames_yields_events` — 正常 SSE フレームパース
6. `parseSseFrames_handles_multiline_data` — 複数 data: 行の結合
7. `parseSseFrames_handles_empty_lines` — 空行で flush
8. `parseSseFrames_ignores_comments` — コメント行無視
9. `parseSseFrames_stops_on_abort` — Abort で終了
10. `loadAuthToken_returns_stored_value` — localStorage 読み取り
11. `persistAuthToken_saves_and_removes` — 保存と削除
12. `sessionKeyNow_formats_correctly` — タイムスタンプ形式
13. `webSessionKey_normalizes` — セッションキー正規化
14. `makeId_generates_unique` — 一意 ID 生成

### hooks/useAuth (2)
15. `useAuth_initializes_from_storage` — 初期値が localStorage
16. `useAuth_save_updates_token` — state と localStorage 更新

### hooks/useWebSocket (5)
17. `useWebSocket_initial_state` — 初期 wsState="connecting"
18. `useWebSocket_connects_on_mount` — マウント時接続
19. `useWebSocket_handles_challenge` — challenge-response 認証
20. `useWebSocket_sets_open_on_success` — 接続成功で open
21. `useWebSocket_closes_on_unmount` — アンマウントで close

### hooks/useConfig (4)
22. `useConfig_loads_initial` — 初回 config 取得
23. `useConfig_save_updates_state` — handleSaveConfig 更新
24. `useConfig_save_sends_api_key` — api_key ペイロード含有
25. `useConfig_clear_api_key` — "*CLEAR*" クリア

### hooks/useSessions (4)
26. `useSessions_loads_list` — セッション一覧取得
27. `useSessions_selects_first` — 初期選択
28. `useSessions_creates_new` — handleNewSession 追加
29. `useSessions_switches_session` — 切替で履歴再読込

### hooks/useStream (5)
30. `useStream_sends_message` — send_stream API 呼び出し
31. `useStream_appends_delta` — delta でメッセージ更新
32. `useStream_handles_done` — done でストリーム終了
33. `useStream_handles_error` — error でエラー表示
34. `useStream_aborts_previous` — 前の AbortController abort

### components (28)
35. `StatusBadge_renders_tone` — tone クラス適用
36. `StatusBadge_renders_text` — テキスト表示
37. `Modal_renders_backdrop` — backdrop 存在
38. `Modal_closes_on_backdrop_click` — 背景クリックで onClose
39. `Modal_closes_on_escape` — Escape で onClose
40. `Sidebar_renders_sessions` — セッション一覧表示
41. `Sidebar_highlights_active` — active クラス
42. `Sidebar_calls_onNewSession` — New Session コールバック
43. `Sidebar_calls_onSelectSession` — セッション選択コールバック
44. `Sidebar_renders_hamburger_button` — ハンバーガートグルボタンが DOM に存在
45. `Sidebar_toggles_open_state` — onToggle コールバックで isOpen 切替
46. `Sidebar_overlay_closes_on_click` — オーバーレイ onClick で onClose 発火
47. `Sidebar_has_drawer_class_when_open` — isOpen=true でドロワー用クラスが付与
48. `ChatPanel_renders_menu_button` — ヘッダーにサイドバートグルボタンが存在
49. `AuthModal_renders_form` — トークン入力フォーム
50. `AuthModal_submits_token` — onSave コールバック
51. `ChatPanel_renders_header` — セッション名とステータス
52. `ChatPanel_renders_messages` — メッセージ一覧
53. `ChatPanel_renders_composer` — 入力フォーム
54. `MessageBubble_bot_style` — bot クラス
55. `MessageBubble_user_style` — user クラス
56. `MessageBubble_renders_timestamp` — タイムスタンプ
57. `Composer_updates_draft` — 入力で draft 更新
58. `Composer_submits_on_button` — 送信ボタン発火
59. `Composer_submits_on_ctrl_enter` — Ctrl+Enter 発火
60. `Composer_prevents_empty_send` — 空文字送信防止
61. `App_renders_without_crash` — クラッシュせず描画

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | WT作成 | ~10行 |
| Step 1 | Tailwind v4 + Vitest 導入、型・api.ts 抽出 | ~400行 |
| Step 2 | hooks: auth, websocket | ~250行 |
| Step 3 | hooks: config, sessions, stream | ~380行 |
| Step 4 | 共通UI + Sidebar + AuthModal | ~300行 |
| Step 5 | ChatPanel + MessageBubble + Composer | ~280行 |
| Step 6 | SettingsModal + App 統合 | ~320行 |
| Step 7 | レスポンシブデザイン | ~180行 |
| Step 8 | UX改善（Markdown等） | ~150行 |
| Step 9 | ビルド検証 + E2E ブラウザ確認 | ~50行 |
| **合計** | | **~2,320行** |
