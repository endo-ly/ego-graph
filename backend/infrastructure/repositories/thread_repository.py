"""Thread Repository Implementation.

SQLiteを使用したスレッド管理のリポジトリ実装を提供します。
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.constants import DEFAULT_THREAD_LIST_LIMIT
from backend.domain.models.thread import (
    THREAD_PREVIEW_MAX_LENGTH,
    THREAD_TITLE_MAX_LENGTH,
    Thread,
    ThreadMessage,
)

logger = logging.getLogger(__name__)


@dataclass
class AddMessageParams:
    """メッセージ追加用のパラメータ。"""

    thread_id: str
    user_id: str
    role: str
    content: str
    model_name: str | None = None


class ThreadRepository:
    """SQLiteを使用したスレッドリポジトリの実装。

    チャット履歴のスレッドとメッセージに対するCRUD操作を提供します。
    すべてのメソッドはSQLite接続を使用し、トランザクション管理を行います。

    Attributes:
        _conn: SQLiteコネクション
    """

    def __init__(self, conn: sqlite3.Connection):
        """ThreadRepositoryを初期化します。

        Args:
            conn: SQLiteコネクション
        """
        self._conn = conn

    _GET_THREADS_QUERY = """
        SELECT
            threads.thread_id,
            threads.user_id,
            threads.title,
            (
                SELECT content FROM messages m2
                WHERE m2.thread_id = threads.thread_id
                ORDER BY m2.created_at DESC
                LIMIT 1
            ) AS preview,
            (SELECT COUNT(*) FROM messages WHERE messages.thread_id = threads.thread_id)
                AS message_count,
            threads.created_at,
            threads.last_message_at
        FROM threads
        WHERE threads.user_id = ?
        ORDER BY threads.last_message_at DESC
        LIMIT ? OFFSET ?
        """

    def create_thread(self, user_id: str, first_message_content: str) -> Thread:
        """新規スレッドを作成する。

        初回メッセージの先頭50文字をタイトルとして使用します。

        Args:
            user_id: ユーザーID
            first_message_content: 初回メッセージの内容

        Returns:
            Thread: 作成されたスレッドオブジェクト

        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        thread_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # タイトルは初回メッセージの先頭N文字
        title = first_message_content[:THREAD_TITLE_MAX_LENGTH]

        try:
            self._conn.execute(
                """
                INSERT INTO threads (
                    thread_id, user_id, title, created_at, last_message_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, user_id, title, now, now),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info("Created thread thread_id=%s, user_id=%s", thread_id, user_id)

        return Thread(
            thread_id=thread_id,
            user_id=user_id,
            title=title,
            preview=title,
            message_count=0,
            created_at=datetime.fromisoformat(now),
            last_message_at=datetime.fromisoformat(now),
        )

    def add_message(self, params: AddMessageParams) -> ThreadMessage:
        """スレッドにメッセージを追加する。

        メッセージを追加し、スレッドのlast_message_atを更新します。

        Args:
            params: メッセージ追加パラメータ

        Returns:
            ThreadMessage: 追加されたメッセージオブジェクト

        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        message_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            # メッセージを追加
            self._conn.execute(
                """
                INSERT INTO messages (
                    message_id, thread_id, user_id, role, content,
                    created_at, model_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    params.thread_id,
                    params.user_id,
                    params.role,
                    params.content,
                    now,
                    params.model_name,
                ),
            )

            # スレッドのlast_message_atを更新
            self._conn.execute(
                """
                UPDATE threads
                SET last_message_at = ?
                WHERE thread_id = ?
                """,
                (now, params.thread_id),
            )

            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        logger.info(
            "Added message message_id=%s to thread_id=%s, role=%s",
            message_id,
            params.thread_id,
            params.role,
        )

        return ThreadMessage(
            message_id=message_id,
            thread_id=params.thread_id,
            user_id=params.user_id,
            role=params.role,
            content=params.content,
            created_at=datetime.fromisoformat(now),
            model_name=params.model_name,
        )

    def get_thread(self, thread_id: str) -> Thread | None:
        """スレッドを取得する。

        Args:
            thread_id: スレッドのUUID

        Returns:
            Thread | None: スレッドオブジェクト（存在しない場合はNone）

        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        result = self._conn.execute(
            """
            SELECT
                threads.thread_id,
                threads.user_id,
                threads.title,
                (
                    SELECT content FROM messages m2
                    WHERE m2.thread_id = threads.thread_id
                    ORDER BY m2.created_at DESC
                    LIMIT 1
                ) AS preview,
                (
                    SELECT COUNT(*)
                    FROM messages
                    WHERE messages.thread_id = threads.thread_id
                )
                    AS message_count,
                threads.created_at,
                threads.last_message_at
            FROM threads
            WHERE threads.thread_id = ?
            """,
            (thread_id,),
        )

        row = result.fetchone()
        if row is None:
            logger.debug("Thread not found: thread_id=%s", thread_id)
            return None

        logger.debug("Retrieved thread: thread_id=%s", thread_id)
        return self._map_row_to_thread(row)

    def get_threads(
        self, user_id: str, limit: int = DEFAULT_THREAD_LIST_LIMIT, offset: int = 0
    ) -> tuple[list[Thread], int]:
        """ユーザーのスレッド一覧を取得する。

        最終メッセージ日時の降順で取得します。

        Args:
            user_id: ユーザーID
            limit: 1ページあたりの件数（デフォルト: 50）
            offset: オフセット（デフォルト: 0）

        Returns:
            tuple[list[Thread], int]: (スレッドのリスト, 総件数) のタプル

        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        total = self._get_thread_count(user_id)
        result = self._conn.execute(
            self._GET_THREADS_QUERY,
            (user_id, limit, offset),
        )
        threads = [self._map_row_to_thread(row) for row in result.fetchall()]

        logger.debug(
            "Retrieved threads for user_id=%s, count=%s, total=%s",
            user_id,
            len(threads),
            total,
        )

        return threads, total

    def _get_thread_count(self, user_id: str) -> int:
        """ユーザーのスレッド総件数を取得する。

        Args:
            user_id: ユーザーID

        Returns:
            int: スレッド総件数
        """
        result = self._conn.execute(
            "SELECT COUNT(*) FROM threads WHERE user_id = ?",
            (user_id,),
        )
        return result.fetchone()[0]

    def _map_row_to_thread(self, row: tuple) -> Thread:
        """データベース行からThreadオブジェクトを構築する。

        Args:
            row: データベースの行タプル

        Returns:
            Thread: Threadオブジェクト
        """
        return Thread(
            thread_id=row[0],
            user_id=row[1],
            title=row[2],
            preview=row[3][:THREAD_PREVIEW_MAX_LENGTH] if row[3] else None,
            message_count=row[4],
            created_at=datetime.fromisoformat(row[5]),
            last_message_at=datetime.fromisoformat(row[6]),
        )

    def get_messages(self, thread_id: str) -> list[ThreadMessage]:
        """スレッドのメッセージ一覧を取得する。

        作成日時の昇順で取得します。

        Args:
            thread_id: スレッドのUUID

        Returns:
            list[ThreadMessage]: メッセージのリスト（時系列順）

        Raises:
            sqlite3.Error: データベース操作に失敗した場合
        """
        result = self._conn.execute(
            """
            SELECT message_id, thread_id, user_id, role, content, created_at, model_name
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            """,
            (thread_id,),
        )

        messages = [
            ThreadMessage(
                message_id=row[0],
                thread_id=row[1],
                user_id=row[2],
                role=row[3],
                content=row[4],
                created_at=datetime.fromisoformat(row[5]),
                model_name=row[6],
            )
            for row in result.fetchall()
        ]

        logger.debug(
            "Retrieved messages for thread_id=%s, count=%s", thread_id, len(messages)
        )

        return messages
