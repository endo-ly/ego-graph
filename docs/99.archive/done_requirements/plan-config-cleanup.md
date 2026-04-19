# Plan: EgoPulse Config 責務整理リファクタ

`config.rs`（1456行の God module）をデータフローに沿ったサブモジュールに分割し、dead code である `config_store.rs` を廃止し、setup との validation 重複を解消する。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **データフローに従う**: 設定のライフサイクル `Read (file → raw) → Transform (normalize + validate + env) → Use (resolve + paths) → Write (serialize + lock)` に沿ってモジュールを分ける。機能別ではなくライフサイクル別
- **型で不正状態を表現不可にする**: `ProviderId`, `ChannelName` の newtype で文字列の取り違えを防ぐ。raw（入力用・`Option` 多用）と実行時型（不変条件あり）を分離する
- **実行時型は Deserialize しない**: `Config` は `Deserialize` を導出せず、`loader` パイプライン経由でのみ構築する。`From`/`Into` ではなく明示的な builder 関数で変換する
- **Dead code は容赦なく消す**: `config_store.rs` は誰からも使われていない。重複する `CONFIG_WRITE_LOCK` / `acquire_config_lock` / `write_yaml_atomically` ごと廃止する
- **Public API は変えない**: `use crate::config::{Config, ChannelConfig, ...}` の外部参照パスは `mod.rs` の re-export で維持し、呼び出し側（19ファイル）に変更を波及させない

## 参考実装（Rust OSS）

本 Plan の設計は以下の OSS プロジェクトのパターンを参考にしている:

| プロジェクト | パターン | 参考点 |
|---|---|---|
| **ruff** (astral-sh) | Options → Configuration → Settings の 3 層 | 「ファイル入力（Option 前提）→ 中間表現（結合・正規化）→ 実行時型（不変条件あり）」の分離。Settings は `Deserialize` しない |
| **agentgateway** | RawConfig → Config + free function 変換 | Raw 型は private、実行時型のみ public。変換はモジュールレベルの自由関数 |
| **pgdog** | ドメイン別サブモジュール + private Raw 型 | 各ファイル内に private な `Raw*` 型を定義し、`deserialize_optional` でカプセル化 |

