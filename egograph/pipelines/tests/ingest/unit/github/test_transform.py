"""GitHub Worklog Transformモジュールのテスト."""

from pipelines.sources.github.transform import (
    _generate_pr_key,
    _is_personal_repo,
    generate_repo_summary,
    transform_commit,
    transform_commits_to_events,
    transform_prs_to_master,
    transform_pull_request,
    transform_repository,
)


class TestGeneratePrKey:
    """PRキー生成関数のテスト."""

    def test_generate_pr_key_basic(self):
        """基本パターンでPRキーを生成する。"""
        # Arrange
        repo_full_name = "owner/repo"
        pr_number = 123

        # Act
        key = _generate_pr_key(repo_full_name, pr_number)

        # Assert
        assert key is not None
        assert isinstance(key, str)
        assert len(key) > 0

    def test_generate_pr_key_consistency(self):
        """同じ入力で同じキーが生成されることを検証する。"""
        # Arrange
        repo_full_name = "owner/repo"
        pr_number = 123

        # Act
        key1 = _generate_pr_key(repo_full_name, pr_number)
        key2 = _generate_pr_key(repo_full_name, pr_number)

        # Assert
        assert key1 == key2

    def test_generate_pr_key_different_for_different_prs(self):
        """異なるPRで異なるキーが生成されることを検証する。"""
        # Arrange
        repo_full_name = "owner/repo"

        # Act
        key1 = _generate_pr_key(repo_full_name, 123)
        key2 = _generate_pr_key(repo_full_name, 456)

        # Assert
        assert key1 != key2


class TestIsPersonalRepo:
    """個人所有Repo判定関数のテスト."""

    def test_personal_repo_true(self):
        """個人所有Repoの場合にTrueを返す。"""
        # Arrange
        repo = {"owner": {"login": "myusername"}}
        github_login = "myusername"

        # Act
        result = _is_personal_repo(repo, github_login)

        # Assert
        assert result is True

    def test_personal_repo_false(self):
        """他人所有Repoの場合にFalseを返す。"""
        # Arrange
        repo = {"owner": {"login": "otheruser"}}
        github_login = "myusername"

        # Act
        result = _is_personal_repo(repo, github_login)

        # Assert
        assert result is False

    def test_personal_repo_missing_owner(self):
        """owner情報が欠損している場合にFalseを返す。"""
        # Arrange
        repo = {}
        github_login = "myusername"

        # Act
        result = _is_personal_repo(repo, github_login)

        # Assert
        assert result is False

    def test_personal_repo_missing_login(self):
        """ownerのloginが欠損している場合にFalseを返す。"""
        # Arrange
        repo = {"owner": {}}
        github_login = "myusername"

        # Act
        result = _is_personal_repo(repo, github_login)

        # Assert
        assert result is False


