# GitHub データソース

## データタイプ判定

- **タイプ**: 構造化ログ
- **主用途**: DuckDB分析

---

## 1. 概要

### 1.1 データの性質

| 項目 | 値 |
|---|---|
| **タイプ** | 構造化ログ |
| **粒度** | Atomic (イベント単位) |
| **更新頻度** | 日次 |
| **センシティビティ** | Medium (公開リポジトリは Low) |
| **主な用途** | 分析（DuckDB） |

### 1.2 概要説明

GitHubのコミット履歴、Pull Request、Issueなどのアクティビティログを取り込み、開発活動の分析を実現する。

---

## 2. データフロー全体像

```
[GitHub API]
         ↓
    [Collector: GitHub PAT認証でデータ取得]
         ↓
    [Transform: 正規化・イベント単位に変換]
         ↓
    [Storage: R2へ保存]
         ├── Raw JSON (監査用)
         └── Parquet (分析用)
         ↓
    [DuckDB: マウント・分析]
```

---

## 3. 入力データ構造

### 3.1 データ取得元

| 項目 | 説明 |
|---|---|
| **取得方法** | API |
| **API** | GitHub REST API |
| **認証方式** | Personal Access Token (PAT) |
| **必要なスコープ** | `repo`, `read:user` |

### 3.2 対象データタイプ

| データタイプ | 説明 | 取得エンドポイント |
|---|---|---|
| commits | コミット履歴 | `GET /repos/{owner}/{repo}/commits` |
| issues | Issue 作成・更新 | `GET /repos/{owner}/{repo}/issues` |
| pull_requests | PR 作成・更新 | `GET /repos/{owner}/{repo}/pulls` |
| reviews | PR レビュー | `GET /repos/{owner}/{repo}/pulls/{pull_number}/reviews` |
| workflow_runs | GitHub Actions 実行履歴 | `GET /repos/{owner}/{repo}/actions/runs` |

---

## 4. Parquetスキーマ

### 4.1 Commit イベントスキーマ

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `commit_event_id` | STRING | 一意識別子 | `{repo_full_name}:{sha}` |
| `source` | STRING | データソース | 固定値: `github` |
| `owner` | STRING | リポジトリオーナー | APIレスポンス |
| `repo` | STRING | リポジトリ名 | APIレスポンス |
| `repo_full_name` | STRING | リポジトリフルネーム | `{owner}/{repo}` |
| `sha` | STRING | コミットハッシュ | APIレスポンス |
| `message` | STRING | コミットメッセージ | APIレスポンス |
| `committed_at_utc` | TIMESTAMP | コミット時刻 (UTC) | APIレスポンス |
| `changed_files_count` | INT | 変更ファイル数 | APIレスポンス |
| `additions` | INT | 追加行数 | APIレスポンス |
| `deletions` | INT | 削除行数 | APIレスポンス |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 (UTC) | システム生成 |

### 4.2 Pull Request イベントスキーマ

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `pr_event_id` | STRING | 一意識別子 | ハッシュ値 |
| `pr_key` | STRING | PRユニークキー | ハッシュ値 |
| `source` | STRING | データソース | 固定値: `github` |
| `owner` | STRING | リポジトリオーナー | APIレスポンス |
| `repo` | STRING | リポジトリ名 | APIレスポンス |
| `repo_full_name` | STRING | リポジトリフルネーム | `{owner}/{repo}` |
| `pr_number` | INT | PR番号 | APIレスポンス |
| `pr_id` | INT | GitHub PR ID | APIレスポンス |
| `action` | STRING | アクション種別 | `opened`, `updated`, `closed`, `merged`, `reopened` |
| `state` | STRING | PR状態 | `open`, `closed` |
| `is_merged` | BOOLEAN | マージ済みフラグ | APIレスポンス |
| `title` | STRING | PRタイトル | APIレスポンス |
| `labels` | VARCHAR[] | ラベル一覧 | APIレスポンス |
| `base_ref` | STRING | マージ先ブランチ | APIレスポンス |
| `head_ref` | STRING | マージ元ブランチ | APIレスポンス |
| `created_at_utc` | TIMESTAMP | 作成時刻 (UTC) | APIレスポンス |
| `updated_at_utc` | TIMESTAMP | 更新時刻 (UTC) | APIレスポンス |
| `closed_at_utc` | TIMESTAMP | クローズ時刻 (UTC) | APIレスポンス |
| `merged_at_utc` | TIMESTAMP | マージ時刻 (UTC) | APIレスポンス |
| `comments_count` | INT | コメント数 | APIレスポンス |
| `review_comments_count` | INT | レビューコメント数 | APIレスポンス |
| `reviews_count` | INT | レビュー数 | APIレスポンス |
| `commits_count` | INT | コミット数 | APIレスポンス |
| `additions` | INT | 追加行数 | APIレスポンス |
| `deletions` | INT | 削除行数 | APIレスポンス |
| `changed_files_count` | INT | 変更ファイル数 | APIレスポンス |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 (UTC) | システム生成 |

