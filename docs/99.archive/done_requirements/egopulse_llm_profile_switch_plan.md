---
title: EgoPulse LLM Switch Plan
aliases:
  - Egopulse Model Switch Plan
  - EgoPulse Provider Model Switch Plan
tags:
  - egopulse
  - llm
  - runtime
  - web
  - tui
  - rust
status: draft
created: 2026-04-11
updated: 2026-04-11
---

# EgoPulse LLM 切り替え計画

## 1. Summary

本計画は、`egopulse` に「使用 LLM を簡単に切り替える機能」を追加するための実装方針を定義する。

本機能は「provider」「model」「適用先 scope」を選択する導線を主とし、ユーザーに任意の識別子設計を要求しない。

採用方針は以下とする。

- `provider` は接続先の系統を表す
- `model` は provider ごとの候補から選ぶ
- `scope` は global または channel を選ぶ
- 内部では provider / model override を保持する
- TUI / Web UI は選択中心にする
- OpenAI 互換 endpoint 前提は維持する
- `EGOPULSE_MODEL` / `EGOPULSE_BASE_URL` / `EGOPULSE_API_KEY` は削除する

## 2. Goal / Non-Goal

### 2.1 Goal

- provider を切り替えられる
- model を切り替えられる
- global / channel 単位で適用先を選べる
- TUI / Web UI / command から変更できる
- runtime restart なしで新設定を反映できる

### 2.2 Non-Goal

- Anthropic native など OpenAI 互換以外の provider 実装追加
- pricing / live model discovery の同時実装
- ユーザーが任意 profile 名を日常的に設計する UX
- Microclaw 設定体系の完全移植

## 3. UX 方針

### 3.1 提供する選択

ユーザーに提供する主な選択は以下の 3 つとする。

1. `Provider`
2. `Model`
3. `Apply to`

### 3.2 Provider の意味

`provider` は接続先系統を表す。
実質的には `base_url` と認証ルールのまとまりである。

例:

- `OpenAI`
- `OpenRouter`
- `Local OpenAI-compatible`
- `Custom OpenAI-compatible`

したがって `base_url` が違えば provider も別系統として扱う。

### 3.3 Model の扱い

`model` は provider ごとに候補を出し分ける。

- OpenAI / OpenRouter は候補選択を主導線にする
- Local / Custom は手入力も許可する

### 3.4 Scope の扱い

適用先は以下を対象にする。

- `Global default`
- `Web`
- `Discord`
- `Telegram`

初期実装では channel 単位 override を優先し、session 単位切替は扱わない。

`cli` と `tui` は v1 では個別 scope を持たず、`Global default` を使用する。
内部実装は将来的に `cli` / `tui` を個別 scope 化できる構造にしておくが、今回の UI / command 選択肢には含めない。

## 4. 現状整理

現状の `egopulse` は単一 LLM 構成で固定されている。

- [`egopulse/src/config.rs`](../../egopulse/src/config.rs)
  - トップレベル `model` / `api_key` / `base_url` を 1 組だけ持つ
- [`egopulse/src/llm.rs`](../../egopulse/src/llm.rs)
  - provider が `model` / `base_url` を内部保持する
- [`egopulse/src/runtime.rs`](../../egopulse/src/runtime.rs)
  - `AppState` が固定 `llm` を持つ
- [`egopulse/src/agent_loop/mod.rs`](../../egopulse/src/agent_loop/mod.rs)
  - `SurfaceContext.channel` は存在するため channel 単位解決の余地はある
- [`egopulse/src/web/config.rs`](../../egopulse/src/web/config.rs)
  - Web UI は単一 `model` / `base_url` 編集前提

このため、単なる UI 追加ではなく、LLM 解決の責務を request-time へ移す必要がある。

## 5. Target State

導入後の `egopulse` は以下の状態を目指す。

- provider をグローバル既定として設定できる
- channel ごとに provider を上書きできる
- channel ごとに model を上書きできる
- TUI / Web UI / command から現在値確認と切替ができる
- 実際の LLM 呼び出し時に `channel -> effective provider -> effective model` を解決する
- `cli` / `tui` は `Global default` を利用する

## 6. Config 方針

### 6.1 基本構造

設定は以下のように整理する。

```yaml
default_provider: openai

providers:
  openai:
    label: OpenAI
    base_url: https://api.openai.com/v1
    api_key: sk-...
    default_model: gpt-4o-mini
    models:
      - gpt-4o-mini
      - gpt-5

  openrouter:
    label: OpenRouter
    base_url: https://openrouter.ai/api/v1
    api_key: sk-or-...
    default_model: openai/gpt-5

  local:
    label: Local OpenAI-compatible
    base_url: http://127.0.0.1:1234/v1
    default_model: qwen2.5

channels:
  web:
    enabled: true
    provider: openai
  discord:
    enabled: false
    provider: openrouter
    model: openai/gpt-5
```