class TestTransformPullRequest:
    """PR変換関数のテスト."""

    def test_transform_pr_basic(self):
        """基本パターンでPRを変換する。"""
        # Arrange
        pr = {
            "id": 123456,
            "number": 1,
            "state": "open",
            "title": "Test PR",
            "user": {"login": "myusername"},
            "head": {
                "ref": "feature-branch",
                "repo": {
                    "owner": {"login": "myusername"},
                    "name": "repo",
                    "full_name": "myusername/repo",
                },
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "labels": [{"name": "bug"}],
        }
        github_login = "myusername"

        # Act
        result = transform_pull_request(pr, github_login)

        # Assert
        assert result is not None
        assert result["pr_number"] == 1
        assert result["state"] == "open"
        assert result["title"] == "Test PR"
        assert result["owner"] == "myusername"
        assert result["base_ref"] == "main"
        assert result["head_ref"] == "feature-branch"
        assert result["labels"] == ["bug"]
        assert result["action"] == "updated"

    def test_transform_pr_merged(self):
        """マージ済みPRを変換する。"""
        # Arrange
        pr = {
            "id": 123456,
            "number": 1,
            "state": "closed",
            "merged": True,
            "merged_at": "2024-01-02T00:00:00Z",
            "user": {"login": "myusername"},
            "head": {
                "ref": "feature",
                "repo": {
                    "owner": {"login": "myusername"},
                    "name": "repo",
                    "full_name": "myusername/repo",
                },
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        github_login = "myusername"

        # Act
        result = transform_pull_request(pr, github_login)

        # Assert
        assert result is not None
        assert result["state"] == "closed"
        assert result["is_merged"] is True
        assert result["merged_at_utc"] == "2024-01-02T00:00:00Z"
        assert result["action"] == "merged"

    def test_transform_pr_opened_action_when_created_equals_updated(self):
        """作成時刻と更新時刻が同一ならopenedになる。"""
        pr = {
            "id": 123456,
            "number": 1,
            "state": "open",
            "user": {"login": "myusername"},
            "head": {
                "ref": "feature",
                "repo": {
                    "owner": {"login": "myusername"},
                    "name": "repo",
                    "full_name": "myusername/repo",
                },
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
        }

        result = transform_pull_request(pr, "myusername")

        assert result is not None
        assert result["action"] == "opened"

    def test_transform_pr_reopened_action_when_closed_at_exists(self):
        """open状態だがclosed_atがある場合はreopenedになる。"""
        pr = {
            "id": 123456,
            "number": 1,
            "state": "open",
            "closed_at": "2024-01-02T00:00:00Z",
            "user": {"login": "myusername"},
            "head": {
                "ref": "feature",
                "repo": {
                    "owner": {"login": "myusername"},
                    "name": "repo",
                    "full_name": "myusername/repo",
                },
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-03T00:00:00Z",
            "labels": [],
        }

        result = transform_pull_request(pr, "myusername")

        assert result is not None
        assert result["action"] == "reopened"

    def test_transform_pr_non_personal_repo(self):
        """個人所有でないRepoの場合にNoneを返す。"""
        # Arrange
        pr = {
            "id": 123456,
            "number": 1,
            "state": "open",
            "user": {"login": "otheruser"},
            "head": {
                "repo": {
                    "owner": {"login": "otheruser"},
                    "name": "repo",
                    "full_name": "otheruser/repo",
                }
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        github_login = "myusername"

        # Act
        result = transform_pull_request(pr, github_login)

        # Assert
        assert result is None

    def test_transform_pr_with_missing_optional_fields(self):
        """オプションナルフィールドが欠損している場合にNoneを設定する。"""
        # Arrange
        pr = {
            "id": 123456,
            "number": 1,
            "state": "open",
            "user": {"login": "myusername"},
            "head": {
                "repo": {
                    "owner": {"login": "myusername"},
                    "name": "repo",
                    "full_name": "myusername/repo",
                },
                "ref": "feature",
            },
            "base": {"ref": "main"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        github_login = "myusername"

        # Act
        result = transform_pull_request(pr, github_login)

        # Assert
        assert result is not None
        assert result["title"] is None
        assert result["closed_at_utc"] is None
        assert result["merged_at_utc"] is None
        assert result["labels"] == []


class TestTransformCommit:
    """Commit変換関数のテスト."""

    def test_transform_commit_basic(self):
        """基本パターンでCommitを変換する。"""
        # Arrange
        commit = {
            "sha": "abc123",
            "commit": {
                "message": "Test commit",
                "author": {"date": "2024-01-01T00:00:00Z"},
            },
            "stats": {
                "additions": 10,
                "deletions": 5,
                "total": 15,
            },
        }
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commit(commit, repo_full_name)

        # Assert
        assert result is not None
        assert result["sha"] == "abc123"
        assert result["message"] == "Test commit"
        assert result["repo_full_name"] == "myusername/repo"
        assert result["additions"] == 10
        assert result["deletions"] == 5
        assert result["changed_files_count"] is None

    def test_transform_commit_with_files_array_sets_changed_files_count(self):
        """files配列がある場合、changed_files_countをファイル数で保持する。"""
        # Arrange
        commit = {
            "sha": "abc123",
            "commit": {
                "message": "Test commit",
                "author": {"date": "2024-01-01T00:00:00Z"},
            },
            "stats": {
                "additions": 10,
                "deletions": 5,
                "total": 15,
            },
            "files": [{"filename": "a.py"}, {"filename": "b.py"}],
        }
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commit(commit, repo_full_name)

        # Assert
        assert result is not None
        assert result["changed_files_count"] == 2

    def test_transform_commit_with_missing_fields(self):
        """必須フィールドが欠損している場合に該当フィールドをNoneにする。"""
        # Arrange
        commit = {
            "sha": "abc123",
            "commit": {"message": "Test commit"},
            # statsが欠損
        }
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commit(commit, repo_full_name)

        # Assert
        assert result is not None
        assert result["sha"] == "abc123"
        assert result["message"] == "Test commit"
        assert result["additions"] is None
        assert result["deletions"] is None
        assert result["changed_files_count"] is None
        assert result["committed_at_utc"] is None

    def test_transform_commit_missing_sha(self):
        """shaが欠損している場合にNoneを返す。"""
        # Arrange
        commit = {"commit": {"message": "Test commit"}}
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commit(commit, repo_full_name)

        # Assert
        assert result is None

    def test_transform_commit_empty_message(self):
        """メッセージが空の場合に空文字列を保存する。"""
        # Arrange
        commit = {
            "sha": "abc123",
            "commit": {},
        }
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commit(commit, repo_full_name)

        # Assert
        assert result is not None
        assert result["sha"] == "abc123"
        assert result["message"] is None


class TestTransformRepository:
    """Repository変換関数のテスト."""

    def test_transform_repo_basic(self):
        """基本パターンでRepositoryを変換する。"""
        # Arrange
        repo = {
            "id": 123456,
            "owner": {"login": "myusername"},
            "name": "repo",
            "full_name": "myusername/repo",
            "description": "Test repository",
            "private": False,
            "fork": False,
            "archived": False,
            "default_branch": "main",
            "language": "Python",
            "topics": ["test", "example"],
            "stargazers_count": 10,
            "forks_count": 5,
            "open_issues_count": 2,
            "size": 1024,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "pushed_at": "2024-01-02T00:00:00Z",
        }
        github_login = "myusername"

        # Act
        result = transform_repository(repo, github_login)

        # Assert
        assert result is not None
        assert result["repo_id"] == 123456
        assert result["owner"] == "myusername"
        assert result["repo"] == "repo"
        assert result["repo_full_name"] == "myusername/repo"
        assert result["description"] == "Test repository"
        assert result["is_private"] is False
        assert result["is_fork"] is False
        assert result["archived"] is False
        assert result["primary_language"] == "Python"
        assert result["topics"] == ["test", "example"]

    def test_transform_repo_non_personal(self):
        """個人所有でないRepoの場合にNoneを返す。"""
        # Arrange
        repo = {
            "id": 123456,
            "owner": {"login": "otheruser"},
            "name": "repo",
            "full_name": "otheruser/repo",
        }
        github_login = "myusername"

        # Act
        result = transform_repository(repo, github_login)

        # Assert
        assert result is None

    def test_transform_repo_with_missing_optional_fields(self):
        """オプショナルフィールドが欠損している場合にNoneを設定する。"""
        # Arrange
        repo = {
            "id": 123456,
            "owner": {"login": "myusername"},
            "name": "repo",
            "full_name": "myusername/repo",
            "private": False,
            "fork": False,
            "archived": False,
        }
        github_login = "myusername"

        # Act
        result = transform_repository(repo, github_login)

        # Assert
        assert result is not None
        assert result["description"] is None
        assert result["homepage_url"] is None
        assert result["default_branch"] is None
        assert result["primary_language"] is None
        assert result["topics"] == []


class TestTransformPrsToMaster:
    """PRリスト一括変換関数のテスト."""

    def test_transform_prs_to_master_basic(self):
        """基本パターンでPRリストを変換する。"""
        # Arrange
        prs = [
            {
                "id": 123456,
                "number": 1,
                "state": "open",
                "user": {"login": "myusername"},
                "head": {
                    "repo": {
                        "owner": {"login": "myusername"},
                        "name": "repo",
                        "full_name": "myusername/repo",
                    },
                    "ref": "feature",
                },
                "base": {"ref": "main"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "labels": [],
            },
            {
                "id": 789012,
                "number": 2,
                "state": "closed",
                "user": {"login": "otheruser"},
                "head": {
                    "repo": {
                        "owner": {"login": "otheruser"},
                        "name": "other-repo",
                        "full_name": "otheruser/other-repo",
                    },
                    "ref": "feature",
                },
                "base": {"ref": "main"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "labels": [],
                "merged": False,
            },
        ]
        github_login = "myusername"

        # Act
        result = transform_prs_to_master(prs, github_login)

        # Assert
        assert len(result) == 1
        assert result[0]["pr_number"] == 1
        assert result[0]["owner"] == "myusername"

    def test_transform_prs_to_master_empty_list(self):
        """空リストの場合に空リストを返す。"""
        # Arrange
        prs = []
        github_login = "myusername"

        # Act
        result = transform_prs_to_master(prs, github_login)

        # Assert
        assert result == []

    def test_transform_prs_to_master_all_non_personal(self):
        """全てのPRが個人所有でない場合に空リストを返す。"""
        # Arrange
        prs = [
            {
                "id": 123456,
                "number": 1,
                "state": "open",
                "user": {"login": "otheruser"},
                "head": {
                    "repo": {
                        "owner": {"login": "otheruser"},
                        "name": "repo",
                        "full_name": "otheruser/repo",
                    },
                    "ref": "feature",
                },
                "base": {"ref": "main"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "labels": [],
            },
        ]
        github_login = "myusername"

        # Act
        result = transform_prs_to_master(prs, github_login)

        # Assert
        assert result == []


class TestTransformCommitsToEvents:
    """Commitリスト一括変換関数のテスト."""

    def test_transform_commits_to_events_basic(self):
        """基本パターンでCommitリストを変換する。"""
        # Arrange
        commits = [
            {
                "sha": "abc123",
                "commit": {
                    "message": "First commit",
                    "author": {"date": "2024-01-01T00:00:00Z"},
                },
                "stats": {"additions": 10, "deletions": 5, "total": 15},
            },
            {
                "sha": "def456",
                "commit": {
                    "message": "Second commit",
                    "author": {"date": "2024-01-02T00:00:00Z"},
                },
                "stats": {"additions": 20, "deletions": 10, "total": 30},
            },
        ]
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commits_to_events(commits, repo_full_name)

        # Assert
        assert len(result) == 2
        assert result[0]["sha"] == "abc123"
        assert result[1]["sha"] == "def456"

    def test_transform_commits_to_events_with_missing_fields(self):
        """フィールド欠損があるCommitも他の有効フィールドは保持する。"""
        # Arrange
        commits = [
            {
                "sha": "abc123",
                "commit": {"message": "Valid commit"},
                # statsが欠損
            },
            {
                "sha": "def456",
                "commit": {"message": "Another valid commit"},
                "stats": {"additions": 10, "deletions": 5, "total": 15},
            },
        ]
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commits_to_events(commits, repo_full_name)

        # Assert
        assert len(result) == 2
        assert result[0]["sha"] == "abc123"
        assert result[0]["additions"] is None
        assert result[1]["sha"] == "def456"
        assert result[1]["additions"] == 10

    def test_transform_commits_to_events_empty_list(self):
        """空リストの場合に空リストを返す。"""
        # Arrange
        commits = []
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commits_to_events(commits, repo_full_name)

        # Assert
        assert result == []

    def test_transform_commits_to_events_all_invalid(self):
        """全てのCommitが無効な場合に空リストを返す。"""
        # Arrange
        commits = [
            {"commit": {"message": "No sha"}},  # shaなし
            {},  # 空オブジェクト
        ]
        repo_full_name = "myusername/repo"

        # Act
        result = transform_commits_to_events(commits, repo_full_name)

        # Assert
        assert result == []


class TestGenerateRepoSummary:
    """Repositoryサマリー生成関数のテスト."""

    def test_generate_summary_with_description_and_topics(self):
        """descriptionとtopicsからサマリーを生成する。"""
        # Arrange
        repo = {
            "description": "A test repository for GitHub worklog",
            "topics": ["github", "worklog", "analytics"],
        }

        # Act
        summary = generate_repo_summary(repo)

        # Assert
        assert summary is not None
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_generate_summary_description_only(self):
        """descriptionのみでサマリーを生成する。"""
        # Arrange
        repo = {
            "description": "A test repository",
            "topics": [],
        }

        # Act
        summary = generate_repo_summary(repo)

        # Assert
        assert summary is not None
        assert isinstance(summary, str)

    def test_generate_summary_topics_only(self):
        """topicsのみでサマリーを生成する。"""
        # Arrange
        repo = {
            "description": None,
            "topics": ["github", "analytics"],
        }

        # Act
        summary = generate_repo_summary(repo)

        # Assert
        assert summary is not None
        assert isinstance(summary, str)

    def test_generate_summary_no_data(self):
        """descriptionとtopicsがない場合にデフォルトサマリーを返す。"""
        # Arrange
        repo = {
            "description": None,
            "topics": [],
        }

        # Act
        summary = generate_repo_summary(repo)

        # Assert
        assert summary is not None
        assert isinstance(summary, str)
        assert summary == ""
