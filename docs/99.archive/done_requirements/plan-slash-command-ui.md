# Plan: WebUI / Discord スラッシュコマンド UI 実装

Telegram で既に動作している「`/` 押下でコマンド候補がポップアップ表示される UI」を、Discord（ネイティブ Application Commands）と WebUI（React オートコンプリート）にも展開する。併せて、コマンド定義の重複解消のため `CommandDef` レジストリを導入し、全チャネルが単一ソースからコマンドメタデータを参照するようリファクタする。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **Single Source of Truth**: コマンド定義（名前・説明・使用法）は `slash_commands.rs` の `CommandDef` 配列に一元化し、各チャネルは `all_commands()` を通じて参照する。Telegram の `BotCommand` リストや Discord の `CreateCommand` リストの個別ハードコードを排除する
- **Discord ネイティブ優先**: Discord はテキストベースの `/` インターセプトに加え、Discord Application Commands（Interactions API）を登録し、プラットフォーム標準のオートコンプリート UI を提供する。既存のテキストベース処理はフォールバックとして残す
- **WebUI はクライアントサイド完結**: コマンド数が少なく（9個）変更頻度も低いため、フロントエンドにハードコードで定義を持つ。将来的に `GET /api/commands` を追加して動的化してもよいが、Phase 1 では不要
- **既存の `handle_slash_command()` を再利用**: Discord Interaction 受信時も最終的に同じ `handle_slash_command()` に到達するよう、入力を正規化して流す。コマンドのビジネスロジックは一切変更しない
- **Microclaw 互換パターンを維持**: スラッシュコマンドはエージェントループに入らず即座に応答する既存動作を崩さない

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 実装元 |
|---|---|
| `CommandDef` レジストリ + `all_commands()` | `src/slash_commands.rs` |
| Telegram: レジストリからの `set_my_commands` 生成 | `src/channels/telegram.rs` |
| Discord: Application Command 登録 + Interaction ハンドラ | `src/channels/discord.rs` |
| WebUI: `CommandSuggest` コンポーネント | `web/src/components/CommandSuggest.tsx`（新規） |
| WebUI: `Composer` にサジェスト統合 | `web/src/components/Composer.tsx` |
| WebUI: スタイル追加 | `web/src/app.css` |
| コマンド定数 | `web/src/commands.ts`（新規） |
| ドキュメント更新 | `docs/30.egopulse/commands.md` |

---

## Step 0: Worktree 作成

`worktree-create` skill を使用して `feat/slash-command-ui` ブランチの Worktree を作成。

---

## Step 1: CommandDef レジストリ (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `all_commands_returns_all` | `all_commands()` が 9 コマンド（new, compact, status, skills, restart, providers, provider, models, model）を返す |
| `all_commands_has_valid_metadata` | 各 `CommandDef` の `name`, `description`, `usage` が非空で `usage` が `/` で始まる |
| `all_commands_names_are_unique` | 全コマンドの `name` が重複しない |
| `find_command_by_name_known` | `find_command("status")` が対応する `CommandDef` を返す |
| `find_command_by_name_unknown` | `find_command("nonexistent")` が `None` を返す |

### GREEN: 実装

`src/slash_commands.rs` に追加:

```rust
/// コマンド定義のメタデータ。
pub struct CommandDef {
    pub name: &'static str,
    pub description: &'static str,
    pub usage: &'static str,
}

/// 登録済みコマンド一覧を返す。
pub const fn all_commands() -> &'static [CommandDef] {
    &[
        CommandDef { name: "new",       description: "Clear current session",    usage: "/new" },
        CommandDef { name: "compact",   description: "Force compact session",    usage: "/compact" },
        CommandDef { name: "status",    description: "Show current status",      usage: "/status" },
        CommandDef { name: "skills",    description: "List available skills",    usage: "/skills" },
        CommandDef { name: "restart",   description: "Restart the bot",         usage: "/restart" },
        CommandDef { name: "providers", description: "List LLM providers",      usage: "/providers" },
        CommandDef { name: "provider",  description: "Show/switch provider",    usage: "/provider [name]" },
        CommandDef { name: "models",    description: "List models",             usage: "/models" },
        CommandDef { name: "model",     description: "Show/switch model",       usage: "/model [name]" },
    ]
}

/// 名前から CommandDef を検索する。
pub fn find_command(name: &str) -> Option<&'static CommandDef> { ... }
```

