# Plan: チャットスラッシュコマンド実装

Telegram / Discord / CLI チャット / TUI / Web チャットでスラッシュコマンドを利用可能にする。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- Microclaw `src/chat_commands.rs` に準拠: `is_slash_command()` → `handle_slash_command()` → match dispatch
- **Microclaw 準拠の API シグネチャ**: `handle_slash_command(state, chat_id, caller_channel, text, sender_id)` — `SurfaceContext` は渡さない
- 全チャネル共通の `slash_commands` モジュールを新規作成
- 既存の `llm_profile.rs` の `/model` `/provider` 系ロジックをそのまま再利用
- Discord Application Commands API + Telegram BotFather `setMyCommands` でコマンド UI を登録

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## コマンドラインナップ

| コマンド | 実装元 |
|---|---|
| `/new` | 新規 |
| `/compact` | 新規 |
| `/status` | 新規 |
| `/skills` | 新規 |
| `/restart` | 新規 |
| `/providers` | `llm_profile.rs` 再利用 |
| `/provider [name\|reset]` | `llm_profile.rs` 再利用 |
| `/models` | `llm_profile.rs` 再利用 |
| `/model [name\|reset]` | `llm_profile.rs` 再利用 |

---

## Step 0: Worktree 作成

`worktree-create` skill で `feat/slash-commands` ブランチの worktree を作成。

---

## Step 1: `storage.rs` — `clear_session()` (TDD)

### RED: テスト先行

```rust
#[test]
fn clear_session_deletes_snapshots_and_messages() {
    // setup: chat_id に snapshot + messages を保存
    // act: clear_session(chat_id)
    // assert: load_session → None, get_recent_messages → empty
}

#[test]
fn clear_session_idempotent_on_empty_chat() {
    // 存在しない chat_id で clear_session → エラーにならない
}
```

### GREEN: 実装

```rust
pub fn clear_session(&self, chat_id: i64) -> Result<(), StorageError> {
    self.execute("DELETE FROM session_snapshots WHERE chat_id = ?", (chat_id,))?;
    self.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))?;
    Ok(())
}
```

### コミット

`feat: add clear_session to Database`

---

## Step 2: `compaction.rs` — `force_compact()` (TDD)

### RED: テスト先行

```rust
#[tokio::test]
async fn force_compact_runs_regardless_of_threshold() {
    // 2メッセージのセッション（max_session_messages よりはるかに少ない）
    // force_compact → compaction が実行される（閾値バイパス確認）
}

#[tokio::test]
async fn force_compact_preserves_recent_messages() {
    // compact_keep_recent 分の最新メッセージが保持される
}

#[tokio::test]
async fn force_compact_produces_archive() {
    // アーカイブファイルが生成される
}
```

### GREEN: 実装

`maybe_compact_messages` と同じロジックだが `messages.len() <= max_session_messages` チェックをスキップ。

### コミット

`feat: add force_compact to compaction module`

---

## Step 3: `skills.rs` — `list_skills_formatted()` (TDD)

### RED: テスト先行

```rust
#[test]
fn list_skills_formatted_empty() {
    // スキル0個 → "No skills loaded."
}

#[test]
fn list_skills_formatted_multiple() {
    // スキル2個 → "Available skills:\n- pdf (...)\n- docx (...)"
}
```

### GREEN: 実装

`SkillManager` に `list_skills_formatted() -> String` を追加。

### コミット

`feat: add list_skills_formatted to SkillManager`

---

## Step 4: `slash_commands.rs` — コアモジュール (TDD)

**ファイル**: `egopulse/src/slash_commands.rs` + `egopulse/src/lib.rs`

### API（Microclaw 準拠）

```rust
pub fn is_slash_command(text: &str) -> bool
pub fn unknown_command_response() -> String
pub async fn handle_slash_command(
    state: &AppState,
    chat_id: i64,
    caller_channel: &str,
    command_text: &str,
    sender_id: Option<&str>,
) -> Option<String>
```

### RED: テスト先行

#### `is_slash_command` 判定

