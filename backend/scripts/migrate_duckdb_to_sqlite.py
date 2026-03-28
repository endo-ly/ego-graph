"""DuckDB → SQLite チャット履歴移行スクリプト。

PR#91 で DuckDB → SQLite へのスキーマ変更が行われましたが、
既存データの移行処理が存在しなかったため、本スクリプトで旧データを復元します。

Usage:
    # ドライラン（実際の書き込みなし、件数確認のみ）
    uv run python -m backend.scripts.migrate_duckdb_to_sqlite --dry-run

    # 実行（移行）
    uv run python -m backend.scripts.migrate_duckdb_to_sqlite

    # パス指定
    uv run python -m backend.scripts.migrate_duckdb_to_sqlite \
        --duckdb-path /path/to/chat.duckdb \
        --sqlite-path /path/to/chat.sqlite
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# デフォルトパス（backend/data/ 配下）
DEFAULT_DUCKDB_PATH = Path(__file__).parent.parent / "data" / "chat.duckdb"
DEFAULT_SQLITE_PATH = Path(__file__).parent.parent / "data" / "chat.sqlite"

BATCH_SIZE = 500


def _datetime_to_iso(value: object) -> str | None:
    """DuckDB の TIMESTAMP 値を ISO8601 文字列に変換する。"""
    if value is None:
        return None
    return value.isoformat()


def migrate(
    duckdb_path: Path,
    sqlite_path: Path,
    *,
    dry_run: bool = False,
) -> None:
    """DuckDB から SQLite へチャット履歴を移行する。

    Args:
        duckdb_path: 旧 DuckDB ファイルのパス
        sqlite_path: 新 SQLite ファイルのパス
        dry_run: True の場合、読み取りと件数表示のみ行い書き込みしない
    """
    if not duckdb_path.exists():
        logger.error("DuckDB file not found: %s", duckdb_path)
        sys.exit(1)

    logger.info("Source (DuckDB): %s", duckdb_path)
    logger.info("Destination (SQLite): %s", sqlite_path)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "MIGRATE")

    # --- DuckDB から読み取り ---
    duck_conn = duckdb.connect(str(duckdb_path), read_only=True)

    thread_count = duck_conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    message_count = duck_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    logger.info("DuckDB records: threads=%d, messages=%d", thread_count, message_count)

    if thread_count == 0 and message_count == 0:
        logger.info("No data to migrate. Exiting.")
        duck_conn.close()
        return

    if dry_run:
        # 最新・最古のサンプルを表示
        oldest = duck_conn.execute(
            "SELECT MIN(created_at) FROM threads"
        ).fetchone()[0]
        newest = duck_conn.execute(
            "SELECT MAX(created_at) FROM threads"
        ).fetchone()[0]
        logger.info("Threads date range: %s ~ %s", oldest, newest)
        duck_conn.close()
        return

    # --- SQLite へ書き込み ---
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.execute("PRAGMA journal_mode=WAL")
    sqlite_conn.execute("PRAGMA foreign_keys=ON")

    # テーブル作成（chat_connection.py のスキーマと同一）
    sqlite_conn.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_message_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user_last_message
            ON threads(user_id, last_message_at DESC);

        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            model_name TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_thread_created
            ON messages(thread_id, created_at);
    """)

    # 既存データとの重複チェック
    existing_threads = {
        row[0]
        for row in sqlite_conn.execute("SELECT thread_id FROM threads").fetchall()
    }
    existing_messages = {
        row[0]
        for row in sqlite_conn.execute("SELECT message_id FROM messages").fetchall()
    }
    logger.info(
        "Existing SQLite records: threads=%d, messages=%d",
        len(existing_threads),
        len(existing_messages),
    )

    # --- threads 移行 ---
    threads_result = duck_conn.execute(
        "SELECT thread_id, user_id, title, created_at, last_message_at FROM threads"
    ).fetchall()

    new_threads = 0
    skipped_threads = 0
    thread_batch: list[tuple[str, str, str, str, str]] = []

    for row in threads_result:
        thread_id, user_id, title, created_at, last_message_at = row
        if thread_id in existing_threads:
            skipped_threads += 1
            continue
        thread_batch.append((
            thread_id,
            user_id,
            title,
            _datetime_to_iso(created_at),  # type: ignore[arg-type]
            _datetime_to_iso(last_message_at),  # type: ignore[arg-type]
        ))
        new_threads += 1

        if len(thread_batch) >= BATCH_SIZE:
            sqlite_conn.executemany(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?)",
                thread_batch,
            )
            thread_batch.clear()

    if thread_batch:
        sqlite_conn.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?)",
            thread_batch,
        )

    logger.info(
        "Threads: migrated=%d, skipped(existing)=%d",
        new_threads,
        skipped_threads,
    )

    # --- messages 移行 ---
    messages_result = duck_conn.execute(
        "SELECT message_id, thread_id, user_id, role, content, created_at, model_name FROM messages"
    ).fetchall()

    new_messages = 0
    skipped_messages = 0
    message_batch: list[tuple[str, str, str, str, str, str, str | None]] = []

    for row in messages_result:
        message_id, thread_id, user_id, role, content, created_at, model_name = row
        if message_id in existing_messages:
            skipped_messages += 1
            continue
        message_batch.append((
            message_id,
            thread_id,
            user_id,
            role,
            content,
            _datetime_to_iso(created_at),  # type: ignore[arg-type]
            model_name,
        ))
        new_messages += 1

        if len(message_batch) >= BATCH_SIZE:
            sqlite_conn.executemany(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                message_batch,
            )
            message_batch.clear()

    if message_batch:
        sqlite_conn.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
            message_batch,
        )

    logger.info(
        "Messages: migrated=%d, skipped(existing)=%d",
        new_messages,
        skipped_messages,
    )

    sqlite_conn.commit()

    # --- 検証 ---
    final_threads = sqlite_conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    final_messages = sqlite_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    logger.info("Final SQLite records: threads=%d, messages=%d", final_threads, final_messages)

    sqlite_conn.close()
    duck_conn.close()
    logger.info("Migration completed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate chat history from DuckDB to SQLite",
    )
    parser.add_argument(
        "--duckdb-path",
        type=Path,
        default=DEFAULT_DUCKDB_PATH,
        help="Path to the source DuckDB file",
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help="Path to the destination SQLite file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only check source data, do not write to SQLite",
    )
    args = parser.parse_args()

    migrate(args.duckdb_path, args.sqlite_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
