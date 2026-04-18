# Plan: SOUL.md / AGENTS.md ファイル読み込み → System Prompt 注入

EgoPulse に Microclaw 由来の SOUL.md（人格定義）と AGENTS.md（グローバルルール）の読み込み・注入を実装する。複数人格ディレクトリ (`~/.egopulse/souls/`) からの選択機構を含む。ファイルベースの読み込みのみで、メモリツールや構造化メモリは含まない。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **Microclaw の実装をそのまま持ち込む**: `load_soul_content()` / `build_system_prompt()` の構造と注入フォーマット（`<soul>` タグ、# Memories セクション等）、soul 選択の3層フォールバックチェーン（account → channel → global）を Microclaw と同じロジックで実装する。EgoPulse には現状 multi-account 機構がないため `account_id` は常に `None` を渡すが、将来の multi-account 実装時に soul 側のコード変更が不要になるよう、インターフェースは最初から3層対応にする
- **EgoPulse のディレクトリ構成に合わせる**: directory.md で定義済みの配置（`~/.egopulse/SOUL.md`、`~/.egopulse/AGENTS.md`、`runtime/groups/{channel}/{chat_id}/AGENTS.md`）に対応
- **`souls/` は固定**: `~/.egopulse/souls/` を固定パスとし、Config に `souls_dir` フィールドは設けない。Config から変更不可
- **チャネル別 soul 選択をサポート**: `ChannelConfig.soul_path` により、チャネルごとに `souls/` 内の人格ファイルを紐付け可能にする。将来の multi-account に備え、`SoulAgentsLoader.load_soul()` は `account_id: Option<&str>` を受け取る設計にする
- **既存パターンに従う**: `SkillManager` のファイル発見・カタログ注入パターンを参考にする

## Soul 選択のフォールバックチェーン（Microclaw 準拠・3層）

Microclaw の `load_soul_content()` と同じ3層構造を実装する。以下の順序で SOUL を探索し、**最初に見つかったもの**を使用する:

| 優先度 | 探索パス | 指定方法 | 備考 |
|---|---|---|---|
| 1 (最高) | アカウント固有 `soul_path` | 将来 `ChannelConfig.accounts.<id>.soul_path` から。現在は `None` のためスキップ | multi-account 実装時に有効化 |
| 2 | チャネル別 `soul_path` | `ChannelConfig.soul_path`。相対パスなら `souls/` から解決 | 現在有効な最上位レイヤ |
| 3 | `state_root/SOUL.md` | デフォルト人格ファイル | Microclaw と同じ |
| 4 (チャット固有) | `runtime/groups/{channel}/{thread}/SOUL.md` | チャット別人格。見つかった場合 **グローバルを完全に上書き** | Microclaw と同じ |

**現在の動作**: `account_id` は常に `None` が渡されるため、優先度1はスキップされ、実質的に2層（channel → SOUL.md → chat-specific）として動作する。将来 `ChannelConfig` に `accounts` サブ構造と `SurfaceContext` に `account_id` を追加すれば、優先度1が自動的に有効になる。

`ChannelConfig.soul_path` の値が相対パス（例: `"work"`）の場合、`~/.egopulse/souls/work.md` として解決する。絶対パスの場合はそのまま使用。Microclaw の `configured_soul_candidate_paths()` / `read_configured_soul_with_fallback()` と同じパス解決ロジック。

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 実装元 | 備考 |
|---|---|---|
| SOUL.md デフォルトファイル | Microclaw `SOUL.md` の内容をそのまま配置 | `~/.egopulse/SOUL.md` |
| SOUL.md 読み込み | Microclaw `load_soul_content()` | フォールバックチェーン付き |
| 複数人格ディレクトリ | Microclaw `souls/` パターン | `~/.egopulse/souls/` 固定 |
| チャネル別 soul 選択 | Microclaw `soul_path_for_channel()` | `ChannelConfig.soul_path` 追加。3層対応（現状は account 無効） |
| AGENTS.md 読み込み | 新規実装（Microclaw のメモリ読み込みを参考） | global + per-chat |
| System Prompt 注入 | Microclaw `build_system_prompt()` の構造を踏襲 | `<soul>` タグ + # Memories |
| `SoulAgentsLoader` | 新規モジュール | `egopulse/src/soul_agents.rs` |
| `AppState` 拡張 | runtime.rs に `SoulAgentsLoader` を追加 | Arc で保持 |
| Config 拡張 | `ChannelConfig.soul_path` + パスメソッド群 | directory.md 準拠 |