コミュニティコンセンサス（[Rust Users Forum](https://users.rust-lang.org/t/config-loading-and-transformation-patterns/125087)）:
> *"アプリケーションドメインと設定ドメインの密結合を避ける。設定型をそのままアプリ全体で使わず、一度ロードしてランタイム設定に変換する。"*

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 現状 | 変更 |
|---|---|---|
| `src/config.rs` (1456行) | God module | データフロー沿い `src/config/` サブモジュール（4ファイル）に分割 |
| `src/config_store.rs` (130行) | Dead code。`#![allow(dead_code)]` 付き | **削除** |
| `src/lib.rs` | `pub mod config; pub mod config_store;` | `pub mod config;` のみに変更 |
| `src/setup/summary.rs` | `validate_fields()` が config.rs の validation と重複 | config 側の validation に委譲 |
| `docs/30.egopulse/config.md` | 設定仕様書 | リファクタ後のモジュール構成を追記 |

---

## Step 0: Worktree 作成

`worktree-create` skill を使用して `refactor/156-config-cleanup` ブランチで Worktree を作成する。

---

## Step 1: config_store.rs 削除

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `cargo test` 全通過 | 削除後に既存テストが全て通ることを確認 |

### GREEN: 実装

1. `src/config_store.rs` を削除
2. `src/lib.rs` から `pub mod config_store;` を削除
3. `cargo check` / `cargo test` でコンパイル・テスト通過を確認

### コミット

`refactor: remove dead config_store module`

---

## Step 2: config.rs → config/ サブモジュールへの分割

**この Step は行の移動のみ。ロジックの変更・newtype の導入はしない。** コンパイルが通る最小の分割を行い、後続 Step で美しくしていく。

### 分割後の構成

```
src/config/
├── mod.rs       # 型定義 + ファサード: Config, ProviderConfig, ChannelConfig, ResolvedLlmConfig,
│                 #   ProviderId, ChannelName, re-export, テスト
├── loader.rs    # Read + Transform: FileConfig(private), normalize, validate, env overlay, build_config
├── persist.rs   # Write: save_yaml, SerializableConfig(private), atomic write, CONFIG_WRITE_LOCK
└── resolve.rs   # Use: LLM解決, channel accessor, パス導出, default_config_path, default_state_root
```

### 各モジュールの責務

**`mod.rs`** (~200行) — 型定義 + 公開ファサード
- `Config`, `ProviderConfig`, `ChannelConfig`, `ResolvedLlmConfig` の構造体定義
- `ProviderId`, `ChannelName` newtype（`Display`, `Debug`, `Clone`, `Hash`, `Eq`, `Borrow<str>`）
- `Debug` 実装（秘匿値のマスク）、`PartialEq`/`Eq`（`ResolvedLlmConfig`）
- `pub mod loader; pub mod persist; pub mod resolve;`
- `pub use` re-export で外部 API を維持
- `Config::load`, `Config::load_allow_missing_api_key` の thin wrapper（loader に委譲）
- `#[cfg(test)] mod tests`（既存テスト）

**`loader.rs`** (~350行) — Read + Transform
- `FileConfig`, `FileProviderConfig`（private, Deserialize 専用）
- `build_config`, `read_file_config` — 読込パイプライン
- `normalize_channels`, `normalize_provider_map`, `normalize_string`, `first_non_empty`
- `validate_base_url`, `validate_compaction_config`, `validate_channel_provider_references`
- `apply_web_channel_env_overrides`, `apply_channel_bot_token_env_override`, `env_var`
- `is_local_url`, `base_url_allows_empty_api_key`, `parse_bool`

**`persist.rs`** (~130行) — Write
- `SerializableConfig`, `SerializableProvider`, `SerializableChannel`（private, Serialize 専用）
- `From<&Config> for SerializableConfig` 変換
- `save_yaml`, `write_atomically`, `acquire_config_lock`
- `CONFIG_WRITE_LOCK`

**`resolve.rs`** (~200行) — Use
- `resolve_global_llm`, `resolve_llm_for_channel`, `effective_provider_name`
- channel accessor: `web_enabled`, `web_host`, `web_port`, `web_auth_token`, `web_allowed_origins`, `channel_enabled`
- `discord_bot_token`, `telegram_bot_token`, `telegram_bot_username`
- `global_provider`
- パス導出: `skills_dir`, `user_skills_dir`, `workspace_dir`, `runtime_dir`, `db_path`, `assets_dir`, `groups_dir`, `soul_path`, `agents_path`, `souls_dir`, `chat_agents_path`, `chat_soul_path`, `status_json_path`
- `default_config_path`, `default_state_root`, `default_workspace_dir`

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| 既存 16 テスト全通過 | テストが mod.rs に移動しても通ること |
| `cargo check` | 全呼び出し側の `use crate::config::*` が壊れないこと |

### GREEN: 実装

1. `src/config.rs` を削除し `src/config/` ディレクトリを作成
2. 各モジュールにコードを切り出し
3. `mod.rs` で `pub use` re-export を設定
4. `cargo check` → `cargo test` → `cargo clippy` で確認

### コミット

`refactor: split config module into lifecycle-based submodules`

---

## Step 3: Newtype 導入（ProviderId, ChannelName）

文字列の取り違えを型レベルで防ぐ。`HashMap<String, ProviderConfig>` → `HashMap<ProviderId, ProviderConfig>` にする。

### newtype の仕様

- `ProviderId`: 小文字正規化済みのプロバイダー識別子。`From<&str>` で小文字化+trim。`Display`, `Debug`, `Clone`, `Hash`, `Eq`, `PartialEq`, `Borrow<str>` を導出
- `ChannelName`: 小文字正規化済みのチャネル名。同じく `Display` 等を導出

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `provider_id_normalizes_case` | `"OpenAI"` → `ProviderId("openai")` |
| `channel_name_trims_whitespace` | `" Web "` → `ChannelName("web")` |
| 既存 26 テスト全通過 | newtype 導入後も既存テストが壊れないこと |

### GREEN: 実装

1. `mod.rs` に `ProviderId`, `ChannelName` を定義
2. `Config.providers`, `Config.channels` のキー型を変更
3. `loader.rs` の正規化で newtype を生成
4. `resolve.rs` の参照解決で newtype を利用
5. `persist.rs` の `From` 実装で newtype を展開

### コミット

`refactor: introduce ProviderId and ChannelName newtypes`

---

## Step 4: ChannelConfig の Deserialize 剥奪

現状 `ChannelConfig` は `Deserialize` を持っているため、YAML から直接構築できてしまい、loader の検証をバイパス可能。raw 側だけが `Deserialize` し、実行時型は loader でのみ構築する。

### 変更点

- `ChannelConfig` から `#[derive(Deserialize)]` を除去
- `loader.rs` に private な `FileChannelConfig`（Deserialize 付き）を定義
- `loader.rs` で `FileChannelConfig` → `ChannelConfig` の変換を行う
- 同様に `ProviderConfig` も `Deserialize` を外し、`FileProviderConfig`（既存）からのみ構築

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| 既存 26 テスト全通過 | 分離後もテストが壊れないこと |
| `cargo check` | 全呼び出し側がコンパイル通ること |

### GREEN: 実装

1. `ChannelConfig` から `Deserialize` を除去
2. `loader.rs` に `FileChannelConfig` を定義
3. `loader.rs` の `normalize_channels` を更新
4. `ProviderConfig` も同様に `Deserialize` を外す

### コミット

`refactor: prevent direct deserialization of runtime config types`

---

## Step 5: setup/summary.rs の validation 重複解消

### 現状の重複

- `summary.rs::validate_fields()` — Provider, URL, API key, channel token の検証
- `config/loader.rs::build_config()` — `normalize_provider_map`, `validate_*` で同種の検証

### 方針

`config/loader.rs` に setup からも使える粒度の validation 関数を `pub` で公開し、`summary.rs` から呼び出す。

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| 既存 10 setup テスト全通過 | setup 側のテストが壊れないこと |
| `validate_base_url_rejects_invalid` | 共有 validation が不正 URL を拒否 |
| `validate_enabled_channel_requires_token` | enabled channel の token 必須チェック |

### GREEN: 実装

1. `config/loader.rs` の validation 関数を `pub` に変更（`validate_base_url`, `is_local_url`, `base_url_allows_empty_api_key` 等）
2. `setup/summary.rs::validate_fields()` から `config::loader` の関数を呼ぶように変更
3. 重複ロジックを削除

### コミット

`refactor: deduplicate validation between config and setup`

---

## Step 6: 動作確認

```bash
cd egopulse
cargo fmt --check
cargo check -p egopulse
cargo clippy --all-targets --all-features -- -D warnings
cargo test -p egopulse
```

---

## Step 7: docs 更新

`docs/30.egopulse/config.md` の最後に、新しいモジュール構成（データフロー図 + 各モジュールの責務）を追記する。

### コミット

`docs: add module architecture to config documentation`

---

## Step 8: PR 作成

```bash
gh pr create --title "refactor(egopulse): config module responsibility cleanup (#156)" --body "..."
```

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/src/config.rs` | **削除** | サブモジュールに分割 |
| `egopulse/src/config/mod.rs` | **新規** | 型定義 + ファサード + re-export + テスト |
| `egopulse/src/config/loader.rs` | **新規** | 読込パイプライン + 正規化 + env overlay + validation |
| `egopulse/src/config/persist.rs` | **新規** | 永続化 + SerializableConfig(private) + atomic write |
| `egopulse/src/config/resolve.rs` | **新規** | LLM解決 + channel accessor + パス導出 |
| `egopulse/src/config_store.rs` | **削除** | Dead code 廃止 |
| `egopulse/src/lib.rs` | 変更 | `config_store` mod 宣言削除 |
| `egopulse/src/setup/summary.rs` | 変更 | validation を config::loader に委譲 |
| `docs/30.egopulse/config.md` | 変更 | モジュール構成追記 |

---

## コミット分割

1. `refactor: remove dead config_store module`
2. `refactor: split config module into lifecycle-based submodules`
3. `refactor: introduce ProviderId and ChannelName newtypes`
4. `refactor: prevent direct deserialization of runtime config types`
5. `refactor: deduplicate validation between config and setup`
6. `docs: add module architecture to config documentation`

---

## テストケース一覧（全 31 件）

### config::tests — 移行確認 (16)
1. `home_directory_unresolved_error_displays_correctly` — エラー表示確認
2. `loads_provider_based_config` — provider ベース設定の読込
3. `allows_missing_api_key_for_local_provider` — local provider の API key 省略
4. `rejects_missing_remote_api_key` — remote provider の API key 必須
5. `rejects_unknown_channel_provider` — 不正 provider 参照の拒否
6. `load_allow_missing_api_key_accepts_incomplete_remote_provider` — setup 用緩和ロード
7. `default_model_in_yaml_overrides_provider_default` — グローバルモデルオーバーライド
8. `default_model_falls_back_to_provider_default` — provider デフォルトへのフォールバック
9. `soul_path_returns_state_root_soul_md` — SOUL.md パス
10. `agents_path_returns_state_root_agents_md` — AGENTS.md パス
11. `chat_agents_path_returns_groups_channel_chatid` — チャット別 AGENTS.md
12. `souls_dir_returns_state_root_souls` — souls ディレクトリ
13. `chat_soul_path_returns_groups_channel_chatid` — チャット別 SOUL.md
14. `channel_soul_path_reads_from_config` — チャネル soul_path 読込
15. `channel_soul_path_none_when_unset` — soul_path 未設定時
16. `model_resolution_chain_channel_overrides_global` — モデル解決チェーン

### setup::tests — 回帰確認 (7)
17. `load_existing_config_prefers_new_provider_schema` — 新スキーマ読込
18. `load_existing_config_ignores_legacy_top_level_llm_fields` — 旧スキーマ無視
19. `filtered_items_returns_all_when_filter_empty` — フィルタ空時の全件返却
20. `filtered_items_matches_substring_case_insensitive` — 大小文字無視フィルタ
21. `filtered_items_returns_none_when_no_match` — マッチなし時の空
22. `setup_mode_navigate_default` — 初期モード Navigate
23. `selector_state_holds_original_value` — セレクター状態保持

### setup::provider::tests — 回帰確認 (3)
24. `provider_selector_items_includes_key_presets` — キープリセット含む
25. `model_selector_items_returns_models_for_known_provider` — 既知 provider のモデル
26. `model_selector_items_returns_empty_for_unknown_provider` — 未知 provider の空

### newtypes — 新規 (2)
27. `provider_id_normalizes_case` — `"OpenAI"` → `ProviderId("openai")` への正規化
28. `channel_name_trims_whitespace` — `" Web "` → `ChannelName("web")` への正規化

### validation — 新規 (3)
29. `validate_base_url_rejects_invalid` — shared validation が不正 URL 拒否
30. `validate_enabled_channel_requires_token` — enabled channel の token 必須チェック
31. `validate_base_url_accepts_valid` — 有効 URL を通す

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | Worktree 作成 | ~5 行 |
| Step 1 | config_store.rs 削除 | ~5 行（削除のみ） |
| Step 2 | config.rs → config/ 物理分割 | ~1500 行（移動） |
| Step 3 | newtype 導入 | ~100 行 |
| Step 4 | Deserialize 剥奪 | ~80 行 |
| Step 5 | validation 重複解消 | ~60 行 |
| Step 6 | 動作確認 | ~0 行 |
| Step 7 | docs 更新 | ~40 行 |
| **合計** | | **~1790 行** |
