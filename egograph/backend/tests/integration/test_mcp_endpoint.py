"""MCPエンドポイント (/mcp) のスモークテスト。

パスマウントやタスクグループ初期化の退化を検知する。
"""

import json


class TestMcpEndpoint:
    """MCPエンドポイントの統合テスト。"""

    def test_mcp_initialize_returns_200(self, test_client):
        """POST /mcp に initialize リクエストを送ると 200 が返る。"""
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        }

        # Act
        response = test_client.post(
            "/mcp",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "x-api-key": "test-backend-key",
            },
        )

        # Assert: パスマウントとタスクグループ初期化が正常であることを確認
        assert response.status_code == 200

    def test_mcp_initialize_response_contains_server_info(self, test_client):
        """initialize レスポンスにサーバー情報が含まれる。"""
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        }

        # Act
        response = test_client.post(
            "/mcp",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "x-api-key": "test-backend-key",
            },
        )

        # Assert: レスポンスボディにEgoGraphサーバー情報が含まれる
        body = response.text
        assert "EgoGraph" in body

    def test_mcp_without_api_key_returns_401(self, test_client):
        """APIキーなしでアクセスすると 401 が返る。"""
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        }

        # Act
        response = test_client.post(
            "/mcp",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        # Assert
        assert response.status_code == 401