既存のテストは `handle_slash_command` のテストなので影響なし。新規テストは `mod tests` 内に追加。

### コミット

`refactor: introduce CommandDef registry for slash command metadata`

---

## Step 2: Telegram: レジストリ参照へのリファクタ (TDD)

前提: Step 1

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `telegram_commands_match_registry` | `telegram.rs` がハードコードではなく `all_commands()` から BotCommand リストを生成することを確認（統合テスト相当） |

※ テストは Step 1 の `all_commands()` で品質担保済み。ここではリファクタ安全性確認のみ。

### GREEN: 実装

`src/channels/telegram.rs:376-394` のハードコード `BotCommand` リストを `all_commands()` からの生成に置換:

```rust
let commands: Vec<BotCommand> = crate::slash_commands::all_commands()
    .iter()
    .map(|c| BotCommand::new(c.name, c.description))
    .collect();
```

### コミット

`refactor: generate Telegram BotCommand list from CommandDef registry`

---

## Step 3: Discord: Application Commands 登録 + Interaction ハンドラ (TDD)

前提: Step 1

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `interaction_command_text_normalizes` | `Interaction::ApplicationCommand` の `data.name` から `"/status"` 形式のテキストを正しく生成できる |
| `interaction_unknown_command_responds` | 登録外コマンド名で unknown 応答が返る |

※ Discord イベントハンドラの直接テストは serenity の構造上困難なため、正規化ロジックを純粋関数として抽出してユニットテストする。Integration 相当のテストは手動確認でカバー。

### GREEN: 実装

`src/channels/discord.rs` を変更:

1. **`ready` ハンドラで Application Commands を一括登録**:

```rust
async fn ready(&self, ctx: Context, ready: Ready) {
    info!("Discord: connected as {}", ready.user.name);

    let commands: Vec<CreateCommand> = crate::slash_commands::all_commands()
        .iter()
        .map(|c| CreateCommand::new(c.name).description(c.description))
        .collect();

    if let Err(e) = Command::set_global_commands(&ctx.http, commands).await {
        warn!("Discord: failed to register slash commands: {e}");
    }
}
```

2. **`interaction_create` ハンドラを追加**:

```rust
async fn interaction_create(&self, ctx: Context, interaction: Interaction) {
    if let Interaction::ApplicationCommand(cmd) = interaction {
        let command_text = format!("/{}", cmd.data.name);
        // 既存の chat_id 解決 → handle_slash_command フローに流す
        // InteractionResponse::ChannelMessageWithSource で応答
    }
}
```

3. **正規化関数を抽出**（ユニットテスト可能）:

```rust
/// Discord Interaction のコマンド名を handle_slash_command が
/// 受け付ける形式（"/command"）に正規化する。
fn interaction_to_command_text(name: &str) -> String {
    format!("/{name}")
}
```

4. **Cargo.toml の serenity features を確認**: `model` feature に `ApplicationCommand`, `Interaction` が含まれているため、feature 追加は不要。

### コミット

`feat(discord): register Discord Application Commands with interaction handler`

---

## Step 4: WebUI: コマンド定数 + CommandSuggest コンポーネント (TDD)

前提: なし（フロントエンドは Rust に依存しない）

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `filterCommands_empty_query` | クエリ空文字で全 9 コマンドが返る |
| `filterCommands_prefix_st` | クエリ `"st"` で `status`, `restart` のみフィルタされる |
| `filterCommands_exact_new` | クエリ `"new"` で `new` のみマッチ |
| `filterCommands_no_match` | クエリ `"xyz"` で空配列 |
| `CommandSuggest renders commands` | コマンドリストが表示される |
| `CommandSuggest highlights active` | 選択中インデックスのアイテムがアクティブ表示 |
| `CommandSuggest empty when no match` | マッチなしで何もレンダリングしない |

※ フロントエンドのテスト手法はプロジェクトの既存テスト（`__tests__/`）に従い Vitest + React Testing Library を使用。

