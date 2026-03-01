"""WebSocket トークンストア。

一回限りの使用を前提とした、セッション単位の WebSocket トークンを管理します。
メモリ内ストアのため、プロセス再起動時にトークンは失われます。
"""

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class WSToken:
    """WebSocket トークン情報。

    Attributes:
        token: トークン文字列
        session_id: 紐付けるセッションID
        expires_at: 有効期限
    """

    token: str
    session_id: str
    expires_at: datetime


class TerminalWSTokenStore:
    """ターミナル WebSocket トークンストアクラス。

    特徴:
        - インメモリストア（プロセス再起動でリセット）
        - 一回きりの使用（consume で削除）
        - セッション単位の発行（同一セッションで新しいトークン発行時は前のトークンを無効化）
        - 有効期限付き（デフォルト60秒）
        - consume 時に期限切れトークンを opportunistically にクリーンアップ

    Args:
        token_ttl_seconds: トークンの有効期限（秒）。デフォルトは60秒
        now_fn: 現在時刻取得関数。テスト用のモック注入用
    """

    DEFAULT_TTL_SECONDS = 60

    def __init__(
        self,
        token_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc).replace(
            tzinfo=None
        ),
    ) -> None:
        """トークンストアを初期化します。

        Args:
            token_ttl_seconds: トークンの有効期限（秒）
            now_fn: 現在時刻取得関数。テスト用
        """
        self._token_ttl_seconds = token_ttl_seconds
        self._now_fn = now_fn
        self._tokens: dict[str, WSToken] = {}
        # session_id -> token のマップ（同一セッションの以前のトークンを無効化するため）
        self._session_tokens: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def issue(self, session_id: str, ttl_seconds: int | None = None) -> str:
        """指定されたセッションに紐付くトークンを発行します。

        同一セッションIDで既にトークンが発行されている場合、
        以前のトークンは無効化されます。

        Args:
            session_id: トークンを紐付けるセッションID
            ttl_seconds: この発行で利用する TTL（秒）。None の場合はストア既定値を使う

        Returns:
            発行されたトークン文字列

        Note:
            トークンは secrets.token_urlsafe(32) で生成されます。
        """
        effective_ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else self._token_ttl_seconds
        )

        token = secrets.token_urlsafe(32)
        now = self._now_fn()
        expires_at = now + timedelta(seconds=effective_ttl_seconds)

        async with self._lock:
            # 同一セッションの以前のトークンを無効化
            if session_id in self._session_tokens:
                old_token = self._session_tokens[session_id]
                if old_token in self._tokens:
                    del self._tokens[old_token]
                    logger.debug("Invalidated old token for session: %s", session_id)

            # 新しいトークンを登録
            ws_token = WSToken(
                token=token,
                session_id=session_id,
                expires_at=expires_at,
            )
            self._tokens[token] = ws_token
            self._session_tokens[session_id] = token

            logger.debug(
                "Issued token for session: %s, expires_at: %s",
                session_id,
                expires_at,
            )

        return token

    async def consume(self, token: str) -> tuple[bool, str | None]:
        """トークンを消費して検証します。

        トークンが有効な場合、ストアから削除されます（一回きりの使用）。
        同時に、期限切れのトークンを opportunistic にクリーンアップします。

        Args:
            token: 消費するトークン文字列

        Returns:
            (成功したかどうか, セッションID)
            トークンが無効な場合、セッションIDは None

        Note:
            - トークンが存在しない場合、(False, None) を返します
            - トークンが期限切れの場合、(False, None) を返し、トークンを削除します
            - トークンが有効な場合、(True, session_id) を返し、トークンを削除します
        """
        async with self._lock:
            # Opportunistic cleanup: 期限切れトークンを削除
            await self._cleanup_expired()

            ws_token = self._tokens.get(token)

            if ws_token is None:
                return False, None

            # 有効期限チェック
            if self._now_fn() > ws_token.expires_at:
                # 期限切れトークンを削除
                del self._tokens[token]
                if ws_token.session_id in self._session_tokens:
                    if self._session_tokens[ws_token.session_id] == token:
                        del self._session_tokens[ws_token.session_id]
                logger.debug("Token expired for session: %s", ws_token.session_id)
                return False, None

            # トークンを消費（削除）
            del self._tokens[token]
            if ws_token.session_id in self._session_tokens:
                if self._session_tokens[ws_token.session_id] == token:
                    del self._session_tokens[ws_token.session_id]

            logger.debug("Consumed token for session: %s", ws_token.session_id)
            return True, ws_token.session_id

    async def _cleanup_expired(self) -> None:
        """期限切れトークンをクリーンアップします。

        Note:
            このメソッドは呼び出し元でロックを取得している必要があります。
        """
        now = self._now_fn()
        expired_tokens = [
            token
            for token, ws_token in self._tokens.items()
            if now > ws_token.expires_at
        ]

        for token in expired_tokens:
            ws_token = self._tokens[token]
            del self._tokens[token]
            if ws_token.session_id in self._session_tokens:
                if self._session_tokens[ws_token.session_id] == token:
                    del self._session_tokens[ws_token.session_id]

        if expired_tokens:
            logger.debug("Cleaned up %d expired tokens", len(expired_tokens))


# モジュールレベルのシングルトン
terminal_ws_token_store = TerminalWSTokenStore()
