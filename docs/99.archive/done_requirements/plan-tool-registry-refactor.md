# Plan: ToolRegistry と MCP の責務境界を整理する (Provider Trait 抽象化)

`ToolRegistry` が抱える MCP 依存を除去し、`McpToolAdapter` を経由して built-in / MCP を統一的に扱うリファクタリング。Close #157

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **Adapter パターン**: MCP tool を `Tool` trait 実装にラップする `McpToolAdapter` を導入。Registry は MCP の存在を知らない
- **Sanitizer 独立**: 秘匿情報マスキングを `tools/sanitizer.rs` に分離し、単独テスト可能にする
- **AppState 直接保持**: `McpManager` への参照は `ToolRegistry` 経由ではなく `AppState` が直接持つ（status snapshot 用）
- **既存 Tool trait 変更なし**: `Tool` trait のシグネチャは変更せず、adapter が実装する。既存 built-in tool は一切修正不要
- **後方互換ハックなし**: 旧 `set_mcp_manager()` / `mcp_manager()` は削除し、新仕様へ一直線に置き換える

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 実装元 |
|---|---|
| Sanitizer モジュール | `tools/mod.rs` から抽出 |
| McpToolAdapter | 新規実装 |
| ToolRegistry | `mcp_manager` フィールド・分岐ロジック削除 |
| McpManager | `create_tool_adapters()` 追加、`is_mcp_tool()` 削除 |
| AppState (runtime.rs) | `mcp_manager` フィールド追加、初期化順序変更 |
| テストコード | sanitizer / adapter / registry 各テスト |
| ドキュメント | tools.md / mcp.md |

---

## Step 0: Worktree 作成

`worktree-create` skill で `refactor/tool-registry-provider-trait` WT を作成。

---

## Step 1: Sanitizer 抽出 (TDD)

前提: なし

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_redact_secrets_replaces_config_values` | Config 由来の secret 値を `[REDACTED:key]` に置換 |
| `test_redact_secrets_empty_list_noop` | secrets が空なら入力をそのまま返す |
| `test_redact_secrets_longer_first` | より長い secret を先に置換し、短い方で誤マッチしない |
| `test_redact_known_patterns_openai` | `sk-` プレフィクスの secret を検出してマスキング |
| `test_redact_known_patterns_multiple` | 1 行に複数の secret パターンがあっても全てマスキング |
| `test_redact_known_patterns_no_false_positive` | `sk-` が単語の途中にあればマスキングしない |
| `test_sanitize_output_string_both_layers` | config secrets + known patterns の両方が適用される |
| `test_sanitize_json_value_nested` | ネストした JSON 内の String 値もマスキングされる |
| `test_sanitize_tool_result_applies_to_all_fields` | content / llm_content / details 全フィールドがサニタイズされる |
| `test_sanitize_message_content_parts` | MessageContent::Parts の InputText / InputImage もサニタイズ |
| `test_collect_config_secrets_extracts_api_keys` | Config の provider API keys を抽出 |
| `test_collect_config_secrets_extracts_auth_tokens` | Config の channel auth tokens を抽出 |

### GREEN: 実装

`tools/sanitizer.rs` を新規作成し、`tools/mod.rs` から以下を移動:

- `SECRET_PATTERNS` 定数
- `redact_secrets()`
- `redact_known_secret_patterns()`
- `sanitize_output_string()`
- `sanitize_message_content()`
- `sanitize_json_value()`
- `sanitize_tool_result()`
- `collect_config_secrets()`

`tools/mod.rs` から `pub(crate) use sanitizer::*;` で再エクスポート。既存の呼び出し元は変更不要。

### コミット

`refactor: extract sanitizer module from tools/mod.rs`

---

## Step 2: McpToolAdapter 実装 (TDD)

前提: なし（Step 1 と独立）

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_adapter_name_matches_sanitized` | adapter の name() が `mcp_{server}_{tool}` 形式 |
| `test_adapter_definition_converts_schema` | MCP schema → ToolDefinition への変換が正しい |
| `test_adapter_execute_success` | 正常な MCP tool 実行 → ToolResult::success |
| `test_adapter_execute_empty_output` | MCP が空レスポンス → `(no output)` 文字列 |
| `test_adapter_execute_server_not_found` | server index 不正 → ToolResult::error |
| `test_adapter_execute_timeout` | timeout 発生 → ToolResult::error に timeout 文言 |
| `test_adapter_execute_non_object_input` | JSON object 以外の入力 → ToolResult::error |
| `test_adapter_execute_formats_text_content` | MCP Text content → そのまま文字列 |
| `test_adapter_execute_formats_image_content` | MCP Image content → `[image: ...]` |
| `test_adapter_execute_formats_resource_content` | MCP Resource content → `resource: ...` / `blob: ...` |
| `test_mcp_manager_create_adapters_count` | adapter 数 = 全 server の全 tool 数 |
| `test_mcp_manager_create_adapters_skips_collisions` | 名前衝突 tool は adapter 生成から除外 |

