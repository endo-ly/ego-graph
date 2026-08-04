"""Compaction helper tests."""

from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock

import pandas as pd
import pytest
from dataset_catalog import datasets
from pipelines.compaction import DatasetCompactionTarget, validate_compaction_targets
from pipelines.sources.common.compaction import (
    _unify_datetime_columns,
    build_compacted_key,
    compact_records,
    discover_available_months,
    normalize_dataframe_for_dataset,
    read_parquet_records_from_prefix,
    resolve_target_months,
)


class TestBuildCompactedKey:
    """build_compacted_key tests."""

    def test_builds_events_key(self):
        key = build_compacted_key(
            compacted_path="compacted/",
            dataset=datasets.SPOTIFY_PLAYS,
            year=2024,
            month=1,
        )

        assert key == "compacted/events/spotify/plays/year=2024/month=01/data.parquet"

    def test_builds_master_key(self):
        key = build_compacted_key(
            compacted_path="compacted/",
            dataset=datasets.SPOTIFY_TRACKS,
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


class TestUnifyDatetimeColumns:
    """_unify_datetime_columns tests."""

    def test_unifies_mixed_timestamp_str_to_datetime(self):
        """Timestamp と str が混在していても datetime に統一される。"""
        df = pd.DataFrame(
            {
                "play_id": ["p1", "p2", "p3"],
                "played_at_utc": [
                    pd.Timestamp("2024-05-01 10:00:00"),
                    "2024-05-02 11:00:00+00:00",
                    pd.Timestamp("2024-05-01 09:00:00"),
                ],
            }
        )

        result = _unify_datetime_columns(df)

        assert result["played_at_utc"].dtype.name.startswith("datetime64[ns, UTC")
        assert result.loc[0, "played_at_utc"] == pd.Timestamp(
            "2024-05-01 10:00:00", tz="UTC"
        )
        assert result.loc[1, "played_at_utc"] == pd.Timestamp(
            "2024-05-02 11:00:00", tz="UTC"
        )

    def test_leaves_homogeneous_str_unchanged(self):
        """混在型でなければ型変換しない。"""
        df = pd.DataFrame(
            {
                "track_id": ["t1", "t2"],
                "label": ["a", "b"],
            }
        )

        result = _unify_datetime_columns(df)

        assert result["label"].dtype == object
        assert list(result["label"]) == ["a", "b"]

    def test_leaves_int_column_unchanged(self):
        """整数カラムは無視される。"""
        df = pd.DataFrame(
            {
                "id": [1, 2],
                "played_at_utc": [
                    pd.Timestamp("2024-05-01 10:00:00"),
                    pd.Timestamp("2024-05-02 11:00:00"),
                ],
            }
        )

        result = _unify_datetime_columns(df)

        assert result["id"].dtype == int
        assert result["played_at_utc"].dtype.name.startswith("datetime64[ns")


@pytest.mark.parametrize(
    ("dataset", "column"),
    [
        (datasets.GITHUB_COMMITS, "committed_at_utc"),
        (datasets.GITHUB_PULL_REQUESTS, "updated_at_utc"),
        (datasets.GITHUB_COMMITS, "ingested_at_utc"),
        (datasets.GITHUB_PULL_REQUESTS, "created_at_utc"),
    ],
)
def test_normalize_dataframe_for_dataset_converts_legacy_string_timestamp(
    dataset,
    column,
):
    """既存の文字列日時をcatalog契約のUTC timestampへ変換する。"""
    # Arrange
    df = pd.DataFrame({column: ["2026-07-01T12:00:00Z"]})

    # Act
    result = normalize_dataframe_for_dataset(df, dataset)

    # Assert
    assert result[column].dtype.name == "datetime64[ns, UTC]"
    assert result.loc[0, column] == pd.Timestamp("2026-07-01 12:00:00", tz="UTC")


@pytest.mark.parametrize(
    ("dataset", "columns"),
    [
        (
            datasets.GITHUB_COMMITS,
            ("committed_at_utc", "ingested_at_utc"),
        ),
        (
            datasets.GITHUB_PULL_REQUESTS,
            (
                "created_at_utc",
                "updated_at_utc",
                "closed_at_utc",
                "merged_at_utc",
                "ingested_at_utc",
            ),
        ),
    ],
)
def test_normalize_dataframe_for_dataset_converts_all_mixed_timestamp_columns(
    dataset,
    columns,
):
    """catalogに定義した全日時列のTimestamp/str混在を正規化する。"""
    # Arrange
    df = pd.DataFrame(
        {
            column: [
                pd.Timestamp("2026-07-01 12:00:00"),
                "2026-07-02T12:00:00Z",
            ]
            for column in columns
        }
    )

    # Act
    result = normalize_dataframe_for_dataset(df, dataset)

    # Assert
    for column in columns:
        assert result[column].dtype.name == "datetime64[ns, UTC]"


def test_normalize_dataframe_for_dataset_does_not_convert_unlisted_string_column():
    """日時列としてcatalogにない文字列列は変換しない。"""
    # Arrange
    df = pd.DataFrame(
        {
            "title": ["2026-07-01T12:00:00Z", "not-a-timestamp"],
            "ingested_at_utc": ["2026-07-01T12:00:00Z", "2026-07-02T12:00:00Z"],
        }
    )

    # Act
    result = normalize_dataframe_for_dataset(df, datasets.GITHUB_COMMITS)

    # Assert
    assert result["title"].dtype == object
    assert result["title"].tolist() == [
        "2026-07-01T12:00:00Z",
        "not-a-timestamp",
    ]


def test_normalize_dataframe_for_dataset_rejects_invalid_timestamp():
    """不正な日時はcompact前にエラーとして扱う。"""
    # Arrange
    df = pd.DataFrame({"committed_at_utc": ["not-a-timestamp"]})

    # Act & Assert
    with pytest.raises(ValueError):
        normalize_dataframe_for_dataset(df, datasets.GITHUB_COMMITS)


def test_read_parquet_records_normalizes_legacy_string_timestamp():
    """source Parquet読込時にもcatalog契約のtimestampへ変換する。"""
    # Arrange
    source_df = pd.DataFrame(
        {
            "commit_event_id": ["commit-1"],
            "committed_at_utc": ["2026-07-01T12:00:00Z"],
        }
    )
    buffer = BytesIO()
    source_df.to_parquet(buffer, index=False, engine="pyarrow")
    s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "events/github/commits/year=2026/month=07/1.parquet"}]}
    ]
    s3.get_paginator.return_value = paginator
    body = MagicMock()
    body.read.return_value = buffer.getvalue()
    s3.get_object.return_value = {"Body": body}

    # Act
    records = read_parquet_records_from_prefix(
        s3,
        "test-bucket",
        "events/github/commits/year=2026/month=07/",
        dataset=datasets.GITHUB_COMMITS,
    )

    # Assert
    assert isinstance(records[0]["committed_at_utc"], pd.Timestamp)
    assert records[0]["committed_at_utc"] == pd.Timestamp(
        "2026-07-01 12:00:00", tz="UTC"
    )


