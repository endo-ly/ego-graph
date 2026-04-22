"""YouTube backend test helpers."""

from contextlib import ExitStack
from unittest.mock import patch


def patch_youtube_paths(youtube_with_sample_data):
    """YouTube parquet path patch をまとめて適用する。"""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "backend.infrastructure.database.youtube_queries._generate_partition_paths",
            return_value=[youtube_with_sample_data.test_watch_events_parquet_path],
        )
    )
    stack.enter_context(
        patch(
            "backend.infrastructure.database.youtube_queries.get_videos_parquet_path",
            return_value=youtube_with_sample_data.test_videos_parquet_path,
        )
    )
    stack.enter_context(
        patch(
            "backend.infrastructure.database.youtube_queries.get_channels_parquet_path",
            return_value=youtube_with_sample_data.test_channels_parquet_path,
        )
    )
    return stack