### 4.3 パーティション

- **パーティションキー**: `year`, `month`
- **理由**: 時系列データのクエリ効率向上

---

## 5. R2保存先

### 5.1 ディレクトリ構造

```text
s3://ego-graph/
  ├── events/github/
  │   ├── commits/
  │   │   └── year=YYYY/
  │   │       └── month=MM/
  │   │           └── {uuid}.parquet
  │   └── pull_requests/
  │       └── year=YYYY/
  │           └── month=MM/
  │               └── {uuid}.parquet
  ├── raw/github/
  │   └── {timestamp}.json
  └── state/
      └── github_worklog_ingest_state.json
```

### 5.2 保存パス例

- **Commits**: `s3://ego-graph/events/github/commits/year=2024/month=01/abc123.parquet`
- **Pull Requests**: `s3://ego-graph/events/github/pull_requests/year=2024/month=01/def456.parquet`
- **Raw**: `s3://ego-graph/raw/github/2024-01-01T120000.json`
- **State**: `s3://ego-graph/state/github_worklog_ingest_state.json`

## 6. 検索・活用シナリオ

- **定量分析**: コミット数、PR数、変更行数の集計
- **事実列挙**: 特定期間の活動履歴、マージ済みPR一覧
- **傾向把握**: 開発活動の傾向、よく作業するリポジトリ

---
## 8. Semantification戦略

※ 将来的にQdrantへ保存する場合に使用

### 8.1 自然言語化テンプレート

| イベントタイプ | テンプレート |
|---|---|
| commit | `{repository}で{message}をコミットした` |
| issue_open | `{repository}でIssue #{number}: {title}を作成した` |
| issue_close | `{repository}でIssue #{number}: {title}をクローズした` |
| pr_open | `{repository}でPR #{number}: {title}を作成した` |
| pr_merge | `{repository}でPR #{number}: {title}をマージした` |
| review | `{repository}のPR #{pr_number}をレビューした` |
| workflow_success | `{repository}でワークフロー{workflow_name}が成功した` |
| workflow_failure | `{repository}でワークフロー{workflow_name}が失敗した` |

---

## 11. 実装時の考慮事項

### 11.1 ワークフロー

- **ワークフロー**: `job-ingest-github.yml`
- **実行タイミング**: Cron (1日1回: 15:00 UTC = 00:00 JST 深夜)
- **増分取り込み**: R2 内のカーソル (`state/github_worklog_ingest_state.json`) で管理

### 11.2 ディレクトリ構成

```text
ingest/github/
├── __init__.py
├── main.py           # エントリーポイント
├── collector.py      # GitHub API データ取得
├── transform.py      # データ変換・正規化
├── storage.py        # R2 アップロード
├── pipeline.py       # ETL パイプライン統合
└── compact.py        # Parquet 最適化
```

### 11.3 認証

- **認証方式**: GitHub Personal Access Token (PAT)
- **必要なスコープ**: `repo`, `read:user`
- **環境変数**: `GITHUB_PAT`, `GITHUB_LOGIN`

### 11.4 将来拡張

- Issue、レビュー、ワークフロー実行履歴の取り込み
- 複数リポジトリの一括監視
- コミットメッセージからの意図抽出（LLM連携）

---

## 13. 次のステップ

### 実装状況

- [x] データ取得 (commits, pull_requests)
- [x] Parquet保存
- [x] DuckDBマウント
- [x] テスト完了

### 未実装機能

- [ ] Issues データの取り込み
- [ ] Reviews データの取り込み
- [ ] Workflow Runs データの取り込み
- [ ] Qdrantへの保存（将来検討）

---

## 参考

- [GitHub REST API Documentation](https://docs.github.com/rest)
- [Ingest 共通アーキテクチャ](./README.md)
- [データ戦略](../01-overview/data-strategy.md)
