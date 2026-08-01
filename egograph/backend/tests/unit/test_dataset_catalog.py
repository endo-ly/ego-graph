"""Dataset catalog tests."""

import pytest
from dataset_catalog import (
    ALL_DATASETS,
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
    assert dataset.time_column == "played_at_utc"


def test_monthly_compaction_datasets_covers_only_append_dedupe_providers():
    """monthly compaction 対象が append_dedupe provider 全てを定義順で返す。"""
    assert monthly_compaction_datasets("spotify") == (
        datasets.SPOTIFY_PLAYS,
        datasets.SPOTIFY_TRACKS,
        datasets.SPOTIFY_ARTISTS,
    )
    assert monthly_compaction_datasets("github") == (
        datasets.GITHUB_COMMITS,
        datasets.GITHUB_PULL_REQUESTS,
    )
    assert monthly_compaction_datasets("browser_history") == (
        datasets.BROWSER_HISTORY_PAGE_VIEWS,
    )
    assert monthly_compaction_datasets("youtube") == (
        datasets.YOUTUBE_WATCH_EVENTS,
    )


def test_monthly_compaction_datasets_excludes_non_append_dedupe_provider():
    """range_replace の provider (google_health) は対象外で KeyError。"""
    with pytest.raises(KeyError, match="unknown_provider: google_health"):
        monthly_compaction_datasets("google_health")


def test_monthly_compaction_datasets_derived_in_definition_order():
    """導出結果が ALL_DATASETS の定義順に一致する（drift 検出の regression guard）。"""
    expected_spotify = tuple(
        d
        for d in ALL_DATASETS
        if d.provider == "spotify"
        and d.partition_policy is PartitionPolicy.MONTHLY
        and d.compaction_strategy is CompactionStrategy.APPEND_DEDUPE
    )
    assert monthly_compaction_datasets("spotify") == expected_spotify


def test_browser_history_sort_key_uses_ingestion_time():
    """browser_history の sort_key は ingested_at_utc（run をまたいだ決定的勝者）。"""
    assert datasets.BROWSER_HISTORY_PAGE_VIEWS.sort_key == "ingested_at_utc"


def test_source_root_selects_by_domain():
    """source_root は domain に応じて events / master の root を選ぶ。"""
    events = "events/"
    master = "master/"

    assert datasets.SPOTIFY_PLAYS.source_root(events, master) == events
    assert datasets.SPOTIFY_TRACKS.source_root(events, master) == master


def test_required_dedupe_key_returns_key_or_raises():
    """required_dedupe_key は設定済みなら返し、未設定ならエラー。"""
    assert datasets.SPOTIFY_PLAYS.required_dedupe_key() == "play_id"

    no_dedupe = DatasetDefinition(
        dataset_id="test.none",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/none",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
        required_columns=("id",),
    )
    with pytest.raises(ValueError, match="dedupe_key_required: test.none"):
        no_dedupe.required_dedupe_key()


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
        required_columns=("id",),
    )
    duplicate_b = DatasetDefinition(
        dataset_id="duplicate.dataset",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/b",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
        required_columns=("id",),
    )

    with pytest.raises(ValueError, match="duplicate_dataset_id: duplicate.dataset"):
        _build_datasets_by_id((duplicate_a, duplicate_b))


def _contract_definition(**overrides) -> DatasetDefinition:
    """schema 契約付き DatasetDefinition を組み立てる。"""
    base = dict(
        dataset_id="test.contract",
        provider="test",
        domain=DataDomain.EVENTS,
        path="test/contract",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.NONE,
        required_columns=("id", "created_at"),
        column_types={"id": "string", "created_at": "timestamp"},
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def test_schema_version_defaults_to_one():
    """schema_version は未指定なら 1。"""
    assert _contract_definition().schema_version == 1


def test_empty_required_columns_raises():
    """required_columns が空の定義は拒否する。"""
    with pytest.raises(ValueError, match="invalid_schema"):
        _contract_definition(required_columns=())


def test_duplicate_required_columns_raises():
    """required_columns の重複は拒否する。"""
    with pytest.raises(ValueError, match="invalid_schema"):
        _contract_definition(required_columns=("id", "id"))


def test_column_type_key_not_in_required_columns_raises():
    """column_types の key が required_columns に含まれない定義は拒否する。"""
    with pytest.raises(ValueError, match="invalid_schema"):
        _contract_definition(column_types={"id": "string", "unknown": "string"})


def test_unknown_canonical_type_raises():
    """未定義の canonical type は拒否する。"""
    with pytest.raises(ValueError, match="invalid_schema"):
        _contract_definition(column_types={"id": "varchar", "created_at": "timestamp"})


def test_all_datasets_have_schema_contracts():
    """全 dataset が schema version と required columns を持つ。"""
    for dataset in ALL_DATASETS:
        assert dataset.schema_version >= 1
        assert (
            dataset.required_columns
        ), f"missing required_columns: {dataset.dataset_id}"
        assert set(dataset.column_types) <= set(dataset.required_columns)