---

## Step 0: Worktree 作成

`worktree-create` skill を使用して `feat/soul-agents-md` ブランチの Worktree を作成。

---

## Step 1: Config 拡張 — パスメソッド + ChannelConfig.soul_path (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `soul_path_returns_state_root_soul_md` | `Config::soul_path()` が `state_root/SOUL.md` を返す |
| `agents_path_returns_state_root_agents_md` | `Config::agents_path()` が `state_root/AGENTS.md` を返す |
| `chat_agents_path_returns_groups_channel_chatid` | `Config::chat_agents_path(channel, thread)` が `runtime/groups/{channel}/{thread}/AGENTS.md` を返す |
| `souls_dir_returns_state_root_souls` | `Config::souls_dir()` が `state_root/souls` を返す |
| `chat_soul_path_returns_groups_channel_chatid` | `Config::chat_soul_path(channel, thread)` が `runtime/groups/{channel}/{thread}/SOUL.md` を返す |
| `channel_soul_path_reads_from_config` | `ChannelConfig.soul_path` に設定された値が読み取れる |
| `channel_soul_path_none_when_unset` | `ChannelConfig.soul_path` が未設定の場合 `None` を返す |

### GREEN: 実装

**Config impl にパスメソッドを追加:**

- `soul_path() -> PathBuf`: `state_root/SOUL.md`
- `agents_path() -> PathBuf`: `state_root/AGENTS.md`
- `souls_dir() -> PathBuf`: `state_root/souls`（固定、Config に `souls_dir` フィールドは追加しない）
- `chat_agents_path(channel: &str, thread: &str) -> PathBuf`: `state_root/runtime/groups/{channel}/{thread}/AGENTS.md`
- `chat_soul_path(channel: &str, thread: &str) -> PathBuf`: `state_root/runtime/groups/{channel}/{thread}/SOUL.md`

既存の `groups_dir()`, `runtime_dir()` を利用して構築。

**ChannelConfig に `soul_path` フィールドを追加:**

```rust
#[derive(Clone, Deserialize, Default)]
pub struct ChannelConfig {
    // ... 既存フィールド
    /// Soul file path for this channel. Relative path resolves from souls/ directory.
    pub soul_path: Option<String>,
}
```

`FileChannelConfig` (Deserialize 用) にも対応するフィールドを追加。

テストは `config.rs` の既存 `#[cfg(test)] mod tests` に追加。

### コミット

`feat(config): add soul/agents path methods and ChannelConfig.soul_path`

---

## Step 2: SoulAgentsLoader モジュール作成 (TDD)