@pytest.mark.parametrize(
    ("dataset", "id_column", "timestamp_columns"),
    [
        (
            datasets.GITHUB_COMMITS,
            "commit_event_id",
            ("committed_at_utc", "ingested_at_utc"),
        ),
        (
            datasets.GITHUB_PULL_REQUESTS,
            "pr_event_id",
            (
                "created_at_utc",
                "updated_at_utc",
                "closed_at_utc",
                "merged_at_utc",
                "ingested_at_utc",
            ),
        ),
    ],
)
def test_read_parquet_records_normalizes_mixed_github_timestamps(
    dataset,
    id_column,
    timestamp_columns,
):
    """複数source Parquet間で型が混在するGitHub日時列を正規化する。"""
    # Arrange
    source_frames = [
        pd.DataFrame(
            {
                id_column: ["event-1"],
                **{
                    column: [pd.Timestamp("2026-07-01 12:00:00")]
                    for column in timestamp_columns
                },
            }
        ),
        pd.DataFrame(
            {
                id_column: ["event-2"],
                **{column: ["2026-07-02T12:00:00Z"] for column in timestamp_columns},
            }
        ),
    ]
    bodies = []
    for source_frame in source_frames:
        buffer = BytesIO()
        source_frame.to_parquet(buffer, index=False, engine="pyarrow")
        bodies.append(buffer.getvalue())

    s3 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "events/github/year=2026/month=07/1.parquet"},
                {"Key": "events/github/year=2026/month=07/2.parquet"},
            ]
        }
    ]
    s3.get_paginator.return_value = paginator
    response_bodies = []
    for body_bytes in bodies:
        body = MagicMock()
        body.read.return_value = body_bytes
        response_bodies.append({"Body": body})
    s3.get_object.side_effect = response_bodies

    # Act
    records = read_parquet_records_from_prefix(
        s3,
        "test-bucket",
        "events/github/year=2026/month=07/",
        dataset=dataset,
    )

    # Assert
    assert len(records) == 2
    for record in records:
        for column in timestamp_columns:
            assert isinstance(record[column], pd.Timestamp)
            assert record[column].tzinfo is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("year", True),
        ("month", False),
        ("year", 2026.5),
        ("month", 7.0),
        ("year", "2026"),
        ("month", "7"),
    ],
)
def test_dataset_compaction_target_rejects_non_exact_int(field, value):
    """compaction targetはboolやint以外の期間値を拒否する。"""
    # Arrange
    target_values = {"dataset_id": "github.commits", "year": 2026, "month": 7}
    target_values[field] = value

    # Act & Assert
    with pytest.raises(ValueError, match=f"invalid_{field}:"):
        DatasetCompactionTarget(**target_values)


def test_validate_compaction_targets_rejects_mixed_providers():
    """一つのrunに異なるproviderの対象を混在させない。"""
    # Arrange
    targets = (
        DatasetCompactionTarget("github.commits", 2026, 7),
        DatasetCompactionTarget("spotify.plays", 2026, 7),
    )

    # Act & Assert
    with pytest.raises(ValueError, match="same provider"):
        validate_compaction_targets(targets)


class TestCompactRecordsSortCanNowAssumeUnifiedTypes:
    """compact_records は統一済みの型を受け取る前提で動作する。"""

    def test_sorts_datetime_column_normally(self):
        df = pd.DataFrame(
            {
                "play_id": ["p1", "p2", "p3"],
                "played_at_utc": pd.to_datetime(
                    [
                        "2024-05-01 10:00:00+00:00",
                        "2024-05-02 11:00:00+00:00",
                        "2024-05-01 09:00:00+00:00",
                    ]
                ),
            }
        )
        records = df.to_dict(orient="records")

        result = compact_records(records, dedupe_key="play_id", sort_by="played_at_utc")

        assert len(result) == 3
        assert result.iloc[0]["play_id"] == "p3"
        assert result.iloc[1]["play_id"] == "p1"
        assert result.iloc[2]["play_id"] == "p2"


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
                                "events/spotify/plays/year=2024/month=02/file-a.parquet"
                            )
                        },
                        {
                            "Key": (
                                "events/spotify/plays/year=2024/month=01/file-b.parquet"
                            )
                        },
                        {
                            "Key": (
                                "events/spotify/plays/year=2024/month=02/file-c.parquet"
                            )
                        },
                        {"Key": "events/spotify/plays/not-a-partition/file.txt"},
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