### GREEN: 実装

`tools/mcp_adapter.rs` を新規作成。

`McpToolAdapter` 構造体:
- `name`: sanitize 済み tool 名
- `original_name`: MCP server 上の元の tool 名
- `server_idx`: server インデックス
- `timeout`: 要求タイムアウト
- `definition`: キャッシュ済み ToolDefinition
- `manager`: `Arc<RwLock<McpManager>>`

`Tool` trait を実装:
- `name()` → 保持する name を返す
- `definition()` → 保持する ToolDefinition を返す
- `execute()` → `manager.read().await.execute_tool(server_idx, original_name, timeout, input)` を呼び出し、結果を ToolResult に変換

McpManager 側に `create_tool_adapters()` メソッドを追加:
- 各 ConnectedServer の各 cached_tool に対し McpToolAdapter を生成
- 名前衝突 tool はスキップ（既存の warn ログと同じロジック）

### コミット

`feat: add McpToolAdapter implementing Tool trait`

---

## Step 3: ToolRegistry 簡素化 + AppState 更新 (TDD)

前提: Step 1, Step 2

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_registry_definitions_returns_all_tools` | built-in + adapter 登録後に全定義が返る |
| `test_registry_execute_builtin_tool` | built-in tool が正しく実行される（MCP 分岐なし） |
| `test_registry_execute_adapter_tool` | McpToolAdapter 経由で MCP tool が実行される |
| `test_registry_execute_unknown_tool` | 未登録 tool 名 → error result |
| `test_registry_no_mcp_field` | mcp_manager / set_mcp_manager が存在しない（コンパイル確認） |
| `test_appstate_has_mcp_manager` | AppState が mcp_manager フィールドを持つ |
| `test_build_app_state_registers_adapters` | build_app_state で adapter が register_tool される |
| `test_status_snapshot_uses_appstate_mcp` | status snapshot が AppState.mcp_manager を参照 |

### GREEN: 実装

**ToolRegistry (`tools/mod.rs`)**:
- `mcp_manager` フィールド削除
- `set_mcp_manager()` 削除
- `mcp_manager()` 削除
- `definitions()` / `definitions_async()` から MCP 分岐を削除（`self.tools.iter()` のみ）
- `execute()` から MCP 分岐を削除（`self.tools.iter()` のみ）

**AppState (`runtime.rs`)**:
- `mcp_manager: Option<Arc<RwLock<McpManager>>>` フィールド追加
- `build_app_state()`:
  1. `ToolRegistry::new()` 作成
  2. `McpManager::new()` 作成
  3. `mcp_manager.create_tool_adapters()` → adapters 取得
  4. 各 adapter を `registry.register_tool()` で登録
  5. `AppState { ..., mcp_manager: Some(Arc::new(RwLock::new(mcp_manager))) }` に格納
- `write_startup_status()`: `state.tools.mcp_manager()` → `state.mcp_manager` に変更

**McpManager (`mcp.rs`)**:
- `is_mcp_tool()` 削除（adapter が直接 server_idx を保持するため不要）

**Clone impl (`runtime.rs`)**:
- `mcp_manager` の clone 処理を追加

### コミット

```
refactor: remove MCP awareness from ToolRegistry
refactor: move mcp_manager to AppState for direct access
```

---

## Step 4: テストコード修正 (TDD)

前提: Step 3

### RED → GREEN: テスト修正

既存テストのうち、`set_mcp_manager()` や `mcp_manager()` を使用している箇所を修正:

| ファイル | 修正内容 |
|---|---|
| `tools/mod.rs` テスト | `set_mcp_manager()` 呼び出しを削除（MCP テストは Step 2 でカバー） |
| `agent_loop/session.rs` テスト | `ToolRegistry::new()` 呼び出しはそのまま、MCP 関連は削除 |
| `agent_loop/turn.rs` テスト | 同上 |

### コミット

`test: update existing tests for new ToolRegistry API`

---

## Step 5: ドキュメント更新

### 実装

- `docs/30.egopulse/tools.md`:
  - Tool Registry セクション更新（MCP 特別扱いがなくなったことを反映）
  - 動的 MCP tool の登録フロー更新
- `docs/30.egopulse/mcp.md`:
  - §9 起動時初期化: `create_tool_adapters()` を含むフローに更新
  - §10 Tool 公開: adapter 経由のフローに更新
  - §3 関連コンポーネント: `tools/mcp_adapter.rs` 追加

### コミット

`docs: update tools.md and mcp.md for provider trait architecture`

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

## Step 7: PR 作成

- Title: `refactor: organize ToolRegistry and MCP responsibility boundaries`
- Body: 日本語。`Close #157` 明記。設計方針・変更概要・テスト戦略を記載。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egopulse/src/tools/sanitizer.rs` | **新規** | 秘匿情報マスキング抽出 |
| `egopulse/src/tools/mcp_adapter.rs` | **新規** | MCP → Tool trait Adapter |
| `egopulse/src/tools/mod.rs` | 変更 | mcp_manager 削除、sanitizer 再エクスポート、テスト修正 |
| `egopulse/src/mcp.rs` | 変更 | create_tool_adapters() 追加、is_mcp_tool() 削除 |
| `egopulse/src/runtime.rs` | 変更 | AppState に mcp_manager 追加、初期化順序変更 |
| `egopulse/src/agent_loop/turn.rs` | 変更 | 軽微（テスト helper 修正のみ） |
| `egopulse/src/agent_loop/session.rs` | 変更 | 軽微（テスト helper 修正のみ） |
| `docs/30.egopulse/tools.md` | 変更 | Registry セクション更新 |
| `docs/30.egopulse/mcp.md` | 変更 | 初期化・公開フロー更新 |

