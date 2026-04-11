---
title: EgoPulse MCP Integration Plan
aliases:
  - Egopulse MCP Plan
  - EgoPulse MicroClaw MCP Migration Plan
tags:
  - egopulse
  - mcp
  - runtime
  - rust
status: draft
created: 2026-04-11
updated: 2026-04-11
---

# EgoPulse MCP 導入計画

## 1. Summary

本計画は `egopulse` に Model Context Protocol (MCP) client を導入し、MicroClaw と同様に外部 MCP server の tool を動的に利用できる状態にするための実装方針を定義する。

今回の方針は「MCP の最小サブセットを独自実装する」ものではなく、MicroClaw の設計をできるだけそのまま取り込みつつ、EgoPulse の `workspace` 中心設計に自然に馴染ませることを目的とする。

初期方針として以下を採用する。

- config source は global と workspace の両対応とする
- transport は `stdio` と `streamable_http` の両対応とする
- tool は `mcp_{server}_{tool}` 形式で動的公開する
- config merge は後勝ち override とする
- 既存 built-in tool registry と同じ経路で LLM に公開する

## 2. Goal / Non-Goal

### 2.1 Goal

- `egopulse` 起動時に MCP config を読み込み、接続可能な server を初期化できる
- 複数 MCP server の tool を動的に列挙し、LLM から built-in tool と同様に呼び出せる
- `stdio` と `streamable_http` の両 transport を利用できる
- global config と workspace config をマージして利用できる
- 接続失敗した server があっても runtime 全体は起動継続できる
- テストで config merge、tool registration、tool execution の主要経路を担保できる

### 2.2 Non-Goal

- MCP server 実装をこのタスクで作ること
- memory backend の MCP 連携まで同時に入れること
- A2A、subagent、browser など MicroClaw の他機能までまとめて移植すること
- 既存 built-in tool の大規模再設計
- 旧案 `.mcp.json` を正式採用すること

## 3. Current Understanding

現状の `egopulse` は以下の構造になっている。

- [`egopulse/src/config.rs`](../../egopulse/src/config.rs)
  - `workspace_dir()` は `~/.egopulse/workspace` を返す
  - `skills_dir()` は workspace 配下に固定されている
- [`egopulse/src/tools.rs`](../../egopulse/src/tools.rs)
  - built-in tool registry を一括定義している
  - registry は静的構成で、動的 tool 追加 API はまだない
- [`egopulse/src/runtime.rs`](../../egopulse/src/runtime.rs)
  - `AppState` 構築時に config / db / llm / skills / tools を組み立てる

一方で MicroClaw は以下の設計を採っている。

- `src/mcp.rs`
  - MCP config 読み込み
  - 複数 server への接続管理
  - `stdio` / `streamable_http` transport 対応
  - tools cache / retry / health probe を実装
- `src/tools/mcp.rs`
  - `mcp_{server}_{tool}` 形式の動的 tool wrapper を提供
- runtime 起動時に `McpManager` から tool を取り出し、tool registry に追加する

したがって EgoPulse 側でも、runtime 初期化時に MCP 接続を行い、tool registry へ後付け登録するのが最も自然である。

## 4. Key Decisions

### 4.1 Config File Naming

MCP config の正式名称は以下とする。

- `mcp.json`
- `mcp.d/*.json`

`.mcp.json` は採用しない。

理由:

- MicroClaw と命名を揃えやすい
- 隠しファイルにする必然が薄い
- `mcp.d/` とセットで見たときに構成が分かりやすい

### 4.2 Config Source Strategy

初期候補として global / workspace の両対応を採用する。

探索対象は以下とする。

1. `~/.egopulse/mcp.json`
2. `~/.egopulse/mcp.d/*.json`
3. `~/.egopulse/workspace/mcp.json`
4. `~/.egopulse/workspace/mcp.d/*.json`

マージ順は上記の通りで、後に読まれた設定が同名 server を override する。

理由:

- 共通 MCP は global で持てる
- project / task 固有 MCP は workspace で上書きできる
- EgoPulse の workspace 中心設計を維持できる
- MicroClaw の `mcp.json` / `mcp.d` パターンも保てる

