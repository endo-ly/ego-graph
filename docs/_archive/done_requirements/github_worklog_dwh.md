# 要件定義: GitHub作業ログ取り込み（EgoGraphデータソース）

## 1. Summary

- **やりたいこと**: GitHub APIで取得した作業ログを、EgoGraphの1データソースとしてDWHへ日次蓄積する
- **理由**: 作業を振り返るための土台データを継続的に収集し、モチベーション維持につなげる
- **対象**: まずは保存レイヤー（collector/transform/storage + state）。可視化/集計APIは別要件で実施
- **優先**: 体験より先に、欠損の少ない保存仕様と運用安定性を優先

---

## 2. Purpose (WHY)

### いま困っていること
- GitHub上の活動がイベント単位で散在し、時系列で一貫して振り返りにくい
- EgoGraphの他データソース（Spotify等）と同じ保存パターンで統合するための定義が不足している
- GitHubデータで「何を保存し、何を保存しないか」の境界が曖昧で、取り込み仕様を確定しにくい

### できるようになったら嬉しいこと
- 毎日自動で活動データが蓄積され、将来の任意フォーマットの振り返り出力に再利用できる
- 活動履歴が欠損なく再計算可能な形で保存される
- 取得対象の拡張（Actions、他サービス連携など）を壊さず段階追加できる

### 成功すると何が変わるか
- 「まず保存」方針で、データソース追加を継続できる共通土台ができる
- GitHubログがEgoGraph全体のライフログの一部として扱え、後続の横断分析に再利用できる

---

## 3. Requirements (WHAT)

### 機能要件

#### 3.1 GitHub活動ログの日次収集
- GitHub APIから対象期間の活動データを日次バッチで取得する
- 増分取得を基本とし、再実行で重複保存しない
- 初回はバックフィル可能な設計にする（期間指定再取り込み）
- 収集対象は**個人所有Repoのみ**とし、会社/組織Repoは対象外にする

#### 3.2 MVP対象データ
- Pull Requests（時系列イベント。作成/更新/マージ/クローズ、作成者、base/head、ラベル）
- Commits（sha、author、message、changed_files_count、additions、deletions などのメタ）
- Repository Master（repo属性 + 自然言語サマリー）

#### 3.3 Diff保持ポリシー（MVP）
- **MVPではPR/Commitの生diff本文は保持しない**
- 代わりに変更量メタデータ（files changed, additions, deletions）を保持する
- Commit messageはそのまま保持する
- PRレビュー本文は保持しない（PRイベント上のレビュー件数メタのみ保持）
- 必要時に再取得できるよう、再フェッチに必要な識別子（repo, number, sha）を保持する

#### 3.4 データ保存レイヤー
- Raw（APIレスポンスJSON）とCurated（分析用Parquet）の二層保存
- Rawは取得時点の監査・再処理のため保持、Curatedは分析用スキーマを提供
- 日付パーティションで保存し、期間クエリを高速化する
- ingest既存方針（Idempotent + Stateful）に従い、state cursorで増分取り込みする

#### 3.5 データ品質管理
- 必須キー欠損時はレコードを隔離し、ジョブ全体は継続
- 取り込み統計（取得件数、新規件数、重複件数、失敗件数）をログ出力する

### R2ファイル構造（MVPで固定）

```text
s3://{bucket}/
├── raw/github/
│   ├── pull_requests/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
│   └── commits/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
│
├── events/github/
│   ├── pull_requests/year={YYYY}/month={MM}/{uuid}.parquet
│   └── commits/year={YYYY}/month={MM}/{uuid}.parquet
│
├── master/github/
│   └── repositories/{owner}/{repo}.parquet
│
└── state/
    └── github_worklog_ingest_state.json
```

### 保存形式（MVPで固定）
- Raw: JSON（APIレスポンスの監査/再処理用、UTF-8）
- Curated: Parquet（分析用。PR/CommitはHiveパーティション `year=YYYY/month=MM`）
- Master: Parquet（`master/github/repositories/{owner}/{repo}.parquet` のみ、非時系列）
- State: JSON（増分カーソル）

### データカラム定義（Curated）

