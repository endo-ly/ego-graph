"""スレッド管理APIの統合テスト。

/v1/threads エンドポイントの動作をテストします。
"""

import pytest
from fastapi.testclient import TestClient

from backend.infrastructure.database import (
    ChatDuckDBConnection,
    chat_connection,
    create_chat_tables,
)
from backend.infrastructure.repositories import (
    AddMessageParams,
    DuckDBThreadRepository,
)
from backend.main import create_app


@pytest.fixture
def test_client_with_threads(tmp_path, monkeypatch):
    """スレッドAPI用のテストクライアントを提供します。"""
    # 一時的なチャット履歴DBパスを設定
    chat_db_path = tmp_path / "test_chat.duckdb"

    # chat_connection.pyのDB_PATHをモンキーパッチ
    monkeypatch.setattr(chat_connection, "DB_PATH", chat_db_path)

    # R2設定（ダミー）
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

    # テーブルを事前に作成
    with ChatDuckDBConnection() as conn:
        create_chat_tables(conn)

    app = create_app()
    client = TestClient(app)

    yield client


@pytest.fixture
def populated_threads(tmp_path, monkeypatch):
    """テストデータが投入されたスレッドDBを提供します。"""
    # 一時的なチャット履歴DBパスを設定
    chat_db_path = tmp_path / "test_chat_populated.duckdb"

    monkeypatch.setattr(chat_connection, "DB_PATH", chat_db_path)

    # テーブル作成
    with ChatDuckDBConnection() as conn:
        create_chat_tables(conn)

        # テストデータを投入
        service = DuckDBThreadRepository(conn)
        threads = []
        for i in range(5):
            thread = service.create_thread("default_user", f"Test message {i}")
            threads.append(thread)

            # メッセージを追加
            service.add_message(
                AddMessageParams(
                    thread_id=thread.thread_id,
                    user_id="default_user",
                    role="user",
                    content=f"Test message {i}",
                )
            )
            service.add_message(
                AddMessageParams(
                    thread_id=thread.thread_id,
                    user_id="default_user",
                    role="assistant",
                    content=f"Response to message {i}",
                )
            )

    # R2設定（ダミー）
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://test.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")

    app = create_app()
    client = TestClient(app)

    # startup イベントを手動で実行（テーブルは既に存在）
    for handler in app.router.on_startup:
        handler()

    return client, threads


def test_get_threads_empty(test_client_with_threads):
    """スレッドが存在しない場合の一覧取得をテストします。"""
    response = test_client_with_threads.get("/v1/threads")

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 10
    assert data["offset"] == 0


def test_get_threads_pagination(populated_threads):
    """スレッド一覧のページングをテストします。"""
    client, threads = populated_threads

    # 1ページ目（limit=2）
    response = client.get("/v1/threads?limit=2&offset=0")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 5
    assert len(data["threads"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0

    # last_message_at降順なので最新が先頭
    assert data["threads"][0]["thread_id"] == threads[-1].thread_id

    # 2ページ目
    response_page2 = client.get("/v1/threads?limit=2&offset=2")
    data_page2 = response_page2.json()

    assert data_page2["total"] == 5
    assert len(data_page2["threads"]) == 2
    assert data_page2["threads"][0]["thread_id"] == threads[-3].thread_id


def test_get_thread_detail(populated_threads):
    """スレッド詳細取得をテストします。"""
    client, threads = populated_threads

    thread_id = threads[0].thread_id
    response = client.get(f"/v1/threads/{thread_id}")

    assert response.status_code == 200
    data = response.json()

    assert data["thread_id"] == thread_id
    assert data["user_id"] == "default_user"
    assert "title" in data
    assert data["preview"] == "Response to message 0"
    assert data["message_count"] == 2
    assert "created_at" in data
    assert "last_message_at" in data


def test_get_thread_not_found(test_client_with_threads):
    """存在しないスレッドの取得で404をテストします。"""
    nonexistent_id = "00000000-0000-0000-0000-000000000000"
    response = test_client_with_threads.get(f"/v1/threads/{nonexistent_id}")

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


def test_get_thread_messages(populated_threads):
    """スレッドメッセージ取得をテストします。"""
    client, threads = populated_threads

    thread_id = threads[0].thread_id
    response = client.get(f"/v1/threads/{thread_id}/messages")

    assert response.status_code == 200
    data = response.json()

    assert data["thread_id"] == thread_id
    assert len(data["messages"]) == 2  # user + assistant

    # 時系列順（created_at昇順）
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Test message 0"
    assert data["messages"][1]["role"] == "assistant"
    assert data["messages"][1]["content"] == "Response to message 0"


def test_get_thread_messages_not_found(test_client_with_threads):
    """存在しないスレッドのメッセージ取得で404をテストします。"""
    nonexistent_id = "00000000-0000-0000-0000-000000000000"
    response = test_client_with_threads.get(f"/v1/threads/{nonexistent_id}/messages")

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


def test_threads_response_schema(populated_threads):
    """スレッド一覧レスポンスのスキーマをテストします。"""
    client, _ = populated_threads

    response = client.get("/v1/threads")
    assert response.status_code == 200
    data = response.json()

    # トップレベルフィールド
    assert "threads" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data

    # スレッドオブジェクト
    if data["threads"]:
        thread = data["threads"][0]
        assert "thread_id" in thread
        assert "user_id" in thread
        assert "title" in thread
        assert "preview" in thread
        assert "message_count" in thread
        assert "created_at" in thread
        assert "last_message_at" in thread


def test_get_threads_limit_upper_bound(test_client_with_threads):
    """limitの上限超過で422になることをテストします。"""
    response = test_client_with_threads.get("/v1/threads?limit=101")

    assert response.status_code == 422


def test_thread_messages_response_schema(populated_threads):
    """スレッドメッセージレスポンスのスキーマをテストします。"""
    client, threads = populated_threads

    thread_id = threads[0].thread_id
    response = client.get(f"/v1/threads/{thread_id}/messages")
    assert response.status_code == 200
    data = response.json()

    # トップレベルフィールド
    assert "thread_id" in data
    assert "messages" in data

    # メッセージオブジェクト
    if data["messages"]:
        message = data["messages"][0]
        assert "message_id" in message
        assert "thread_id" in message
        assert "user_id" in message
        assert "role" in message
        assert "content" in message
        assert "created_at" in message