### GREEN: 実装

1. **`web/src/commands.ts`（新規）**:

```typescript
export interface SlashCommand {
  name: string;
  description: string;
  usage: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "new",       description: "Clear current session", usage: "/new" },
  { name: "compact",   description: "Force compact session", usage: "/compact" },
  { name: "status",    description: "Show current status",   usage: "/status" },
  { name: "skills",    description: "List available skills", usage: "/skills" },
  { name: "restart",   description: "Restart the bot",      usage: "/restart" },
  { name: "providers", description: "List LLM providers",   usage: "/providers" },
  { name: "provider",  description: "Show/switch provider", usage: "/provider [name]" },
  { name: "models",    description: "List models",          usage: "/models" },
  { name: "model",     description: "Show/switch model",    usage: "/model [name]" },
];

/** 入力テキストからコマンド候補をフィルタする。"/" は入力済み前提。 */
export function filterCommands(query: string): SlashCommand[] {
  const prefix = query.toLowerCase();
  return SLASH_COMMANDS.filter((c) => c.name.startsWith(prefix));
}
```

2. **`web/src/components/CommandSuggest.tsx`（新規）**:

```tsx
// Props: commands, activeIndex, onSelect
// 表示: コマンド名 + 説明 のリスト。activeIndex のアイテムをハイライト
// キーボード操作は親 Composer で管理し、CommandSuggest は純粋に表示に専念
```

3. **スタイル追加** (`web/src/app.css`):

```css
.command-suggest { /* ポップアップ位置・ボーダー・背景 */ }
.command-suggest-item { /* 各アイテムのパディング・ホバー */ }
.command-suggest-item.active { /* 選択中のハイライト */ }
.command-suggest-item .cmd-name { /* コマンド名（太字） */ }
.command-suggest-item .cmd-desc { /* 説明文（グレイ） */ }
```

### コミット

`feat(web): add CommandSuggest component with command definitions`

---

## Step 5: WebUI: Composer へのサジェスト統合 (TDD)

前提: Step 4

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `Composer shows suggestions on slash` | textarea に `/` を入力すると CommandSuggest が表示される |
| `Composer filters on typing` | `/st` 入力で status, restart のみ表示 |
| `Composer hides on non-slash` | `hello` 入力でサジェスト非表示 |
| `Composer hides on escape` | Escape キーでサジェスト非表示 |
| `Composer selects on tab` | Tab キーで選択中コマンドが textarea に挿入される |
| `Composer navigates with arrows` | ↑↓ キーでアクティブインデックスが移動 |

### GREEN: 実装

`web/src/components/Composer.tsx` を拡張:

- **状態追加**: `showSuggest`, `suggestFilter`, `activeIndex`
- **`onChange` 拡張**: 入力値が `/` で始まる場合にサジェストを表示、それ以外は非表示
- **`onKeyDown` 拡張**: サジェスト表示中のみ以下をハンドル
  - `ArrowUp` / `ArrowDown`: `activeIndex` の移動（ラップアラウンド）
  - `Tab` / `Enter`: 選択中コマンドで `setDraft` を置換
  - `Escape`: `showSuggest` を `false` に
- **レンダー**: `<CommandSuggest>` を textarea 直下に条件付きレンダー
- **キャレット位置**: テキスト全体をコマンドで置換（スラッシュコマンドは行頭入力前提）

### コミット

`feat(web): integrate slash command autocomplete into Composer`

---

## Step 6: 動作確認

- `cargo fmt --check`
- `cargo check -p egopulse`
- `cargo clippy --all-targets --all-features -- -D warnings`
- `cargo test -p egopulse`
- `cd egopulse/web && npm run build`（型エラーなし確認）
- WebUI ブラウザ確認: `/` 入力でサジェスト表示、コマンド選択→送信で正常応答
- Discord 確認: `/` 入力で Discord ネイティブサジェスト表示、コマンド選択で正常応答

---

## Step 7: ドキュメント更新

`docs/30.egopulse/commands.md` の「4.2 実行コンテキスト別の利用可能コマンド」の補足として、Discord Application Commands 登録と WebUI サジェスト対応を追記。

