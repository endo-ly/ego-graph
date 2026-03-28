---
name: 要件定義 / Requirements
about: 新機能や修正の要件を明確化するためのテンプレート
title: "[REQ] System Prompt Design (Bootstrap Context Files)"
labels: requirements
assignees: ""
---

<!--
追加ラベル:
- カテゴリ: feature, fix
- コンポーネント: backend, frontend, ingest, gateway
-->

## 1. Summary

<!-- 1〜3行。いまの理解を短く。 -->

- やりたいこと：システムプロンプトの基盤ファイル群をファイル管理し、毎回コンテキストへ注入する
- 理由：Clawdbotの思想（編集可能な正本を常時注入）をEgoGraphに取り入れたい
- 対象：`backend/context/` 配下のブートストラップファイル一式 + モバイルアプリからの編集
- 優先：高

## 2. Purpose (WHY)

<!-- 解決したい課題 / 得たい価値 -->

- いま困っていること：ユーザー情報や運用ルールが会話履歴に散在し、更新/共有が曖昧
- できるようになったら嬉しいこと：ユーザー情報や運用方針をファイルで一元管理し、毎回確実に注入できる
- 成功すると何が変わるか：アプリ側でいつでも編集でき、LLMの挙動が安定し再現性が上がる

## 3. Requirements (WHAT)

<!-- ユーザーが「何をできるようになるか」を具体的かつ構造化してまとめる。実装方法は書かない。 -->

- 機能要件：
- アプリ（Capacitorモバイル）から、以下のブートストラップファイルを閲覧・編集できる
  - `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `BOOTSTRAP.md`
  - ブートストラップファイルは `backend/context/` を正本とする
  - モバイルアプリはAPI経由でファイルを直接読み書きする
  - 各チャット実行時に、ブートストラップファイルがシステムプロンプトへ必ず注入される
  - ファイルが存在しない場合は注入をスキップし、チャット実行は継続する
- 期待する挙動：
  - 編集内容は即座に次回以降のチャットコンテキストに反映される
  - 1ファイルあたり最大20,000文字まで注入される
- 画面/入出力（ある場合）：
  - モバイルアプリのサイドバーから「System Prompt」専用画面へ遷移できる
- 1画面でタブ切替し、複数ファイルを編集できる
  - タブ順序は固定（USER → IDENTITY → SOUL → TOOLS → AGENTS → HEARTBEAT → BOOTSTRAP）
  - 保存は明示的な保存ボタンで行う
  - 認証は既存のAPIキーで行う

## 4. Scope

<!-- スコープ膨張を止める -->

- 今回やる（MVP）：
  - `backend/context/` 配下の7ファイルを正本として扱う
- サイドバーから遷移できる「System Prompt」専用画面
- タブ切替による複数ファイル編集（全文）
- タブ順序は固定（USER → IDENTITY → SOUL → TOOLS → AGENTS → HEARTBEAT → BOOTSTRAP）
- 明示的な保存ボタン
- API経由でファイルを直接読み書きする
- ファイル未作成時はテンプレートを自動生成して編集画面へ誘導
  - 毎回のシステムプロンプト注入
  - 注入上限 20,000 文字/ファイル
- 今回やらない（Won’t）：
  - MEMORY.md / memory/ の長期記憶設計
  - サブエージェント向けのプロンプト最小化設計
  - ファイル差分編集や履歴管理
- 次回以降（あれば）：
  - メモリ機構の追加
  - 注入対象ファイルの動的設定

## 5. User Story Mapping

<!-- ユーザーの行動の流れで並べる。 -->
<!-- 例: 開く → 入力 → 確認 → 保存 → 後で見る/編集 -->

| Step | MVP（最低限）                                   | Nice to have           |
| ---- | ----------------------------------------------- | ---------------------- |
| 開く | サイドバーから「System Prompt」画面に遷移できる | 直近編集ファイルの復元 |
| 切替 | 固定順のタブでファイルを切替できる              | タブの並び替え         |
| 編集 | 本文を更新できる                                | 変更のプレビュー       |
| 保存 | 保存後に次回のチャットへ反映される              | 差分比較               |

## 6. Acceptance Criteria

<!-- 2〜5個。Given/When/Then推奨 -->

- Given 既存の `USER.md` がある, When アプリで本文を更新して保存する, Then 次回チャット実行時のシステムプロンプトに更新内容が注入される
- Given `SOUL.md` が未作成, When System Prompt画面を開く, Then テンプレートが自動生成され編集可能になる
- Given `SOUL.md` が存在しない, When チャットを実行する, Then 注入はスキップされ、チャットは正常に処理される
- Given 20,000文字を超える本文が保存されている, When チャットを実行する, Then 注入は20,000文字で打ち切られる

## 7. 例外・境界（必要なら）

<!-- 失敗時/空状態/上限/権限など。気になるところだけ。 -->

- 失敗時（通信/保存/権限）：保存失敗時はエラーを表示し本文は保持される
- 空状態（データ0件）：ファイルが未作成の状態でもチャットは実行できる
- 上限（文字数/件数/サイズ）：1ファイル20,000文字上限
- 既存データとの整合（互換/移行）：既存のチャット履歴への影響はなし

## 8. Non-Functional Requirements (FURPS)

<!-- 関係あるものだけ。1行でOK。 -->

- Performance：注入処理はチャット応答の体感遅延を悪化させない
- Reliability：保存した内容は失われず、次回以降の実行に必ず反映される
- Usability：モバイルから編集できることが前提
- Security/Privacy：既存のAPIキー認証を使用する
- Constraints（技術/期限/外部APIなど）：Capacitorモバイルアプリからの編集を前提

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

<!-- 各1行でOK -->

- Risk：APIキー漏洩時に改ざんリスクが高い
- Assumption：アプリは既存のAPIキーで認証される
- Issue：編集競合の解決は行わない（最新で上書き）
- Dependency：モバイルアプリ側の編集UI/編集フロー

## 10. Reference

<!-- 画像/リンク/メモなど -->

- https://github.com/clawdbot/clawdbot/blob/main/docs/concepts/system-prompt.md

## 11. 補足（決定事項）

- 正本はファイル運用とし、Git管理はしない
- systemd直起動のため、サーバーディスク上の `backend/context/` は永続として扱える
- `backend/data/chat.duckdb` と同様に、`backend/context/` を運用対象とする