| テストケース | 入力 | 期待 |
|---|---|---|
| `is_slash_basic` | `/status` | true |
| `is_slash_with_args` | `/model gpt-5` | true |
| `is_slash_telegram_mention` | `@mybot /status` | true |
| `is_slash_discord_mention` | `<@U123456> /status` | true |
| `is_slash_mention_no_space` | `@bot/status` | true（Microclaw 準拠） |
| `is_slash_plain_text` | `hello world` | false |
| `is_slash_empty` | `""` | false |
| `is_slash_mention_only` | `@bot` | false |
| `is_slash_double_slash` | `// comment` | false（`//` はコードブロック等で誤検出を避ける） |
| `is_slash_case_insensitive` | `/STATUS` | true |

#### `handle_slash_command` — 各コマンド

| テストケース | 入力 | 期待 |
|---|---|---|
| **`/new`** | `/new` | session クリア + "Session cleared" |
| **`/new` クリア確認** | `/new` 後に `load_session` | → None |
| **`/compact` 正常** | `/compact` | "Compacted N messages." |
| **`/compact` 空セッション** | `/compact`（メッセージ0） | エラーにならない |
| **`/status` 表示** | `/status` | "Channel: ...\nProvider: ...\nModel: ...\nSession: ..." |
| **`/status` メッセージ数** | `/status`（12メッセージ） | "12 messages" を含む |
| **`/status` 空セッション** | `/status`（メッセージ0） | "empty" を含む |
| **`/skills` 表示** | `/skills` | "Available skills:\n- ..." |
| **`/skills` スキルなし** | `/skills`（スキル0） | "No skills loaded." |
| **`/restart` systemd** | `/restart`（systemd 環境） | "Restarting via systemctl..." |
| **`/restart` foreground** | `/restart`（非systemd） | "Restarting..." + exit(0) 発火 |
| **`/providers`** | `/providers` | プロバイダー一覧（llm_profile に delegate） |
| **`/provider`** | `/provider` | 現在の provider 表示 |
| **`/provider <name>`** | `/provider openai` | provider 切替 |
| **`/provider reset`** | `/provider reset` | provider リセット |
| **`/models`** | `/models` | モデル一覧 |
| **`/model`** | `/model` | 現在の model 表示 |
| **`/model <name>`** | `/model gpt-5` | model 切替 |
| **`/model reset`** | `/model reset` | model リセット |
| **未知コマンド** | `/foo` | None |
| **空コマンド** | `/` | None |
| **引数付き未知** | `/foo bar baz` | None |

#### エッジケース

| テストケース | 入力 | 期待 |
|---|---|---|
| 前後空白 | `  /status  ` | 正常動作 |
| 大文字小文字混在 | `/Status` | `/status` として処理 |
| 絵文字混じり | `/status 🔧` | `/status` として処理（余剰は無視） |
| メンション後の複数空白 | `@bot   /status` | true + 正常動作 |

### GREEN: 実装

Microclaw `chat_commands.rs` と同じ match dispatch:

```
normalized_slash_command(text)
  ├── "/new"      → clear_session(chat_id)
  ├── "/compact"  → force_compact()
  ├── "/status"   → provider/model/session 情報
  ├── "/skills"   → state.skills.list_skills_formatted()
  ├── "/restart"  → systemctl restart or exit(0)
  ├── "/providers" ─┐
  ├── "/provider"   │
  ├── "/models"     ├→ llm_profile::handle_command() に delegate
  ├── "/model"    ──┘
  └── _           → None
```

`lib.rs` に `pub mod slash_commands;` を追加。

### `/status` の応答（現在の状態を強調）

```
Status
Channel: telegram
Provider: openrouter
Model: gpt-5
Session: active (12 messages)
```

### `/restart` の実装

```
systemd 動作 → systemctl --user restart egopulse
フォアグラウンド → exit(0)（500ms delay で応答メッセージ送信後に終了）
```

### コミット

`feat: add slash_commands module with slash command handler`

---

## Step 5: Telegram チャネル (TDD)

