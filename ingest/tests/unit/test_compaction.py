"""Compaction helper tests."""

from datetime import datetime, timezone

import pandas as pd

from ingest.compaction import (
    build_compacted_key,
    compact_records,
    discover_available_months,
    resolve_target_months,
)


class TestBuildCompactedKey:
    """build_compacted_key tests."""

    def test_builds_events_key(self):
        key = build_compacted_key(
            compacted_path="compacted/",
            data_domain="events",
            dataset_path="spotify/plays",
            year=2024,
            month=1,
        )

        assert key == "compacted/events/spotify/plays/year=2024/month=01/data.parquet"

    def test_builds_master_key(self):
        key = build_compacted_key(
            compacted_path="compacted/",
            data_domain="master",
            dataset_path="spotify/tracks",
            year=2024,
            month=2,
        )

        assert key == "compacted/master/spotify/tracks/year=2024/month=02/data.parquet"


class TestCompactRecords:
    """compact_records tests."""

    def test_deduplicates_by_key_keeping_latest(self):
        records = [
            {
                "track_id": "track-1",
                "name": "Song A",
                "updated_at": "2024-01-01T00:00:00Z",
            },
            {
                "track_id": "track-1",
                "name": "Song A+",
                "updated_at": "2024-01-02T00:00:00Z",
            },
            {
                "track_id": "track-2",
                "name": "Song B",
                "updated_at": "2024-01-01T00:00:00Z",
            },
        ]

        df = compact_records(
            records,
            dedupe_key="track_id",
            sort_by="updated_at",
        )

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert df.loc[df["track_id"] == "track-1", "name"].item() == "Song A+"

    def test_returns_empty_dataframe_for_empty_records(self):
        df = compact_records([], dedupe_key="track_id")

        assert df.empty


class TestResolveTargetMonths:
    """resolve_target_months tests."""

    def test_returns_explicit_month_when_given(self):
        assert resolve_target_months(2024, 3) == [(2024, 3)]

    def test_returns_current_and_previous_month_by_default(self):
        now = datetime(2024, 3, 15, tzinfo=timezone.utc)

        assert resolve_target_months(now=now) == [(2024, 2), (2024, 3)]

    def test_handles_year_boundary(self):
        now = datetime(2024, 1, 10, tzinfo=timezone.utc)

        assert resolve_target_months(now=now) == [(2023, 12), (2024, 1)]


class TestDiscoverAvailableMonths:
    """discover_available_months tests."""

    def test_returns_sorted_unique_partitions_from_parquet_keys(self):
        class DummyPaginator:
            def paginate(self, **_: object):
                yield {
                    "Contents": [
                        {
                            "Key": (
                                "events/spotify/plays/"
                                "year=2024/month=02/file-a.parquet"
                            )
                        },
                        {
                            "Key": (
                                "events/spotify/plays/"
                                "year=2024/month=01/file-b.parquet"
                            )
                        },
                        {
                            "Key": (
                                "events/spotify/plays/"
                                "year=2024/month=02/file-c.parquet"
                            )
                        },
                        {
                            "Key": "events/spotify/plays/not-a-partition/file.txt"
                        },
                    ]
                }

        class DummyS3Client:
            def get_paginator(self, name: str):
                assert name == "list_objects_v2"
                return DummyPaginator()

        months = discover_available_months(
            DummyS3Client(),
            bucket_name="egograph",
            source_prefix="events/spotify/plays/",
        )

        assert months == [(2024, 1), (2024, 2)]
