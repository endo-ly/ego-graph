"""WebSocket トークンストアの単体テスト。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from gateway.services.ws_token_store import TerminalWSTokenStore, WSToken


class TestTerminalWSTokenStore:
    """TerminalWSTokenStore クラスの単体テスト。"""

    def test_init_default_params(self) -> None:
        """デフォルトパラメータでの初期化テスト。"""
        store = TerminalWSTokenStore()
        assert store._token_ttl_seconds == TerminalWSTokenStore.DEFAULT_TTL_SECONDS

    def test_init_custom_params(self) -> None:
        """カスタムパラメータでの初期化テスト。"""
        store = TerminalWSTokenStore(token_ttl_seconds=600)
        assert store._token_ttl_seconds == 600

    @pytest.mark.asyncio
    async def test_issue_token(self) -> None:
        """トークン発行のテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act
        token = await store.issue("session-123")

        # Assert
        assert token
        assert len(token) > 0
        assert token in store._tokens
        assert store._tokens[token].session_id == "session-123"
        assert store._tokens[token].expires_at == now + timedelta(seconds=60)

    @pytest.mark.asyncio
    async def test_issue_token_with_explicit_ttl(self) -> None:
        """issue で明示 TTL を渡した場合に有効期限へ反映されることを確認する。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act
        token = await store.issue("session-123", 45)

        # Assert
        assert token
        assert token in store._tokens
        assert store._tokens[token].expires_at == now + timedelta(seconds=45)

    @pytest.mark.asyncio
    async def test_consume_token_once(self) -> None:
        """トークンが一回だけ使用できることのテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        token = await store.issue("session-123")

        # Act - 1回目の consume
        success1, session_id1 = await store.consume(token)

        # Assert
        assert success1 is True
        assert session_id1 == "session-123"
        assert token not in store._tokens

        # Act - 2回目の consume（失敗すべき）
        success2, session_id2 = await store.consume(token)

        # Assert
        assert success2 is False
        assert session_id2 is None

    @pytest.mark.asyncio
    async def test_consume_expired_token(self) -> None:
        """期限切れトークンの consume テスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        issue_time = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: issue_time

        token = await store.issue("session-123")

        # 時間を経過させる（6分後 = 期限切れ）
        consume_time = datetime(2025, 1, 1, 12, 6, 0)
        store._now_fn = lambda: consume_time

        # Act
        success, session_id = await store.consume(token)

        # Assert
        assert success is False
        assert session_id is None
        assert token not in store._tokens

    @pytest.mark.asyncio
    async def test_consume_nonexistent_token(self) -> None:
        """存在しないトークンの consume テスト。"""
        # Arrange
        store = TerminalWSTokenStore()

        # Act
        success, session_id = await store.consume("nonexistent-token")

        # Assert
        assert success is False
        assert session_id is None

    @pytest.mark.asyncio
    async def test_issue_invalidates_previous_token(self) -> None:
        """同一セッションで新しいトークン発行時、以前のトークンが無効化されるテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act - 1つ目のトークンを発行
        token1 = await store.issue("session-123")

        # 2つ目のトークンを発行（同一セッション）
        token2 = await store.issue("session-123")

        # Assert - 1つ目のトークンは無効化されている
        success1, _ = await store.consume(token1)
        assert success1 is False

        # Assert - 2つ目のトークンは有効
        success2, session_id = await store.consume(token2)
        assert success2 is True
        assert session_id == "session-123"

    @pytest.mark.asyncio
    async def test_different_sessions_independent(self) -> None:
        """異なるセッションのトークンが独立しているテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act
        token1 = await store.issue("session-111")
        token2 = await store.issue("session-222")

        # Assert
        success1, session_id1 = await store.consume(token1)
        assert success1 is True
        assert session_id1 == "session-111"

        success2, session_id2 = await store.consume(token2)
        assert success2 is True
        assert session_id2 == "session-222"

    @pytest.mark.asyncio
    async def test_opportunistic_cleanup_on_consume(self) -> None:
        """consume 時に期限切れトークンがクリーンアップされるテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        issue_time = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: issue_time

        # 複数のトークンを発行
        token1 = await store.issue("session-111")
        token2 = await store.issue("session-222")
        token3 = await store.issue("session-333")

        # 時間を経過させる（6分後 = token1, token2 は期限切れ）
        consume_time = datetime(2025, 1, 1, 12, 6, 0)
        store._now_fn = lambda: consume_time

        # token3 の有効期限を更新（まだ有効）
        store._tokens[token3].expires_at = datetime(2025, 1, 1, 12, 10, 0)

        # Act - token3 を consume（クリーンアップがトリガーされる）
        success, session_id = await store.consume(token3)

        # Assert
        assert success is True
        assert session_id == "session-333"

        # 期限切れトークンはクリーンアップされている
        assert token1 not in store._tokens
        assert token2 not in store._tokens

    @pytest.mark.asyncio
    async def test_concurrent_consume_race_safety(self) -> None:
        """同時 consume の競合安全性テスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        token = await store.issue("session-123")

        # Act - 同じトークンを同時に consume しようとする
        results = await asyncio.gather(
            store.consume(token),
            store.consume(token),
            store.consume(token),
        )

        # Assert - 1つだけ成功し、残りは失敗する
        success_count = sum(1 for success, _ in results if success)
        assert success_count == 1

        # 成功したものは正しいセッションIDを持つ
        success_results = [session_id for success, session_id in results if success]
        assert success_results[0] == "session-123"

    @pytest.mark.asyncio
    async def test_concurrent_issue_different_sessions(self) -> None:
        """異なるセッションでの同時発行テスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act - 複数のセッションで同時にトークンを発行
        tokens = await asyncio.gather(
            store.issue("session-111"),
            store.issue("session-222"),
            store.issue("session-333"),
        )

        # Assert - 全て異なるトークン
        assert len(set(tokens)) == 3

        # 全て有効
        for token, session_id in zip(
            tokens, ["session-111", "session-222", "session-333"]
        ):
            success, actual_session_id = await store.consume(token)
            assert success is True
            assert actual_session_id == session_id

    @pytest.mark.asyncio
    async def test_token_expiration_boundary(self) -> None:
        """トークン有効期限境界のテスト。"""
        # Arrange
        store = TerminalWSTokenStore(token_ttl_seconds=300)
        issue_time = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: issue_time

        token = await store.issue("session-123")

        # ちょうど有効期限ギリギリ（299秒後）
        store._now_fn = lambda: datetime(2025, 1, 1, 12, 4, 59)
        success1, _ = await store.consume(token)
        assert success1 is True

        # 新しいトークンを発行（時刻をリセット）
        store._now_fn = lambda: datetime(2025, 1, 1, 12, 0, 0)
        token2 = await store.issue("session-456")

        # ちょうど有効期限切れ（301秒後）
        store._now_fn = lambda: datetime(2025, 1, 1, 12, 5, 1)
        success2, _ = await store.consume(token2)
        assert success2 is False

    @pytest.mark.asyncio
    async def test_multiple_issues_same_session_cleanup(self) -> None:
        """同一セッションで複数回発行時のクリーンアップテスト。"""
        # Arrange
        store = TerminalWSTokenStore()
        now = datetime(2025, 1, 1, 12, 0, 0)
        store._now_fn = lambda: now

        # Act - 同一セッションで3回トークンを発行
        token1 = await store.issue("session-123")
        token2 = await store.issue("session-123")
        token3 = await store.issue("session-123")

        # Assert - 最後のトークンのみ有効
        assert token1 not in store._tokens
        assert token2 not in store._tokens
        assert token3 in store._tokens

        # 以前のトークンは consume できない
        success1, _ = await store.consume(token1)
        assert success1 is False

        success2, _ = await store.consume(token2)
        assert success2 is False

        # 最後のトークンは consume できる
        success3, session_id = await store.consume(token3)
        assert success3 is True
        assert session_id == "session-123"