---

## コミット分割

1. `refactor: extract sanitizer module from tools/mod.rs` — sanitizer.rs, mod.rs
2. `feat: add McpToolAdapter implementing Tool trait` — mcp_adapter.rs, mcp.rs
3. `refactor: remove MCP awareness from ToolRegistry` — mod.rs, mcp.rs
4. `refactor: move mcp_manager to AppState for direct access` — runtime.rs
5. `test: update existing tests for new ToolRegistry API` — mod.rs, session.rs, turn.rs
6. `docs: update tools.md and mcp.md for provider trait architecture` — tools.md, mcp.md

---

## テストケース一覧（全 32 件）

### Sanitizer (12)
1. `test_redact_secrets_replaces_config_values` — Config 由来 secret の REDACTED 置換
2. `test_redact_secrets_empty_list_noop` — secrets 空 → 入力そのまま
3. `test_redact_secrets_longer_first` — 長い secret 優先で誤マッチ防止
4. `test_redact_known_patterns_openai` — sk- プレフィクス検出
5. `test_redact_known_patterns_multiple` — 1行に複数パターン
6. `test_redact_known_patterns_no_false_positive` — 単語途中の sk- は無視
7. `test_sanitize_output_string_both_layers` — config + known patterns 二重適用
8. `test_sanitize_json_value_nested` — ネスト JSON 内の String もマスキング
9. `test_sanitize_tool_result_applies_to_all_fields` — content / llm_content / details 全フィールド
10. `test_sanitize_message_content_parts` — Parts の InputText / InputImage
11. `test_collect_config_secrets_extracts_api_keys` — provider API keys 抽出
12. `test_collect_config_secrets_extracts_auth_tokens` — channel auth tokens 抽出

### McpToolAdapter (12)
13. `test_adapter_name_matches_sanitized` — name() が mcp_{server}_{tool} 形式
14. `test_adapter_definition_converts_schema` — MCP schema → ToolDefinition 変換
15. `test_adapter_execute_success` — 正常実行 → ToolResult::success
16. `test_adapter_execute_empty_output` — 空レスポンス → (no output)
17. `test_adapter_execute_server_not_found` — server index 不正 → error
18. `test_adapter_execute_timeout` — timeout → error with timeout message
19. `test_adapter_execute_non_object_input` — JSON object 以外 → error
20. `test_adapter_execute_formats_text_content` — Text content → そのまま
21. `test_adapter_execute_formats_image_content` — Image content → [image: ...]
22. `test_adapter_execute_formats_resource_content` — Resource content → resource/blob
23. `test_mcp_manager_create_adapters_count` — adapter 数 = 全 server × 全 tool
24. `test_mcp_manager_create_adapters_skips_collisions` — 衝突 tool 除外

### ToolRegistry + AppState (8)
25. `test_registry_definitions_returns_all_tools` — built-in + adapter 全定義
26. `test_registry_execute_builtin_tool` — built-in dispatch（MCP 分岐なし）
27. `test_registry_execute_adapter_tool` — adapter dispatch
28. `test_registry_execute_unknown_tool` — 未登録 → error
29. `test_registry_no_mcp_field` — mcp_manager 系メソッドが存在しない
30. `test_appstate_has_mcp_manager` — AppState.mcp_manager フィールド
31. `test_build_app_state_registers_adapters` — adapter が register_tool される
32. `test_status_snapshot_uses_appstate_mcp` — status が AppState.mcp_manager 参照

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | Worktree 作成 | ~5 行 |
| Step 1 | Sanitizer 抽出 | ~250 行 |
| Step 2 | McpToolAdapter 実装 | ~300 行 |
| Step 3 | ToolRegistry 簡素化 + AppState | ~200 行 |
| Step 4 | 既存テスト修正 | ~80 行 |
| Step 5 | ドキュメント更新 | ~60 行 |
| **合計** | | **~895 行** |
