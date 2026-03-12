# Maestro Test Tag Mapping

E2Eテスト自動化のためのCompose UI testtag命名規約と実装マッピング

## 命名規約

### 基本形式

```
<screen>_<element>_<action>
```

または簡易形式:

```
<element>_<type>
```

### 命名パターン

| パターン            | 説明                 | 例                                    |
| ------------------- | -------------------- | ------------------------------------- |
| `element_type`      | UI要素の種類         | `chat_input_field`, `message_list`    |
| `element_action`    | ボタン等のアクション | `send_button`, `save_settings_button` |
| `element_menu`      | メニューアイテム     | `system_prompt_menu`                  |
| `prompt_tab_{name}` | 動的タブ             | `prompt_tab_concise`                  |

### 実装要件

すべてのtesttagは以下の修飾子を含む必要があります:

```kotlin
Modifier
    .semantics { testTagsAsResourceId = true }
    .testTag("tag_name")
```

## 画面別testtag一覧

### 1. チャット画面 (Chat Screen)

チャットメッセージの送信と表示を行うメイン画面。

| testtag            | 要素                     | ファイル         | 行番号 |
| ------------------ | ------------------------ | ---------------- | ------ |
| `chat_input_field` | メッセージ入力フィールド | `ChatInput.kt`   | 58     |
| `send_button`      | 送信ボタン               | `ChatInput.kt`   | 89     |
| `message_list`     | メッセージ一覧           | `MessageList.kt` | 55     |
| `error_message`    | エラーメッセージ表示     | `ChatInput.kt`   | -      |

### 2. スレッド一覧 (Thread List)

サイドバーに表示されるスレッド履歴一覧。

| testtag       | 要素                 | ファイル        | 行番号 |
| ------------- | -------------------- | --------------- | ------ |
| `thread_list` | スレッド一覧コンテナ | `ThreadList.kt` | 117    |
| `thread_item` | 個別スレッドアイテム | `ThreadItem.kt` | 54     |

### 3. モデル選択 (Model Selector)

チャット入力欄内のモデル選択ドロップダウン。

| testtag          | 要素         | ファイル           | 行番号 |
| ---------------- | ------------ | ------------------ | ------ |
| `model_selector` | モデル選択UI | `ModelSelector.kt` | 97     |

### 4. 設定画面 (Settings Screen)

API設定とテーマ設定を行う画面。

| testtag                | 要素                  | ファイル            | 行番号 |
| ---------------------- | --------------------- | ------------------- | ------ |
| `api_url_input`        | API URL入力フィールド | `SettingsScreen.kt` | 162    |
| `api_key_input`        | APIキー入力フィールド | `SettingsScreen.kt` | 196    |
| `save_settings_button` | 設定保存ボタン        | `SettingsScreen.kt` | 231    |

### 5. サイドバー (Sidebar)

スレッド履歴とナビゲーションを提供するサイドバードロワー。

| testtag              | 要素                               | ファイル           | 行番号 |
| -------------------- | ---------------------------------- | ------------------ | ------ |
| `settings_button`    | 設定ボタン（アイコン）             | `SidebarHeader.kt` | 57     |
| `new_chat_button`    | 新規チャットボタン                 | `SidebarHeader.kt` | 75     |
| `system_prompt_menu` | システムプロンプトメニューアイテム | `SidebarScreen.kt` | 79     |

### 6. システムプロンプトエディタ (System Prompt Editor)

システムプロンプトの編集画面。

| testtag              | 要素                     | ファイル                      | 行番号 |
| -------------------- | ------------------------ | ----------------------------- | ------ |
| `prompt_editor`      | プロンプト編集フィールド | `SystemPromptEditor.kt`       | 26     |
| `back_button`        | キャンセル/戻るボタン    | `SystemPromptEditorScreen.kt` | 89     |
| `save_prompt_button` | プロンプト保存ボタン     | `SystemPromptEditorScreen.kt` | 117    |

### 7. システムプロンプトタブ (System Prompt Tabs)

プロンプトエディタのタブ切り替えUI（動的生成）。

