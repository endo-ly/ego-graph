"""Dataset catalog tests."""

import pytest
from dataset_catalog import (
    CompactionStrategy,
    DataDomain,
    DatasetDefinition,
    PartitionPolicy,
    datasets,
    get_dataset,
    monthly_compaction_datasets,
)
from dataset_catalog.catalog import _build_datasets_by_id


def test_catalog_resolves_dataset_by_id():
    """dataset id から定義を取得できる。"""
    dataset = get_dataset("spotify.plays")

    assert dataset is datasets.SPOTIFY_PLAYS
    assert dataset.domain is DataDomain.EVENTS
    assert dataset.path == "spotify/plays"
    assert dataset.partition_policy is PartitionPolicy.MONTHLY
    assert dataset.compaction_strategy is CompactionStrategy.APPEND_DEDUPE
    assert dataset.dedupe_key == "play_id"
    assert dataset.sort_key == "played_at_utc"
    assert dataset.event_time_column == "played_at_utc"


def test_monthly_compaction_datasets_are_explicitly_ordered():
    """monthly compaction 対象が provider ごとに明示順で取得できる。"""
    assert monthly_compaction_datasets("spotify") == (
        datasets.SPOTIFY_PLAYS,
        datasets.SPOTIFY_TRACKS,
        datasets.SPOTIFY_ARTISTS,
    )
    assert monthly_compaction_datasets("github") == (
        datasets.GITHUB_COMMITS,
        datasets.GITHUB_PULL_REQUESTS,
    )


def test_dataset_builds_storage_paths():
    """dataset 定義から source / compacted path を生成できる。"""
    dataset = datasets.BROWSER_HISTORY_PAGE_VIEWS

    assert dataset.source_partition_prefix("events/", year=2026, month=4) == (
        "events/browser_history/page_views/year=2026/month=04/"
    )
    assert dataset.compacted_partition_key("compacted/", year=2026, month=4) == (
        "compacted/events/browser_history/page_views/year=2026/month=04/data.parquet"
    )
    assert datasets.GITHUB_REPOSITORIES.source_glob("master/") == (
        "master/github/repositories/**/*.parquet"
    )


def test_snapshot_dataset_builds_fixed_source_key():
    """snapshot dataset は固定 source key を生成できる。"""
    assert datasets.YOUTUBE_VIDEOS.source_snapshot_key("master/") == (
        "master/youtube/videos/data.parquet"
    )


def test_duplicate_dataset_id_fails_fast():
    """dataset id の重複は catalog 構築時に検知する。"""
    duplicate_a = DatasetDefinition(
        dataset_id="duplicate.dataset",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/a",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
    )
    duplicate_b = DatasetDefinition(
        dataset_id="duplicate.dataset",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/b",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
    )

    with pytest.raises(ValueError, match="duplicate_dataset_id: duplicate.dataset"):
        _build_datasets_by_id((duplicate_a, duplicate_b))
