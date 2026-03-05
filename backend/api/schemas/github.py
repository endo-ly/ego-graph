"""GitHub データ API スキーマ。

GitHub Worklog データ API のレスポンスモデルを定義します。
"""

from pydantic import BaseModel


class PullRequestResponse(BaseModel):
    """Pull Request API レスポンス。

    Attributes:
        pr_event_id: PRイベントID
        pr_key: PRキー
        owner: オーナー
        repo: リポジトリ
        repo_full_name: リポジトリフルネーム
        pr_number: PR番号
        pr_id: PR ID
        action: アクション（opened, closed, merged, reopened, updated）
        state: 状態（open, closed）
        is_merged: マージされたかどうか
        title: タイトル
        labels: ラベルリスト
        base_ref: ベースブランチ
        head_ref: ヘッドブランチ
        created_at_utc: 作成日時（UTC）
        updated_at_utc: 更新日時（UTC）
        closed_at_utc: クローズ日時（UTC）
        merged_at_utc: マージ日時（UTC）
        comments_count: コメント数
        review_comments_count: レビューコメント数
        reviews_count: レビュー数
        commits_count: コミット数
        additions: 追加行数
        deletions: 削除行数
        changed_files_count: 変更ファイル数
    """

    pr_event_id: str
    pr_key: str
    owner: str
    repo: str
    repo_full_name: str
    pr_number: int
    pr_id: int | None = None
    action: str
    state: str
    is_merged: bool | None = None
    title: str | None = None
    labels: list[str] | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    created_at_utc: str | None = None
    updated_at_utc: str
    closed_at_utc: str | None = None
    merged_at_utc: str | None = None
    comments_count: int | None = None
    review_comments_count: int | None = None
    reviews_count: int | None = None
    commits_count: int | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files_count: int | None = None


class CommitResponse(BaseModel):
    """Commit API レスポンス。

    Attributes:
        commit_event_id: コミットイベントID
        owner: オーナー
        repo: リポジトリ
        repo_full_name: リポジトリフルネーム
        sha: コミットSHA
        message: コミットメッセージ
        committed_at_utc: コミット日時（UTC）
        changed_files_count: 変更ファイル数
        additions: 追加行数
        deletions: 削除行数
    """

    commit_event_id: str
    owner: str
    repo: str
    repo_full_name: str
    sha: str
    message: str | None = None
    committed_at_utc: str
    changed_files_count: int | None = None
    additions: int | None = None
    deletions: int | None = None


class RepositoryResponse(BaseModel):
    """Repository API レスポンス。

    Attributes:
        repo_id: リポジトリID
        owner: オーナー
        repo: リポジトリ
        repo_full_name: リポジトリフルネーム
        description: 説明
        is_private: プライベートかどうか
        is_fork: フォークかどうか
        archived: アーカイブ済みかどうか
        primary_language: メイン言語
        topics: トピックリスト
        stargazers_count: スター数
        forks_count: フォーク数
        open_issues_count: オープンイシュー数
        size_kb: サイズ（KB）
        created_at_utc: 作成日時（UTC）
        updated_at_utc: 更新日時（UTC）
        pushed_at_utc: プッシュ日時（UTC）
        repo_summary_text: リポジトリサマリー
        summary_source: サマリーソース
    """

    repo_id: int
    owner: str
    repo: str
    repo_full_name: str
    description: str | None = None
    is_private: bool
    is_fork: bool
    archived: bool
    primary_language: str | None = None
    topics: list[str] | None = None
    stargazers_count: int | None = None
    forks_count: int | None = None
    open_issues_count: int | None = None
    size_kb: int | None = None
    created_at_utc: str
    updated_at_utc: str
    pushed_at_utc: str | None = None
    repo_summary_text: str | None = None
    summary_source: str | None = None


class ActivityStatsResponse(BaseModel):
    """アクティビティ統計 API レスポンス。

    Attributes:
        period: 期間（日付文字列）
        prs_created: PR作成数
        prs_merged: PRマージ数
        commits_count: コミット数
        additions: 追加行数
        deletions: 削除行数
    """

    period: str
    prs_created: int
    prs_merged: int
    commits_count: int
    additions: int
    deletions: int


class RepoSummaryStatsResponse(BaseModel):
    """リポジトリ別統計 API レスポンス。

    Attributes:
        owner: オーナー
        repo: リポジトリ
        repo_full_name: リポジトリフルネーム
        prs_total: PR総数
        prs_merged: PRマージ数
        commits_total: コミット総数
        total_additions: 総追加行数
        total_deletions: 総削除行数
        last_pr_updated_at: 最後のPR更新日時（UTC）
        last_commit_at: 最後のコミット日時（UTC）
    """

    owner: str
    repo: str
    repo_full_name: str
    prs_total: int
    prs_merged: int
    commits_total: int
    total_additions: int
    total_deletions: int
    last_pr_updated_at: str | None = None
    last_commit_at: str | None = None
