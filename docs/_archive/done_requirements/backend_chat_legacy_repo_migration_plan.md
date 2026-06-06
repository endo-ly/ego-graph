---
title: Backend Chat API Legacy Repo Migration Plan
aliases:
  - Chat API Legacy Migration Plan
  - Backend Legacy Repo Split Plan
tags:
  - backend
  - legacy
  - migration
  - frontend
  - api
status: approved
created: 2026-04-10
updated: 2026-04-10
---

# バックエンド Chat API Legacy Repo 移行計画

## 1. Summary

本計画は、現行 `egograph/backend` からチャット系 API 群を分離し、旧フロントエンド専用リポジトリ `endo-ava/egograph-frontend-capacitor-legacy` に移設するための段階的な移行方針を定義する。

移行後の責務は以下とする。

- 現行リポジトリ: EgoGraph のデータ提供 API と将来の MCP server に集中する
- Legacy リポジトリ: 旧 Capacitor frontend と、その frontend が依存する chat 系 backend を同居管理する

本計画は「どちらのリポジトリで何を行うか」を明確にし、無駄な後方互換や中途半端な二重管理を避けることを目的とする。

## 2. Goal / Non-Goal

### 2.1 Goal

- 現行 `egograph/backend` から chat 系 API と LLM 依存を除去する
- 旧 frontend が依存する chat 系 API を legacy repo 内 `backend/` に再配置する
- 旧 frontend と旧 backend の契約変更を legacy repo 内で閉じられる状態にする
- 現行 backend の責務を「データ提供」と「MCP server 化」に寄せる
- 移行後に両 repo でテストと起動確認ができる状態にする

### 2.2 Non-Goal

- 現行 backend と legacy backend の長期的な API 互換維持
- chat API を MCP 化すること
- 履歴保持を最優先した複雑な git 移植
- 旧 frontend の大幅な UI 改修
- 現時点での backend 完全再設計

## 3. Current Understanding

現時点で legacy frontend が依存する API 契約は以下である。

- `POST /v1/chat`
- `GET /v1/chat/models`
- `GET /v1/threads`
- `GET /v1/threads/{thread_id}`
- `GET /v1/threads/{thread_id}/messages`
- `GET /v1/system-prompts/{name}`
- `PUT /v1/system-prompts/{name}`

現行リポジトリ側では、これらは単なる endpoint ではなく、以下の要素にまたがって存在している。

- FastAPI router
- chat 履歴用 SQLite
- thread repository
- chat usecase
- LLM provider / config
- tool registry
- dev tool
- API / usecase / repository / integration tests
- backend docs

したがって「`api/chat.py` を削除して終わり」ではなく、chat 系の境界を一式で移送する必要がある。

## 4. Target State

### 4.1 現行リポジトリ

- `egograph/backend` はデータ取得 API のみを提供する
- chat / threads / system prompts / LLM runtime を持たない
- 起動時に chat 用 SQLite を初期化しない
- production validation で LLM を前提にしない
- docs / README から chat agent backend と読める記述を除去する

### 4.2 Legacy リポジトリ

- ルート直下に `frontend/` と `backend/` を持つ
- `frontend/` には既存 Capacitor frontend を再配置する
- `backend/` には旧 frontend 専用 chat backend を配置する
- ルート README で app 全体の構成と起動手順を説明する
- frontend / backend の変更を同一 repo の PR で扱える

## 5. Repository Strategy

### 5.1 現行リポジトリでやること

- chat 系コードの依存範囲を確定する
- legacy repo へ移す対象をファイル単位で棚卸しする
- 現行 backend から chat 系機能を削除する
- chat 削除後も残る data API 群の動作を維持する
- README / architecture docs を data API 中心へ更新する
- 今後の MCP server 化に不要な LLM 前提を取り除く

### 5.2 Legacy リポジトリでやること

- repo ルート配下を `frontend/` へ再配置する
- 新規 `backend/` を作成する
- chat 系 backend を移植する
- frontend の API base path や開発手順を新構成に合わせて更新する
- frontend / backend をまとめた CI と README を整備する

### 5.3 一時的に両 repo で合わせてやること