| testtag               | 要素           | ファイル              | 行番号 |
| --------------------- | -------------- | --------------------- | ------ |
| `prompt_tab_user`     | タブ: User     | `SystemPromptTabs.kt` | 32     |
| `prompt_tab_concise`  | タブ: Concise  | `SystemPromptTabs.kt` | 32     |
| `prompt_tab_detailed` | タブ: Detailed | `SystemPromptTabs.kt` | 32     |
| `prompt_tab_creative` | タブ: Creative | `SystemPromptTabs.kt` | 32     |

※ `SystemPromptTabs.kt`の行32で動的生成: `testTag("prompt_tab_${tab.apiName}")`

### 8. ターミナル画面 (Terminal Screen)

tmuxセッションへの接続、ターミナル操作、セッション管理を行う画面。

| testtag                    | 要素                                   | ファイル                  | 行番号 |
| ------------------------- | -------------------------------------- | ------------------------- | ------ |
| `session_item`            | セッションリストの個別アイテム         | `SessionListItem.kt`      | 71     |
| `session_preview`         | セッションのターミナルプレビュー表示   | `SessionListItem.kt`      | 126    |
| `terminal_status_pill`    | ターミナル下部のフローティングピル     | `TerminalControls.kt`     | 77     |
| `terminal_back_button`    | ターミナル画面の戻るボタン             | `TerminalControls.kt`     | 32     |
| `terminal_keyboard_toggle`| キーボード表示/非表示トグルボタン      | `TerminalControls.kt`     | 46     |
| `terminal_copy_button`    | ターミナル内容コピーボタン             | `TerminalControls.kt`     | 61     |
| `terminal_copy_feedback`  | コピー完了フィードバック               | `TerminalControls.kt`     | 124    |

※ タグ定数は `TerminalTestTags.kt` で一元管理されています。

## ファイルパス

全てのUIファイルは以下のパスに配置されています:

```
frontend/shared/src/commonMain/kotlin/dev/egograph/shared/ui/
├── ChatInput.kt
├── MessageList.kt
├── ThreadList.kt
├── ThreadItem.kt
├── ModelSelector.kt
├── settings/
│   └── SettingsScreen.kt
├── sidebar/
│   ├── SidebarHeader.kt
│   └── SidebarScreen.kt
└── systemprompt/
    ├── SystemPromptTabs.kt
    ├── SystemPromptEditor.kt
    └── SystemPromptEditorScreen.kt
```

**ターミナル機能のファイル:**

```
frontend/shared/src/commonMain/kotlin/dev/egograph/shared/features/terminal/
├── TerminalTestTags.kt
├── agentlist/components/
│   └── SessionListItem.kt
└── session/components/
    ├── TerminalControls.kt
    ├── SpecialKeysBar.kt
    └── ...
```

## Maestroフローでの使用例

```yaml
# メッセージ送信
- tapOn: "chat_input_field"
- inputText: "Hello, EgoGraph!"
- tapOn: "send_button"

# スレッド選択
- tapOn: "thread_list"
- tapOn: "thread_item"

# 設定変更
- tapOn: "settings_button"
- tapOn: "api_url_input"
- inputText: "https://api.egograph.dev"
- tapOn: "save_settings_button"

# ターミナル操作
- tapOn: "session_item"
- assertVisible: "terminal_back_button"
- tapOn: "terminal_copy_button"
- assertVisible: "terminal_copy_feedback"
```
```

## 実装ガイドライン

### 新規testtag追加時

1. **命名規約に従う**: 画面名をプレフィックスに含める
2. **一意性を確保**: 既存のtesttagと重複しない
3. **semantics修飾子**: 必ず `testTagsAsResourceId = true` を含める
4. **ドキュメント更新**: このファイルの該当セクションを更新

### 実装テンプレート

```kotlin
Modifier
    .semantics { testTagsAsResourceId = true }
    .testTag("your_tag_name")
```

## 関連ドキュメント

- [Maestro Flows](./flows/) - E2Eテストフロー定義（READMEなし）
- [Frontend README](../frontend/README.md) - アプリケーション概要
- [Compose Testing](https://developer.android.com/jetpack/compose/testing) - Compose UIテスト公式ドキュメント