### 4.3 Transport Support

初回から以下をサポートする。

- `stdio`
- `streamable_http`

`stdio` 限定にはしない。

### 4.4 Tool Naming

動的 tool 名は MicroClaw に合わせて以下とする。

- `mcp_{server}_{tool}`

無効文字は `_` に正規化し、長さ制限も設ける。

### 4.5 Runtime Failure Policy

一部の MCP server が接続失敗しても EgoPulse 全体は起動継続する。

- 接続できた server の tool のみ公開する
- 接続失敗は warning log に記録する
- config 全体が壊れていても built-in tool runtime は落とさない

## 5. Target State

導入後の `egopulse` は以下の状態を目指す。

- 起動時に MCP config source を列挙してマージする
- 定義済み MCP server ごとに接続を試行する
- 接続した server から `tools/list` を取得する
- 動的 tool wrapper を registry に追加する
- LLM には built-in tool と MCP tool が同一インターフェースで渡される
- tool 実行時には対応する server に `call_tool` を転送する
- server ごとの timeout / retry / health probe が働く

## 6. Architecture Plan

### 6.1 New Module

新規に [`egopulse/src/mcp.rs`](../../egopulse/src/mcp.rs) を追加する。

責務は以下とする。

- MCP config schema 定義
- config file 読み込み
- `mcp.json` / `mcp.d/*.json` のマージ
- MCP server connection 管理
- tools cache 管理
- health probe 起動
- `call_tool` の実行

### 6.2 Tool Layer Integration

MCP tool wrapper は `tools` 層に追加する。

候補:

- `egopulse/src/tools/mcp.rs` を追加する
- もしくは既存 [`egopulse/src/tools.rs`](../../egopulse/src/tools.rs) を分割する

推奨は `tools` 分割である。理由は `tools.rs` がすでに大きく、MCP wrapper を同居させると責務がさらに膨らむため。

ただし、既存構造への影響を最小にすることを優先するなら、初回は `tools.rs` 内に `McpTool` を追加してもよい。

### 6.3 Registry Extension

既存 `ToolRegistry` は静的配列で構築されているため、以下の変更を入れる。

- `add_tool(Box<dyn Tool>)` を追加
- `definitions()` が built-in + dynamic tool を返せるようにする
- `execute()` が追加済み dynamic tool も対象にできるようにする

### 6.4 Runtime Wiring

[`egopulse/src/runtime.rs`](../../egopulse/src/runtime.rs) の `build_app_state_with_path()` で以下を行う。

1. config から MCP config paths を解決
2. `McpManager` を初期化
3. `ToolRegistry` を生成
4. `McpManager::all_tools()` で得た tool を registry に追加
5. `AppState` に組み込む

### 6.5 stdio Working Directory Policy

`stdio` transport の subprocess は workspace を `cwd` にして起動する。

理由:

- filesystem 系 MCP server が自然に workspace を基準に動作できる
- Egopulse の built-in file tools と基準を揃えられる
- config file の配置場所ではなく、agent の作業空間を基準にしたほうが利用者の期待に合う

## 7. Config Schema Plan

MicroClaw 互換に寄せた schema を採用する。

```json
{
  "defaultProtocolVersion": "2024-11-05",
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
    },
    "remote": {
      "transport": "streamable_http",
      "endpoint": "http://127.0.0.1:8080/mcp",
      "headers": {
        "Authorization": "Bearer REPLACE_ME"
      },
      "request_timeout_secs": 60
    }
  }
}
```

server ごとの主な項目は以下とする。

- `transport`
- `protocol_version`
- `request_timeout_secs`
- `max_retries`
- `health_interval_secs`
- `command`
- `args`
- `env`
- `endpoint`
- `headers`

## 8. Phase Plan

### Phase 1. Config / Type Foundation

- `config.rs` に MCP config paths 解決 API を追加する
- `mcp.rs` に config schema と merge 処理を追加する
- global / workspace 両 source の探索順を固定する
- 無効 JSON、重複 server override、未存在 path の扱いを決める

完了条件:

- config source の列挙と merge を unit test で確認できる
- override 順が明文化され、実装でも固定されている

### Phase 2. MCP Connection Layer