**ファイル**: `egopulse/src/channels/telegram.rs`

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `slash_command_does_not_enter_agent_loop` | `/status` を送信 → `process_turn` が呼ばれない |
| `slash_command_reply_returned` | `/status` を送信 → 応答に "Status" を含む |
| `unknown_slash_command_reply` | `/foo` を送信 → "Unknown command" を含む |
| `non_slash_passes_through` | `hello` を送信 → `process_turn` が呼ばれる |
| `slash_command_with_mention` | `@bot /status` → コマンドとして処理 |

### GREEN: 実装

`handle_message()` の `process_turn()` 呼び出し直前にインターセプトを追加。Microclaw `telegram.rs` L640-693 と同じパターン。

`chat_id` 解決を `process_turn` の前に移動する必要があるため、`resolve_chat_id()` をインターセプト部で先に呼ぶ。

### 5b: Telegram `setMyCommands` 登録

`start_telegram_bot()` 起動時に teloxide の `set_my_commands` でコマンド一覧を BotFather に登録。ユーザーが `/` ボタンを押したときにポップアップ表示される。

### コミット

`feat: intercept slash commands and register bot commands in Telegram`

---

## Step 6: Discord チャネル (TDD)

**ファイル**: `egopulse/src/channels/discord.rs`

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `text_slash_command_does_not_enter_agent_loop` | `/status` テキスト → `process_turn` 呼ばれない |
| `text_slash_command_reply_returned` | `/status` → "Status" 含む応答 |
| `unknown_text_slash_reply` | `/foo` → "Unknown command" |
| `interaction_command_handled` | Application Command `status` → 応答返る |
| `interaction_with_option` | Application Command `model` + option `gpt-5` → model 切替 |
| `interaction_unknown_command` | 未登録の interaction → エラーレスポンス |

### GREEN: 実装

#### 6a: テキストベースのインターセプト

Telegram と同じパターンで `process_turn()` 呼び出し直前に挿入。

#### 6b: Discord Application Commands 登録

`ready()` イベントで serenity の `Command::set_global_commands` でコマンドを一括登録。

コマンド定義:
- `new`, `compact`, `status`, `skills`, `restart` — 引数なし
- `provider` — option: `name` (string, optional), `reset` (boolean, optional)
- `providers` — 引数なし
- `model` — option: `name` (string, optional), `reset` (boolean, optional)
- `models` — 引数なし

#### 6c: Interaction ハンドラ

`EventHandler` に `interaction_create()` を追加。Interaction ペイロードからコマンド名 + オプション引数を抽出し、`slash_commands::handle_slash_command()` に渡す。テキストベースと Application Commands の両方から同じハンドラに到達。

### コミット

`feat: intercept slash commands and register Discord Application Commands`

---

## Step 7: CLI チャットの統合 (TDD)

**ファイル**: `egopulse/src/channels/cli.rs`

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `cli_slash_new_works` | CLI チャットで `/new` → session クリア |
| `cli_slash_status_works` | CLI チャットで `/status` → 情報表示 |
| `cli_slash_model_works` | CLI チャットで `/model gpt-5` → model 切替 |

### GREEN: 実装

現状の `llm_profile::handle_command()` 呼び出しを `slash_commands::handle_slash_command()` に切替。

### コミット

`refactor: unify CLI chat command handling through slash_commands`

---

## Step 8: 動作確認

- `cargo test -p egopulse` — 全テスト通過
- `cargo clippy --all-targets --all-features -- -D warnings` — 警告なし
- `cargo fmt --check` — フォーマット準拠

---

## Step 9: PR 作成