- API 契約差分の確認
- 環境変数名の整理
- ローカル起動フローの再定義
- テスト観点の再配分

## 6. Migration Scope

### 6.1 Legacy repo へ移す対象

- `api/chat.py`
- `api/threads.py`
- `api/system_prompts.py`
- chat/threads/system prompt 用 schema
- `usecases/chat/`
- chat に必要な `usecases/tools/`
- chat に必要な `domain/models/` と `domain/tools/`
- `infrastructure/llm/`
- chat 用 SQLite connection / table 初期化
- `infrastructure/repositories/thread_repository.py`
- `dev_tools/chat_cli.py`
- chat / threads / system prompts / llm に関する tests
- 関連ドキュメントのうち legacy backend に必要なもの

### 6.2 現行 repo に残す対象

- data API
- browser history / github などのデータ参照 endpoint
- R2 / DuckDB ベースのデータアクセス機能
- 将来 MCP server 化するためのデータ取得ユースケース

### 6.3 判断が必要な対象

- `system_prompts` を legacy backend に残すか
  - 決定: legacy frontend が依存しているため、chat 系 API と同じ単位で legacy repo へ移設する
  - 将来的に不要化する場合も、legacy repo 内で閉じて削除する
- `usecases/tools/` のうち chat 以外でも使うもの
  - 共通化せず、まずは legacy backend に必要最小限を複製移設する

## 7. Directory Plan For Legacy Repo

推奨構成は以下とする。

```text
egograph-frontend-capacitor-legacy/
├── frontend/
│   ├── android/
│   ├── public/
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── backend/
│   ├── app/
│   ├── tests/
│   ├── pyproject.toml
│   ├── README.md
│   └── .env.example
├── API.md
└── README.md
```

補足:

- backend 名は現行 repo と揃えるため `backend/` とする
- frontend と backend を別 package / 別 runtime として扱う
- root は「legacy app 全体」を説明する repo root とする

## 8. Phase Plan

### Phase 1. 事前棚卸し

現行 repo で以下を行う。

- chat 系コードの依存グラフを確定する
- legacy repo に必要な最小ファイルセットを決める
- docs と tests の移送対象を決める
- 現行 backend から削除後に残す公開 surface を明文化する

完了条件:

- 移設対象一覧がファイル単位で確定している
- 現行 repo / legacy repo の担当範囲が明文化されている

### Phase 2. Legacy repo 構造再編

legacy repo で以下を行う。

- 既存 frontend 一式を `frontend/` 配下へ移動する
- path, build, Android, Vite, CI の参照先を更新する
- root README を新構成に合わせて更新する

完了条件:

- `frontend/` 配下で既存 frontend がビルドできる
- Android 同期と web build が通る

決定:

- backend 移植より先に、この構造再編を完了させる

### Phase 3. Legacy backend 新設

legacy repo で以下を行う。

- `backend/` を新設する
- FastAPI 起動構成、依存、`.env.example`、テスト基盤を整える
- healthcheck と設定ロードを先に通す

完了条件:

- `backend/` 単体で起動できる
- テスト基盤が動く

### Phase 4. Chat 系機能移植

legacy repo で以下を行う。

- chat / threads / system prompts を移植する
- SQLite, LLM config, repository, usecase, tool registry を移植する
- frontend が参照する API 契約を維持する
- API.md を移植後実装に合わせて更新する

完了条件:

- frontend からチャット送信、スレッド一覧、履歴取得、system prompt 編集が動く
- backend tests が通る

### Phase 5. 現行 repo から chat 系除去

現行 repo で以下を行う。

- chat / threads / system prompt router を削除する
- chat SQLite 初期化を削除する
- LLM config 必須前提を削除する
- chat 関連 tests / docs / dev tool を削除または整理する
- README / architecture docs を更新する

完了条件:

- 現行 backend が data API として起動する
- chat 関連コードが production path に残っていない

決定:

- legacy 側疎通確認後に、現行 repo の chat 系は並行運用せず一気に除去する

### Phase 6. MCP server 化前提の整理

現行 repo で以下を行う。

- data access の公開面を再定義する
- REST と MCP の境界を決める
- 不要な HTTP endpoint をさらに減らせるか確認する