- `McpServer` と `McpManager` を実装する
- `stdio` / `streamable_http` の接続をサポートする
- 初期化時に `tools/list` を取得して cache する
- timeout / retry / health probe を組み込む

完了条件:

- mock 可能な範囲で接続ロジックの unit test がある
- 接続失敗時に runtime が継続できる

### Phase 3. Tool Registry Integration

- `McpTool` wrapper を実装する
- tool 名の namespacing と sanitize を実装する
- `ToolRegistry` に dynamic tool 追加機構を入れる
- runtime 起動時に MCP tool を登録する

完了条件:

- `definitions()` に MCP tool が含まれる
- `execute()` 経由で MCP tool を呼び出せる

### Phase 4. End-to-End Validation

- local な stdio MCP server を使って E2E 検証する
- HTTP MCP server を使って E2E 検証する
- tool 名、引数、エラー経路、タイムアウト経路を確認する
- ドキュメントと example config を追加する

完了条件:

- `cargo test -p egopulse`
- `cargo check -p egopulse`
- `cargo clippy --all-targets --all-features -- -D warnings`
- README または docs に利用方法が追記されている

## 9. Testing Strategy

### 9.1 Unit Test

- config path 解決
- `mcp.json` / `mcp.d` merge 順
- duplicate server override
- tool 名 sanitize
- internal input key 除去
- timeout / retry 判定ロジック

### 9.2 Integration Test

- `ToolRegistry` に MCP tool を追加して定義に見える
- MCP tool 実行結果が `ToolResult` に正しく変換される
- 接続失敗 server を含んでも registry 生成が継続する

### 9.3 Manual Verification

- workspace `mcp.json` だけで stdio server が動く
- global `mcp.json` だけで HTTP server が動く
- global 定義を workspace 側が override できる
- LLM から `mcp_*` tool が見える

## 10. Risks / Open Questions

### 10.1 rmcp 依存導入

MicroClaw と同じく `rmcp` を導入する前提だが、現在の `egopulse` dependency と feature set の競合確認が必要である。

対応:

- 依存追加後に `cargo check -p egopulse` を早めに回す
- 必要なら feature を MicroClaw と同様に最小化する

### 10.2 Tool File Structure

`tools.rs` がすでに大きいため、MCP wrapper をどこに置くかは保守性に効く。

推奨:

- 初回で `tools/` ディレクトリ分割までやる

妥協案:

- 初回は差分最小で `tools.rs` に入れ、後続で分割する

### 10.3 stdio subprocess cwd

workspace 基準にする方針だが、一部 server が config file 親ディレクトリ基準を期待する可能性がある。

現時点の判断:

- EgoPulse では workspace 基準を正とする
- 必要なら後続で server 単位 override を追加検討する

## 11. Implementation Worktree / Git Plan

本計画に基づく実装は「計画あり」の作業であるため、実装着手時は Git worktree を作成して進める。

基本スコープは以下とする。

- Worktree 作成
- 実装
- unit / integration / manual verification
- 意味ごとの commit 分割
- PR 作成

ブランチ名候補:

- `feat/egopulse-mcp-client`

コミット粒度候補:

1. `feat(egopulse): add mcp config and manager foundation`
2. `feat(egopulse): register dynamic mcp tools`
3. `docs(egopulse): document mcp configuration and usage`

## 12. Acceptance Criteria

- `egopulse` が global / workspace 両方の MCP config source を読める
- `stdio` / `streamable_http` の両 transport を使える
- 接続済み server の tool が `mcp_{server}_{tool}` 形式で LLM に公開される
- built-in tool と同じ turn loop で MCP tool を実行できる
- 一部 server の失敗で runtime 全体が起動不能にならない
- テストと静的検査が通る
- config 命名は `mcp.json` / `mcp.d` に統一される

## 13. References

- MicroClaw MCP architecture docs
  - https://microclaw.ai/docs/architecture-mcp/
- MicroClaw `src/mcp.rs`
  - https://github.com/microclaw/microclaw/blob/main/src/mcp.rs
- MicroClaw `src/tools/mcp.rs`
  - https://github.com/microclaw/microclaw/blob/main/src/tools/mcp.rs
