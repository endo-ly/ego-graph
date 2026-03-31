# EgoPulse MVP Issue 2.5: Local TUI And Config Polish

## 1. Summary
- やりたいこと：Issue 2 で完成した persistent agent core の上に、ローカル利用に適した TUI と設定体験を追加する。
- 理由：`chat --session ...` 前提の開発者向け CLI のままだと、継続利用・検証・再開の操作コストが高い。
- 対象：`egopulse/` の local surface と config loading まわり。
- 優先：Issue 3 の multi-surface 対応に入る前の優先タスク。

## 2. Purpose (WHY)
- いま困っていること：ローカル検証で毎回 `--config` や `--session` を手で指定する必要があり、再開や新規開始が不便。
- できるようになったら嬉しいこと：`egopulse` 単体で起動し、session 一覧から再開・新規開始ができる。
- 成功すると何が変わるか：Issue 3 に入る前に、persistent core を人間向けの local surface として日常的に使えるようになる。

## 3. Requirements (WHAT)
- 機能要件：
  - `egopulse` 単体起動で local TUI が開く。
  - TUI から session 一覧表示、新規 session 作成、既存 session 再開ができる。
  - TUI 内で継続会話ができ、Issue 2 の persistent agent core をそのまま利用する。
  - `egopulse.config.yaml` を自動探索して読み込める。
  - `ask` と `chat --session ...` は開発者向け入口として残す。
- 期待する挙動：
  - config が見つかれば `egopulse` 単体で起動可能。
  - config 未発見時は、作成方法と探索場所が分かるエラーを返す。
  - session 一覧には session 名、最終更新時刻、短い preview が出る。
  - 再起動後も同じ TUI から session を再開できる。
- 画面/入出力（ある場合）：
  - local TUI（`ratatui` / `crossterm` 想定）
  - 一覧画面
  - 会話画面
  - 新規 session 開始導線

## 4. Scope
- 今回やる（MVP）：
  - local TUI
  - `egopulse.config.yaml` 自動読込
  - session 一覧 / 新規 / 再開
  - 起動時エラー案内改善
  - README / runbook 更新
- 今回やらない（Won’t）：
  - Discord / Telegram / WebUI
  - tools / Skill / MCP
  - scheduler
  - 本格的な setup wizard 全体
- 次回以降（あれば）：
  - Issue 3 の multi-surface 対応
  - より高度な setup wizard
  - local Web UI との関係整理

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 起動する | `egopulse` で TUI が開く | 前回利用 session の自動選択 |
| 設定を読む | `egopulse.config.yaml` を自動読込 | `~/.config/egopulse/config.yaml` 探索 |
| session を選ぶ | 一覧から再開 / 新規作成 | 検索 / 並び替え |
| 会話する | 継続会話できる | ショートカット / 補助コマンド |
| 再開する | 再起動後に同じ session を再開できる | session rename / archive |

## 6. Acceptance Criteria
- Given `egopulse.config.yaml` が存在する, When `egopulse` を起動する, Then local TUI が開く。
- Given 既存 session がある, When TUI からその session を選ぶ, Then 過去履歴を踏まえて継続会話できる。
- Given session が存在しない, When TUI から新規開始する, Then 新しい session が作られて保存される。
- Given プロセスを再起動する, When 同じ session を選ぶ, Then SQLite に保存された履歴から再開できる。
- Given config が存在しない, When `egopulse` を起動する, Then `egopulse.config.yaml` の作り方が分かるメッセージが出る。

## 7. 例外・境界
- 失敗時（通信/保存/権限）：LLM / SQLite / config 読込エラーは TUI から分かる形で表示する。
- 空状態（データ0件）：session 一覧 0 件でも新規 session 作成ができる。
- 上限（文字数/件数/サイズ）：Issue 2 の履歴上限をそのまま使う。
- 既存データとの整合（互換/移行）：Issue 2 の SQLite schema をそのまま利用する。

## 8. Non-Functional Requirements (FURPS)
- Performance：session 一覧表示はローカルで体感待ちが少ないこと。
- Reliability：Issue 2 の resume/persistence を壊さないこと。
- Usability：`egopulse` 単体起動で基本操作に入れること。
- Security/Privacy：自動読込対象は `egopulse.config.yaml` のみとし、`.env` や `egopulse.local.yaml` の自動読込は行わない。
- Constraints（技術/期限/外部APIなど）：MicroClaw copy-first 方針を維持し、local surface だけにスコープを限定する。

## 9. RAID (Risks, Assumptions, Issues, Dependencies)
- Risk：TUI 実装が core を巻き込んで責務分離を崩す。
- Assumption：Issue 2 の persistent agent core は stable に利用できる。
- Issue：現状の CLI は開発者向けで、人間向け導線が弱い。
- Dependency：Issue 2 の PR が main に入っていること。

## 10. Reference
- https://github.com/microclaw/microclaw
- /root/workspace/ego-graph/docs/00.requirements/egopulse_mvp_issue_2_persistent_agent_core.md
- /root/workspace/ego-graph/docs/00.requirements/egopulse_mvp_issue_3_surfaces_and_mvp_completion.md