前提: Step 1

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `load_soul_reads_existing_file` | SOUL.md が存在する場合、内容を `Some(content)` で返す |
| `load_soul_returns_none_when_missing` | SOUL.md が存在しない場合、`None` を返す |
| `load_soul_returns_none_for_empty_file` | SOUL.md が空（空白のみ）の場合、`None` を返す |
| `load_agents_reads_existing_file` | AGENTS.md が存在する場合、内容を `Some(content)` で返す |
| `load_agents_returns_none_when_missing` | AGENTS.md が存在しない場合、`None` を返す |
| `load_chat_agents_reads_existing_file` | チャット別 AGENTS.md が存在する場合、内容を `Some` で返す |
| `load_chat_agents_returns_none_when_missing` | チャット別 AGENTS.md が存在しない場合、`None` を返す |
| `load_chat_soul_reads_existing_file` | チャット別 SOUL.md が存在する場合、グローバルを完全上書きして返す |
| `load_chat_soul_returns_none_when_missing` | チャット別 SOUL.md が存在しない場合、`None` を返す |
| `load_soul_from_souls_dir_by_name` | `souls/` ディレクトリ内のファイルを名前指定で読み込める（例: `"work"` → `souls/work.md`） |
| `load_soul_from_souls_dir_with_md_extension` | `"work.md"` 指定でも `souls/work.md` を読み込める |
| `load_soul_from_souls_dir_missing` | `souls/` に該当ファイルがない場合、`None` を返す |
| `resolve_soul_path_absolute_uses_as_is` | 絶対パス指定時はそのまま使用 |
| `resolve_soul_path_relative_resolves_from_souls_dir` | 相対パス `"friendly"` → `souls/friendly.md` に解決 |
| `resolve_soul_path_relative_resolves_from_state_root` | 相対パスで `souls/` にない場合は `state_root` からも探索 |
| `load_soul_prefers_channel_soul_over_default` | チャネル別 `soul_path` が設定されている場合、デフォルト SOUL.md より優先 |
| `load_soul_falls_back_to_default_when_channel_soul_missing` | チャネル別 `soul_path` のファイルが存在しない場合、デフォルトにフォールバック |
| `load_soul_account_path_overrides_channel` | `account_id` あり & accounts 配下に soul_path がある場合、チャネルレベルより優先（将来用） |
| `load_soul_account_path_falls_back_to_channel` | `account_id` ありだが accounts 配下に soul_path がない場合、チャネルレベルにフォールバック |
| `build_soul_section_wraps_in_xml_tags` | SOUL 内容が `<soul>...</soul>` タグでラップされる |
| `build_soul_section_includes_identity_line` | `Your name is EgoPulse. Current channel: {channel}.` が付与される |
| `build_agents_section_formats_memories_header` | AGENTS 内容が `# Memories` セクションヘッダ付きでフォーマットされる |

### GREEN: 実装

新規ファイル `egopulse/src/soul_agents.rs`:

```rust
/// SOUL.md / AGENTS.md の読み込みと system prompt セクション構築。
/// Microclaw の load_soul_content() / build_system_prompt() を踏襲。
pub struct SoulAgentsLoader {
    state_root: PathBuf,
    soul_path: PathBuf,
    agents_path: PathBuf,
    souls_dir: PathBuf,
    groups_dir: PathBuf,
}

impl SoulAgentsLoader {
    pub fn new(config: &Config) -> Self { ... }

    /// SOUL を読み込む。Microclaw の3層フォールバックチェーン:
    /// 1. アカウント別 soul_path (account_id 指定時。将来用。現状は None)
    /// 2. チャネル別 soul_path (ChannelConfig.soul_path → 相対パスは souls/ から解決)
    /// 3. state_root/SOUL.md (デフォルト)
    /// 4. チャット別 SOUL.md (あればグローバルを完全上書き)
    pub fn load_soul(&self, channel: &str, thread: &str, channel_soul_path: Option<&str>, account_id: Option<&str>) -> Option<String>

    /// souls/ ディレクトリから名前指定で読み込み
    /// "work" → souls/work.md, "work.md" → souls/work.md
    pub fn load_soul_by_name(&self, name: &str) -> Option<String>

    /// 相対パスを解決する。Microclaw の configured_soul_candidate_paths() と同じロジック:
    /// - まず souls/ から探す
    /// - 次に state_root から探す
    fn resolve_soul_path(&self, path: &str) -> Vec<PathBuf>

    /// グローバル AGENTS.md を読み込む
    pub fn load_global_agents(&self) -> Option<String>

    /// チャット別 AGENTS.md を読み込む
    pub fn load_chat_agents(&self, channel: &str, thread: &str) -> Option<String>

    /// System prompt 用の <soul> セクションを構築
    /// Microclaw 準拠: <soul>{content}</soul> + identity line
    pub fn build_soul_section(&self, content: &str, channel: &str) -> String

    /// System prompt 用の # Memories セクションを構築
    /// global_agents + chat_agents を結合
    pub fn build_agents_section(&self, channel: &str, thread: &str) -> Option<String>
}
```

Microclaw の注入フォーマットを踏襲:

```
<soul>
{SOUL.md の内容}
</soul>

Your name is EgoPulse. Current channel: {channel}.
```

```
# Memories

<agents>
{グローバル AGENTS.md の内容}
</agents>

<chat-agents>
{チャット別 AGENTS.md の内容}
</chat-agents>
```

### コミット

`feat(egopulse): add SoulAgentsLoader with soul selection fallback chain`