#### 1) PRイベント（events/github/pull_requests/）
```sql
pr_event_id          VARCHAR PRIMARY KEY  -- repo + pr_number + updated_at + state のハッシュ
pr_key               VARCHAR NOT NULL     -- repo_full_name + pr_number のハッシュ
source               VARCHAR NOT NULL     -- 固定値: 'github'
owner                VARCHAR NOT NULL
repo                 VARCHAR NOT NULL
repo_full_name       VARCHAR NOT NULL
pr_number            INTEGER NOT NULL
pr_id                BIGINT
action               VARCHAR NOT NULL     -- opened, closed, merged, reopened, updated
state                VARCHAR NOT NULL     -- open, closed
is_merged            BOOLEAN
title                VARCHAR
labels               VARCHAR[]
base_ref             VARCHAR
head_ref             VARCHAR
created_at_utc       TIMESTAMP
updated_at_utc       TIMESTAMP NOT NULL
closed_at_utc        TIMESTAMP
merged_at_utc        TIMESTAMP
comments_count       INTEGER              -- PRコメント件数（本文は保持しない）
review_comments_count INTEGER             -- PR Reviewコメント件数（本文は保持しない）
reviews_count        INTEGER              -- PRに紐づくレビュー件数
commits_count        INTEGER
additions            INTEGER
deletions            INTEGER
changed_files_count  INTEGER
ingested_at_utc      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

`PRイベント` の運用方針（MVP）:
- 日次実行で取得したPRスナップショットを時系列イベントとして追記保存する
- 保存先は `events/github/pull_requests/year=YYYY/month=MM/` の月次パーティション
- `pr_event_id` で重複排除し、再実行時も同一イベントは重複保存しない
#### 2) Commitイベント（events/github/commits/）
```sql
commit_event_id      VARCHAR PRIMARY KEY  -- repo + sha
source               VARCHAR NOT NULL     -- 固定値: 'github'
owner                VARCHAR NOT NULL
repo                 VARCHAR NOT NULL
repo_full_name       VARCHAR NOT NULL
sha                  VARCHAR NOT NULL
message              VARCHAR              -- そのまま保持
committed_at_utc     TIMESTAMP
changed_files_count  INTEGER
additions            INTEGER
deletions            INTEGER
ingested_at_utc      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

#### 3) Repository Master（master/github/repositories/{owner}/{repo}.parquet）
```sql
repo_id              BIGINT PRIMARY KEY
source               VARCHAR NOT NULL     -- 固定値: 'github'
owner                VARCHAR NOT NULL
repo                 VARCHAR NOT NULL
repo_full_name       VARCHAR NOT NULL
description          VARCHAR
homepage_url         VARCHAR
is_private           BOOLEAN NOT NULL
is_fork              BOOLEAN NOT NULL
archived             BOOLEAN NOT NULL
default_branch       VARCHAR
primary_language     VARCHAR
topics               VARCHAR[]
stargazers_count     INTEGER
forks_count          INTEGER
open_issues_count    INTEGER
size_kb              INTEGER
created_at_utc       TIMESTAMP
updated_at_utc       TIMESTAMP
pushed_at_utc        TIMESTAMP
repo_summary_text    VARCHAR              -- 自然言語サマリー（短文、任意）
summary_source       VARCHAR              -- template, manual, llm, empty
summary_updated_at_utc TIMESTAMP
```

`repo_summary_text` の運用方針（MVP）:
- 1〜3文の短文サマリーを保持してよい（目的・主要機能・技術要素）
- 初期値は `description` と `topics` から生成可能な範囲で作成
- LLM生成を使う場合も本文長を制限し、機密情報を含めない

URLの扱い（MVP）:
- GitHubの `html_url` / `api_url` は保存しない
- 必要時に `repo_full_name + pr_number`（PR）または `repo_full_name + sha`（Commit）から導出する

### 期待する挙動

1. **通常日次実行**
    - 前回カーソル以降のイベントを取得
    - PR/Commitはeventsへ追記、Repository Masterはmasterを更新
    - 処理成功後にカーソル更新

2. **再実行（同日）**
   - 同一イベントは冪等で重複保存されない
   - 取り込み統計だけ更新される

3. **失敗時**
   - API失敗はリトライ後、失敗情報をログ/メタに残して終了
   - カーソルは全体成功時のみ進める

### 画面/入出力
- 本要件でUIは対象外
- 入力: GitHub API認証情報、対象owner/repo（個人repo限定）、取得期間
- 出力: `raw/github/*` JSON、`events/github/pull_requests/*` Parquet、`events/github/commits/*` Parquet、`master/github/repositories/*/*.parquet`、`state/github_worklog_ingest_state.json`

---

## 4. Scope

### 今回やる（MVP）
- 保存仕様の確定（データ粒度、保持方針、更新頻度、冪等性）
- 個人所有Repoのみを収集対象にするためのフィルタ条件定義
- PR/Commitメタデータの取得と保存（コメント本文は除外）
- PRは時系列イベントとして保存（更新履歴を保持）
- Repository Masterの取得と更新（1 repo = 1 masterファイル）
- owner判定は「GitHub login == repo owner」の一致で制御
- 日次バッチ + 増分カーソル + 再実行安全性
- Raw/Events/Master/Stateの4系統保存

### 今回やらない（Won't）
- Wrapped風サマリ生成、ランキング表示、APIレスポンス整形
- Diff本文の長期保存
- 高度な品質スコアリング（レビュー品質、意味解析）
- 会社/組織Repoのデータ収集

### 次回以降
- 表示/分析API（backend）
- 指標定義（習慣化スコア、継続率、集中時間帯）
- 必要に応じた短期diff保持（例: 30日TTL）

---

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 対象を決める | owner/repo（個人所有のみ）と期間を設定できる | ユーザーごとのプロファイル切替 |
| 取得する | 日次でPR/Commitを取得 | webhook併用で準リアルタイム化 |
| 正規化する | 共通イベントスキーマに変換 | 活動タイプの自動クラスタリング |
| 保存する | Raw + Events(PR/Commit) + Master(Repository) + cursorを保存 | 品質異常の自動通知 |
| 再処理する | 期間指定で再取り込み可能 | ワンクリック再集計ジョブ |