完了条件:

- 次の実装フェーズで MCP server 化へ進める前提が揃っている

## 9. Validation Plan

### 9.1 現行 repo

- `uv run pytest egograph/backend/tests`
- chat 系削除後に残すテストの再編
- `uv run ruff check egograph/backend`
- backend 起動確認
- `/health` と data API の疎通確認

### 9.2 Legacy repo

- `npm run lint`
- `npx tsc --noEmit`
- `npm run build`
- `npm run test:run`
- backend tests
- frontend から legacy backend への実機またはローカル疎通確認

### 9.3 E2E 観点

- 新規チャット送信
- 既存 thread 継続
- ストリーミング応答
- スレッド一覧表示
- thread message 再読込
- system prompt 読み書き
- API key 有効 / 無効時の挙動

## 10. Risks And Mitigations

### Risk 1. chat 系依存の取り残し

- 症状: 現行 repo に LLM 設定や SQLite 初期化が残る
- 対策: import / router / config / test を横断して棚卸しする

### Risk 2. legacy repo の構造変更で frontend が壊れる

- 症状: Android, Vite, CI, asset path が崩れる
- 対策: 先に `frontend/` 再配置だけを単独で完了させる

### Risk 3. API 契約の微差で旧 frontend が動かない

- 症状: stream chunk, error detail, thread response shape のズレ
- 対策: API.md をテスト対象として扱い、互換確認を行う

### Risk 4. 共通化を狙いすぎて移行が止まる

- 症状: 両 repo で使える抽象化を作ろうとして手が止まる
- 対策: まずは legacy 専用 backend として素直に移植する

### Risk 5. 履歴移行に時間を使いすぎる

- 症状: git 履歴移植が主作業になる
- 対策: 履歴保持は必須要件にしない

## 11. History Migration Policy

結論として、**履歴を完全に持っていくことは今回の主目的ではない** と定義する。

理由:

- chat 系コードは単独ファイルではなく、現行 backend 全体にまたがっている
- legacy repo 側では同時に `frontend/` 再配置も行うため、純粋な履歴移植が難しい
- `git filter-repo`, `subtree`, `cherry-pick` を駆使しても、得られる履歴の可読性が低くなりやすい
- 移行の本質は責務分離であり、履歴保存ではない

推奨方針:

- 実装は通常の新規 commit で行う
- 必要に応じて commit message や README に「移設元」を明記する
- 重要な背景は計画書や API.md に残す
- 初回移設 PR に移設元ファイル一覧と参照 commit を明記する

妥協案:

- legacy repo 側の初回移植 PR に「移設元ファイル一覧」を明記する
- 必要なら現行 repo の commit hash を参考情報として PR description に残す

## 12. Recommended Execution Order

1. この計画をレビューしてスコープを確定する
2. legacy repo の `frontend/` 再配置 plan を別途詳細化する
3. legacy repo で構造再編を先に完了する
4. legacy repo に backend を新設する
5. chat 系 backend を移植して frontend 疎通を通す
6. 現行 repo から chat 系を削除する
7. 現行 backend の data API / MCP 方向の次計画へ進む

## 13. Open Questions

- legacy backend の package 名をどうするか
- system prompts をどこまで legacy backend に残すか
- legacy repo で frontend / backend をどう起動統合するか
- CI を monorepo 的に 1 workflow へ寄せるか、frontend/backend 分割にするか
- chat 用 SQLite の保存場所を repo 内ローカルファイルにするか、実行ディレクトリ基準にするか

## 14. Decision

現時点の推奨判断は以下とする。

- chat 系 backend は legacy repo に移す
- `system_prompts` も legacy repo に移す
- legacy repo は `frontend/` と `backend/` の二層構成に再編する
- legacy repo の `frontend/` 再編を backend 移植より先に完了する
- legacy 側疎通後、現行 repo の chat 系は一気に除去する
- 履歴移行は無理に狙わない
- ただし移設元ファイル一覧と参照 commit は PR に残す
- 現行 repo では後方互換を持たず、chat 系をきれいに除去する

この方針が、責務分離・保守性・将来の MCP server 化の3点で最も素直である。