`pr-create` で PR 作成。説明は日本語。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/src/slash_commands.rs` | **新規** | スラッシュコマンドハンドラ（Microclaw 準拠） |
| `egopulse/src/lib.rs` | 変更 | `pub mod slash_commands;` 追加 |
| `egopulse/src/storage.rs` | 変更 | `clear_session()` 追加 + テスト |
| `egopulse/src/agent_loop/compaction.rs` | 変更 | `force_compact()` 追加 + テスト |
| `egopulse/src/skills.rs` | 変更 | `list_skills_formatted()` 追加 + テスト |
| `egopulse/src/channels/telegram.rs` | 変更 | インターセプト + `setMyCommands` 登録 + テスト |
| `egopulse/src/channels/discord.rs` | 変更 | インターセプト + App Commands 登録 + Interaction + テスト |
| `egopulse/src/channels/cli.rs` | 変更 | `llm_profile` → `slash_commands` 切替 + テスト |

---

## コミット分割

1. `feat: add clear_session to Database`
2. `feat: add force_compact to compaction module`
3. `feat: add list_skills_formatted to SkillManager`
4. `feat: add slash_commands module with slash command handler`
5. `feat: intercept slash commands and register bot commands in Telegram`
6. `feat: intercept slash commands and register Discord Application Commands`
7. `refactor: unify CLI chat command handling through slash_commands`

---

## テストケース一覧（全 43 件）

### `storage.rs` (2)
1. `clear_session_deletes_snapshots_and_messages`
2. `clear_session_idempotent_on_empty_chat`

### `compaction.rs` (3)
3. `force_compact_runs_regardless_of_threshold`
4. `force_compact_preserves_recent_messages`
5. `force_compact_produces_archive`

### `skills.rs` (2)
6. `list_skills_formatted_empty`
7. `list_skills_formatted_multiple`

### `slash_commands.rs` — `is_slash_command` (10)
8. `is_slash_basic`
9. `is_slash_with_args`
10. `is_slash_telegram_mention`
11. `is_slash_discord_mention`
12. `is_slash_mention_no_space`
13. `is_slash_plain_text`
14. `is_slash_empty`
15. `is_slash_mention_only`
16. `is_slash_double_slash`
17. `is_slash_case_insensitive`

### `slash_commands.rs` — `handle_slash_command` (21)
18. `handle_new_clears_session`
19. `handle_new_clear_confirm`
20. `handle_compact_success`
21. `handle_compact_empty_session`
22. `handle_status_shows_info`
23. `handle_status_message_count`
24. `handle_status_empty_session`
25. `handle_skills_lists_skills`
26. `handle_skills_no_skills`
27. `handle_restart_systemd`
28. `handle_restart_foreground`
29. `handle_providers`
30. `handle_provider_show`
31. `handle_provider_switch`
32. `handle_provider_reset`
33. `handle_models`
34. `handle_model_show`
35. `handle_model_switch`
36. `handle_model_reset`
37. `handle_unknown_command`
38. `handle_empty_command`

### エッジケース (4)
39. `handle_leading_trailing_whitespace`
40. `handle_case_insensitive`
41. `handle_emoji_after_command`
42. `handle_mention_multiple_spaces`

### Telegram (5)
43. `telegram_slash_does_not_enter_agent_loop`
44. `telegram_slash_reply_returned`
45. `telegram_unknown_slash_reply`
46. `telegram_non_slash_passes_through`
47. `telegram_slash_with_mention`

### Discord (6)
48. `discord_text_slash_does_not_enter_agent_loop`
49. `discord_text_slash_reply_returned`
50. `discord_unknown_text_slash_reply`
51. `discord_interaction_command_handled`
52. `discord_interaction_with_option`
53. `discord_interaction_unknown_command`

### CLI (3)
54. `cli_slash_new_works`
55. `cli_slash_status_works`
56. `cli_slash_model_works`

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | Worktree | 1 min |
| Step 1 | `storage.rs` (TDD) | ~30 行 |
| Step 2 | `compaction.rs` (TDD) | ~40 行 |
| Step 3 | `skills.rs` (TDD) | ~20 行 |
| Step 4 | `slash_commands.rs` (TDD) | ~400 行 |
| Step 5 | Telegram (TDD) | ~40 行 |
| Step 6 | Discord (TDD) | ~120 行 |
| Step 7 | CLI (TDD) | ~20 行 |
| Step 8 | 動作確認 | — |
| Step 9 | PR 作成 | — |
| **合計** | | **~670 行** |
