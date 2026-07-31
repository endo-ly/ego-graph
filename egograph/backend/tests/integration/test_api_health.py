from unittest.mock import MagicMock, patch

import duckdb

import backend.dependencies as deps


class TestHealthEndpoint:
    """Healthエンドポイントのテスト。"""

    def test_health_check_success(self, test_client, mock_backend_config):
        """ヘルスチェックが成功する。"""

        # モックDB接続を作成
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [1]  # SELECT 1の結果
        mock_conn.execute.return_value = mock_result

        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.return_value = mock_conn
        mock_db_connection.__exit__.return_value = False

        # 依存性オーバーライド
        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            response = test_client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "duckdb" in data
            assert "r2" in data
            assert data["data_available"] is True
        finally:
            # クリーンアップ
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    def test_health_check_with_v1_prefix(self, test_client, mock_backend_config):
        """/v1/healthエンドポイントでもアクセス可能。"""

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [1]  # SELECT 1の結果
        mock_conn.execute.return_value = mock_result

        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.return_value = mock_conn
        mock_db_connection.__exit__.return_value = False

        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            response = test_client.get("/v1/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    def test_health_check_handles_db_error(self, test_client, mock_backend_config):
        """DB接続エラーをハンドリング。"""

        # DB接続でエラーを発生させる
        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.side_effect = Exception("Connection failed")

        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            response = test_client.get("/health")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "error"
            assert "error" in data
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    def test_health_check_returns_ok_when_local_parquet_is_missing(
        self, test_client, mock_backend_config
    ):
        """compacted parquet が未生成でも正常応答する。"""

        # Arrange
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = FileNotFoundError("missing parquet")

        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.return_value = mock_conn
        mock_db_connection.__exit__.return_value = False

        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            # Act
            response = test_client.get("/health")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["duckdb"] == "connected"
            assert data["r2"] == "accessible"
            assert data["data_available"] is False
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    def test_health_check_handles_path_resolution_error(
        self, test_client, mock_backend_config
    ):
        """R2 path 解決エラーを readiness failure として返す。"""
        with patch(
            "backend.api.health.build_dataset_glob",
            side_effect=ValueError("invalid R2 path"),
        ):
            response = test_client.get("/health")

        assert response.status_code == 503
        assert response.json() == {
            "status": "error",
            "error": "invalid R2 path",
        }

    def test_health_check_returns_ok_when_no_compacted_files_exist(
        self, test_client, mock_backend_config
    ):
        """R2 に compacted parquet がまだ無い場合も正常応答する。"""

        # Arrange
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = duckdb.IOException(
            "No files found that match the pattern"
        )

        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.return_value = mock_conn
        mock_db_connection.__exit__.return_value = False

        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            # Act
            response = test_client.get("/health")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["duckdb"] == "connected"
            assert data["r2"] == "accessible"
            assert data["data_available"] is False
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config

    def test_health_error_response_excludes_infra_info(
        self, test_client, mock_backend_config
    ):
        """エラーレスポンスに R2 URL 等のインフラ情報が含まれない。"""

        # Arrange: R2 URL を含む例外を発生させるモックを準備
        mock_db_connection = MagicMock()
        mock_db_connection.__enter__.side_effect = RuntimeError(
            "Failed to connect to https://abc123.r2.cloudflarestorage.com/data"
        )

        app = test_client.app
        app.dependency_overrides[deps.get_db_connection] = lambda: mock_db_connection

        try:
            # Act: ヘルスチェックを実行
            response = test_client.get("/health")

            # Assert: レスポンスに R2 ホスト名が含まれないことを検証
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "error"
            assert "r2.cloudflarestorage.com" not in data["error"]
            assert "abc123" not in data["error"]
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides[deps.get_config] = lambda: mock_backend_config