### 6.2 旧設定との関係

旧トップレベル `model` / `base_url` / `api_key` は削除対象とする。

- 新規導線は provider ベースへ統一する
- setup / example config / README は新 schema に寄せる
- 旧 schema の読み取りを残さない
- `EGOPULSE_MODEL` / `EGOPULSE_BASE_URL` / `EGOPULSE_API_KEY` を削除する

### 6.3 今回あわせて削除する負債

今回の変更で、将来の負債になりやすい以下のフォールバック / 旧導線をまとめて削除対象とする。

1. 旧 LLM 環境変数
   - `EGOPULSE_MODEL`
   - `EGOPULSE_BASE_URL`
   - `EGOPULSE_API_KEY`
2. 旧トップレベル LLM 設定
   - `model`
   - `base_url`
   - `api_key`
3. 単一 OpenAI 既定値の直書き
   - `default_model()`
   - `default_llm_base_url()`
4. 環境変数のみで runtime 起動成立とみなす経路
   - `env_vars_sufficient_for_runtime()`
5. Web 設定保存後の見かけ上の成功フォールバック
   - config 再読込失敗時に `state.app_state.config.clone()` を返す経路
6. 常時 restart 必須を前提とした Web UI メッセージ
   - `requires_restart: true` 固定

上記は「移行のために一時的に残す」のではなく、今回のスコープで削除する。

## 7. 実装方針

### 7.1 Config

[`egopulse/src/config.rs`](../../egopulse/src/config.rs) に以下を追加する。

- `ProviderConfig`
- `default_provider`
- `providers`
- `ChannelConfig.provider`
- `ChannelConfig.model`
- 実効 provider / model 解決 helper

### 7.2 Runtime / LLM

固定 provider をやめ、turn ごとに実効設定を解決する構造へ変更する。

- `AppState.llm` を router / executor へ置き換える
- `llm.rs` は request-time に `base_url` / `api_key` / `model` を受け取れるようにする
- compaction でも同じ解決ルールを使う

### 7.3 Command

以下の command を追加する。

- `/providers`
- `/provider`
- `/models`
- `/model`

責務:

- 現在値の確認
- 切替
- reset
- config 永続化

### 7.4 TUI / Web UI

UI は識別子編集ではなく、選択中心にする。

- Provider picker
- Model picker
- Apply scope 選択

Web UI では dropdown を優先し、Local / Custom のみ入力補助を許可する。
TUI setup でも同じ概念で選ばせる。

## 8. 検証方針

### 8.1 Config / Runtime

- provider 読み込み
- default provider 解決
- channel override 解決
- model override 解決
- 旧トップレベル設定と旧環境変数が除去されていること
- 単一 OpenAI 既定値の直書きが除去されていること
- config file 再読込失敗時に見かけ上成功しないこと

### 8.2 LLM Request

- channel に応じて request body の `model` が変わる
- channel に応じて `base_url` / auth が変わる
- compaction でも同じ provider / model を使う

### 8.3 UX

- command から切替できる
- TUI から切替できる
- Web UI から切替できる
- 変更後の次ターンで反映される

## 9. フェーズ計画

### Phase 1. Config 再設計

- provider schema 追加
- channel override 追加
- 解決 helper 追加
- unit test 追加
- 旧 LLM 環境変数削除
- 旧トップレベル LLM 設定削除
- `default_model()` / `default_llm_base_url()` 削除
- `env_vars_sufficient_for_runtime()` 削除

### Phase 2. LLM Router 化

- request-time 解決へ変更
- runtime wiring 更新
- compaction 統一

### Phase 3. 操作面追加

- command 追加
- TUI 追加
- Web UI 追加
- `requires_restart: true` 前提の文言削除
- Web 設定保存失敗時の見かけ成功フォールバック削除

### Phase 4. ドキュメント更新

- setup 更新
- example config 更新
- README 更新

### Phase 5. 総合検証

- `cargo check -p egopulse`
- `cargo test -p egopulse`
- Web 動作確認
- 可能なら実チャネル確認

## 10. リスク

### 10.1 候補一覧の保守

provider ごとの model 候補一覧は古くなる可能性がある。

方針:

- v1 では静的候補 + 手入力 fallback
- live discovery は将来対応

## 11. Git Plan

本件は計画あり実装のため、Git Worktree を切って進める。

推奨ブランチ名:

- `feature/egopulse-llm-switch`

想定 commit 例:

- `feat(egopulse): add provider based llm config`
- `feat(egopulse): resolve llm settings per channel`
- `feat(egopulse): add provider and model switch commands`
- `feat(egopulse): update tui and web ui for llm switching`
- `docs(egopulse): document provider based llm configuration`