---

## Step 3: AppState へ統合 (TDD)

前提: Step 2

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `build_app_state_contains_soul_agents_loader` | `build_app_state()` 後に `state.soul_agents` が初期化されている |
| `soul_agents_loader_uses_config_paths` | loader が config のパスを正しく使用している |

### GREEN: 実装

`runtime.rs` の `AppState` に `soul_agents: Arc<SoulAgentsLoader>` を追加し、`build_app_state_with_path()` で初期化。

```rust
pub struct AppState {
    // ... 既存フィールド
    pub soul_agents: Arc<SoulAgentsLoader>,
}
```

### コミット

`feat(runtime): integrate SoulAgentsLoader into AppState`

---

## Step 4: build_system_prompt 拡張 (TDD)

前提: Step 3

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `system_prompt_contains_soul_section_when_file_exists` | SOUL.md が存在する場合、`<soul>` タグが含まれる |
| `system_prompt_uses_default_identity_when_no_soul` | SOUL.md がない場合、既存のハードコード identity を使用 |
| `system_prompt_contains_agents_section_when_file_exists` | AGENTS.md が存在する場合、`# Memories` セクションが含まれる |
| `system_prompt_no_agents_section_when_no_files` | SOUL.md も AGENTS.md もない場合、これらのセクションが出現しない |
| `system_prompt_order_soul_before_identity` | SOUL セクションが identity rules より前に来る |
| `system_prompt_order_agents_before_skills` | Memories セクションが Skills セクションより前に来る |
| `system_prompt_chat_agents_included` | チャット別 AGENTS.md が存在する場合、global + chat 両方が含まれる |
| `system_prompt_chat_soul_overrides_global` | チャット別 SOUL.md が存在する場合、グローバルの代わりに使われる |
| `system_prompt_channel_soul_from_config` | `ChannelConfig.soul_path` に設定された人格が使われる |
| `system_prompt_channel_soul_fallback_to_default` | チャネル soul_path が設定されていない場合、デフォルト SOUL.md が使われる |
| `system_prompt_account_soul_overrides_channel` | account_id があり accounts 配下に soul_path がある場合、チャネルレベルより優先（将来用） |

### GREEN: 実装

`turn.rs` の `build_system_prompt()` を拡張。Microclaw の `build_system_prompt()` と同じセクション順序にする:

```
1. <soul> SOUL.md 内容 </soul> + identity line  ← 追加
2. Identity rules + Capabilities (既存)
3. # Memories (AGENTS.md 内容)                    ← 追加
4. # Agent Skills (既存)
```

`build_system_prompt()` に `SoulAgentsLoader` を渡し、`channel` / `thread` に基づいて適切な SOUL と AGENTS を読み込む。

チャネル別 `soul_path` の取得: `state.config.channels.get(channel).and_then(|c| c.soul_path.as_deref())`

### コミット

`feat(agent-loop): inject SOUL.md and AGENTS.md into system prompt`

---

## Step 5: デフォルト SOUL.md プロビジョニング

前提: Step 1–4

### 実装

Microclaw の `SOUL.md` をそのまま `~/.egopulse/SOUL.md` に配置する仕組みを実装。

バイナリに `include_str!` で埋め込み、`build_app_state` のタイミングでファイルが存在しなければ書き出す。既存ファイルは上書きしない。

追加テスト:

| テストケース | 内容 |
|---|---|
| `default_soul_content_matches_microclaw` | 埋め込み内容が Microclaw SOUL.md と一致する |
| `write_default_soul_creates_file_when_missing` | ファイル不在時に書き出される |
| `write_default_soul_does_not_overwrite_existing` | 既存ファイルは上書きしない |

### コミット

`feat(egopulse): embed and provision default SOUL.md on first run`

---

## Step 6: 動作確認

- `cargo test -p egopulse` 全テスト通過
- `cargo fmt --check` フォーマット確認
- `cargo check -p egopulse` 型チェック
- `cargo clippy --all-targets --all-features -- -D warnings` lint

---