### コミット

`docs: update commands.md with Discord and WebUI slash command UI`

---

## Step 8: PR 作成

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/src/slash_commands.rs` | 変更 | `CommandDef` 構造体 + `all_commands()` + `find_command()` 追加 |
| `egopulse/src/channels/telegram.rs` | 変更 | `set_my_commands` のコマンドリストを `all_commands()` から生成 |
| `egopulse/src/channels/discord.rs` | 変更 | `ready` での Application Command 登録 + `interaction_create` ハンドラ追加 |
| `egopulse/web/src/commands.ts` | **新規** | フロントエンド用コマンド定数 + `filterCommands()` |
| `egopulse/web/src/components/CommandSuggest.tsx` | **新規** | コマンドサジェスト表示コンポーネント |
| `egopulse/web/src/components/Composer.tsx` | 変更 | サジェスト状態管理 + キーボード操作 + CommandSuggest レンダー |
| `egopulse/web/src/app.css` | 変更 | `.command-suggest` 系スタイル追加 |
| `docs/30.egopulse/commands.md` | 変更 | Discord / WebUI のコマンド UI 対応を追記 |

---

## コミット分割

1. `refactor: introduce CommandDef registry for slash command metadata` — `src/slash_commands.rs`
2. `refactor: generate Telegram BotCommand list from CommandDef registry` — `src/channels/telegram.rs`
3. `feat(discord): register Discord Application Commands with interaction handler` — `src/channels/discord.rs`
4. `feat(web): add CommandSuggest component with command definitions` — `web/src/commands.ts`, `web/src/components/CommandSuggest.tsx`, `web/src/app.css`
5. `feat(web): integrate slash command autocomplete into Composer` — `web/src/components/Composer.tsx`
6. `docs: update commands.md with Discord and WebUI slash command UI` — `docs/30.egopulse/commands.md`

---

## テストケース一覧（全 22 件）

### CommandDef レジストリ (5)
1. `all_commands_returns_all` — 9 コマンドが返る
2. `all_commands_has_valid_metadata` — name, description, usage が非空、usage が `/` 始まり
3. `all_commands_names_are_unique` — name の重複なし
4. `find_command_by_name_known` — 既知コマンドの検索成功
5. `find_command_by_name_unknown` — 未知コマンドの検索失敗

### Telegram リファクタ (1)
6. `telegram_commands_match_registry` — BotCommand リストが all_commands() と整合

### Discord Interaction (2)
7. `interaction_command_text_normalizes` — Interaction name → "/command" 形式変換
8. `interaction_unknown_command_responds` — 未知コマンドで unknown 応答

### WebUI: コマンド定数 + CommandSuggest (7)
9. `filterCommands_empty_query` — 空クエリで全コマンド返る
10. `filterCommands_prefix_st` — "st" → status, restart
11. `filterCommands_exact_new` — "new" → new のみ
12. `filterCommands_no_match` — "xyz" → 空
13. `CommandSuggest renders commands` — コマンドリストが表示される
14. `CommandSuggest highlights active` — 選択インデックスのアイテムがアクティブ
15. `CommandSuggest empty when no match` — マッチなしで非表示

### WebUI: Composer 統合 (7)
16. `Composer shows suggestions on slash` — `/` 入力でサジェスト表示
17. `Composer filters on typing` — `/st` でフィルタ
18. `Composer hides on non-slash` — 通常テキストで非表示
19. `Composer hides on escape` — Escape で非表示
20. `Composer selects on tab` — Tab でコマンド挿入
21. `Composer selects on enter` — Enter でコマンド挿入
22. `Composer navigates with arrows` — ↑↓ でインデックス移動

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 1 | CommandDef レジストリ + テスト | ~80 行 |
| Step 2 | Telegram リファクタ + テスト | ~30 行 |
| Step 3 | Discord Application Commands + テスト | ~120 行 |
| Step 4 | WebUI コマンド定数 + CommandSuggest + テスト | ~150 行 |
| Step 5 | Composer 統合 + テスト | ~120 行 |
| Step 7 | ドキュメント更新 | ~20 行 |
| **合計** | | **~520 行** |