---

## 6. Acceptance Criteria

- Given 前回カーソルが存在する, When 日次ジョブを実行する, Then カーソル以降のイベントだけが取得される
- Given 同じ期間でジョブを再実行する, When 既存イベントが再取得される, Then Curatedに重複レコードが発生しない
- Given PR/Commitを取得する, When 保存処理を行う, Then diff本文は保存されず変更量メタデータのみ保存される
- Given Commitを取得する, When 保存処理を行う, Then commit messageと変更量メタ（files/additions/deletions）が保存される
- Given PRを取得する, When 保存処理を行う, Then PRイベントにレビュー件数（reviews_count）が保存される
- Given 同一PRが後日更新される, When 保存処理を行う, Then 新しいPRイベントが追記され、既存イベントと重複しない
- Given PRレビュー本文を取得できる, When 保存処理を行う, Then 本文は保存対象外となる
- Given 取り込み処理が成功する, When R2を確認する, Then Rawは`raw/github/*/*.json`、PR/Commitは`events/github/*/*.parquet`に保存される
- Given Repository情報を取得する, When 保存処理を行う, Then `master/github/repositories/{owner}/{repo}.parquet`に保存/更新される
- Given Repositoryサマリーを生成する, When 保存処理を行う, Then `repo_summary_text`に1〜3文で保存される
- Given Curated保存が行われる, When Parquetを読み込む, Then `year=YYYY/month=MM`のHiveパーティションで参照できる
- Given 会社/組織Repoが対象候補に含まれる, When 収集ジョブを実行する, Then そのRepoは収集対象から除外される
- Given ownerが自分のGitHub loginと一致しないRepo, When 収集対象判定を行う, Then そのRepoは除外される
- Given APIの一部取得が失敗する, When リトライ上限に達する, Then 失敗内容がアプリケーションログに記録されカーソルは進まない
- Given 対象期間を指定して再取り込みする, When ジョブ完了する, Then 指定期間のRaw/Curatedが再生成される

---

## 7. 例外・境界

- 失敗時（通信/保存/権限）: レート制限・認可エラー・タイムアウトはリトライし、最終失敗はアプリケーションログに記録
- 空状態（データ0件）: 正常終了し、0件実行としてアプリケーションログに記録
- 上限（文字数/件数/サイズ）: APIページネーション上限に達した場合は継続取得し、未取得が残る場合は次回へ繰越
- 既存データとの整合（互換/移行）: スキーマ変更時はバージョン列で互換管理し、旧データを破壊しない

---

## 8. Non-Functional Requirements (FURPS)

- Performance: 日次ジョブは対象規模（個人利用想定）で運用可能な実行時間に収まる
- Reliability: 失敗時に部分結果と原因が追跡でき、再実行で復旧可能
- Usability: 後続分析側が利用しやすい一貫スキーマを提供
- Security/Privacy: トークンを安全に管理し、diff/コメント本文を保存せず、会社/組織Repoを収集しない
- Constraints（技術/期限/外部APIなど）: GitHub API制限、対象repo権限、日次バッチ運用
- Data Retention: Raw JSONは無期限保持

---

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

- Risk: GitHub APIレート制限やスキーマ変更で取り込みが不安定になる
- Assumption: モチベ維持目的では本文全文よりメタデータ中心でも価値を出せる。出力形式は週次/月次に固定しない
- Assumption: モチベ維持目的ではdiff本文なしでも、commit message + 変更量メタで十分な基礎データになる
- Assumption: レビューはPR単位の件数メタのみで当面の振り返り要件を満たせる
- Issue: diff本文未保持により、一部の深掘り分析は後から再取得が必要
- Dependency: GitHub API、R2保存基盤、既存ingestパイプライン規約

---

## 10. Reference

- `.github/ISSUE_TEMPLATE/requirements.md`
- `ingest/README.md`
- `docs/10.architecture/1002_data_model.md`

---

## 補足（今回の暫定合意）

- 収集頻度: 日次バッチ
- 優先価値: モチベ維持
- 対象フェーズ: 保存仕様のみ（出力/可視化は別要件）
- diff保持: MVPは本文非保持、メタデータ保持
- commit保持: messageはそのまま保持、ファイル数/追加行数/削除行数まで保持
- review保持: PRイベント上の件数メタのみ（本文不要）
- PR保持: 時系列イベント（主キーは pr_event_id、PR識別は pr_key）
- issue: MVP対象外（Issue運用なし）
- repository master: `master/github/repositories/{owner}/{repo}.parquet`（非時系列）
- repository summary: 自然言語の短文（1〜3文）を保持
- 収集スコープ: 自分のRepoのみ（会社/組織Repoは除外）
- 判定方法: GitHub login == repo owner
- Raw保持: 無期限
- 初回バックフィル: 過去1年
- 出力方針: 週次・月次サマリに固定しない（将来決定）