## Step 7: PR 作成

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/src/soul_agents.rs` | **新規** | SOUL.md / AGENTS.md 読み込み・soul 選択・セクション構築 |
| `egopulse/src/config.rs` | 変更 | パスアクセサメソッド追加 + `ChannelConfig.soul_path` 追加 + テスト追加 |
| `egopulse/src/runtime.rs` | 変更 | `AppState` に `SoulAgentsLoader` 追加 |
| `egopulse/src/agent_loop/turn.rs` | 変更 | `build_system_prompt()` 拡張 + テスト追加 |
| `egopulse/src/lib.rs` | 変更 | `soul_agents` モジュール登録 |

---

## コミット分割

1. `feat(config): add soul/agents path methods and ChannelConfig.soul_path` — config.rs
2. `feat(egopulse): add SoulAgentsLoader with soul selection fallback chain` — soul_agents.rs, lib.rs
3. `feat(runtime): integrate SoulAgentsLoader into AppState` — runtime.rs
4. `feat(agent-loop): inject SOUL.md and AGENTS.md into system prompt` — turn.rs
5. `feat(egopulse): embed and provision default SOUL.md on first run` — soul_agents.rs (default content)

---

## テストケース一覧（全 41 件）

### Config パスアクセサ + ChannelConfig (7)
1. `soul_path_returns_state_root_soul_md`
2. `agents_path_returns_state_root_agents_md`
3. `chat_agents_path_returns_groups_channel_chatid`
4. `souls_dir_returns_state_root_souls`
5. `chat_soul_path_returns_groups_channel_chatid`
6. `channel_soul_path_reads_from_config`
7. `channel_soul_path_none_when_unset`

### SoulAgentsLoader (22)
8. `load_soul_reads_existing_file`
9. `load_soul_returns_none_when_missing`
10. `load_soul_returns_none_for_empty_file`
11. `load_agents_reads_existing_file`
12. `load_agents_returns_none_when_missing`
13. `load_chat_agents_reads_existing_file`
14. `load_chat_agents_returns_none_when_missing`
15. `load_chat_soul_reads_existing_file`
16. `load_chat_soul_returns_none_when_missing`
17. `load_soul_from_souls_dir_by_name`
18. `load_soul_from_souls_dir_with_md_extension`
19. `load_soul_from_souls_dir_missing`
20. `resolve_soul_path_absolute_uses_as_is`
21. `resolve_soul_path_relative_resolves_from_souls_dir`
22. `resolve_soul_path_relative_resolves_from_state_root`
23. `load_soul_prefers_channel_soul_over_default`
24. `load_soul_falls_back_to_default_when_channel_soul_missing`
25. `load_soul_account_path_overrides_channel`
26. `load_soul_account_path_falls_back_to_channel`
27. `build_soul_section_wraps_in_xml_tags`
28. `build_soul_section_includes_identity_line`
29. `build_agents_section_formats_memories_header`

### AppState 統合 (2)
30. `build_app_state_contains_soul_agents_loader`
31. `soul_agents_loader_uses_config_paths`

### System Prompt 注入 (11)
32. `system_prompt_contains_soul_section_when_file_exists`
33. `system_prompt_uses_default_identity_when_no_soul`
34. `system_prompt_contains_agents_section_when_file_exists`
35. `system_prompt_no_agents_section_when_no_files`
36. `system_prompt_order_soul_before_identity`
37. `system_prompt_order_agents_before_skills`
38. `system_prompt_chat_agents_included`
39. `system_prompt_chat_soul_overrides_global`
40. `system_prompt_channel_soul_from_config`
41. `system_prompt_channel_soul_fallback_to_default`
42. `system_prompt_account_soul_overrides_channel`

### デフォルト SOUL.md プロビジョニング (3)
43. `default_soul_content_matches_microclaw`
44. `write_default_soul_creates_file_when_missing`
45. `write_default_soul_does_not_overwrite_existing`

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 1 | Config パスアクセサ + ChannelConfig.soul_path | ~50 行 |
| Step 2 | SoulAgentsLoader モジュール（3層 soul 選択チェーン付き） | ~300 行 |
| Step 3 | AppState 統合 | ~30 行 |
| Step 4 | build_system_prompt 拡張 | ~90 行 |
| Step 5 | デフォルト SOUL.md プロビジョニング | ~50 行 |
| **合計** | | **~500 行** |
