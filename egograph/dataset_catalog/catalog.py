"""Parquet dataset catalog definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataDomain(StrEnum):
    """R2 上のデータ分類。"""

    EVENTS = "events"
    MASTER = "master"


class PartitionPolicy(StrEnum):
    """Dataset の物理配置方針。"""

    MONTHLY = "monthly"
    SNAPSHOT = "snapshot"
    RECURSIVE = "recursive"


class CompactionStrategy(StrEnum):
    """Compacted dataset の生成戦略。"""

    APPEND_DEDUPE = "append_dedupe"
    RANGE_REPLACE = "range_replace"
    SNAPSHOT_UPSERT = "snapshot_upsert"
    NONE = "none"


@dataclass(frozen=True)
class DatasetDefinition:
    """Parquet dataset の境界契約。"""

    dataset_id: str
    provider: str
    domain: DataDomain
    path: str
    partition_policy: PartitionPolicy
    compaction_strategy: CompactionStrategy
    event_time_column: str | None = None
    dedupe_key: str | None = None
    sort_key: str | None = None
    snapshot_file_name: str | None = None

    def __post_init__(self) -> None:
        if self.path.startswith("/") or self.path.endswith("/"):
            raise ValueError(f"invalid_dataset_path: {self.path}")
        if self.partition_policy is PartitionPolicy.SNAPSHOT and not (
            self.snapshot_file_name
        ):
            raise ValueError(f"snapshot_file_name_required: {self.dataset_id}")
        if (
            self.compaction_strategy is CompactionStrategy.APPEND_DEDUPE
            and not self.dedupe_key
        ):
            raise ValueError(f"dedupe_key_required: {self.dataset_id}")

    def source_prefix(self, root_path: str) -> str:
        """events/master root から dataset prefix を組み立てる。"""
        return f"{_normalize_path(root_path)}{self.path}/"

    def source_partition_prefix(self, root_path: str, *, year: int, month: int) -> str:
        """月次 partition の source prefix を組み立てる。"""
        return f"{self.source_prefix(root_path)}year={year}/month={month:02d}/"

    def source_glob(self, root_path: str) -> str:
        """source dataset 全体の再帰 glob を組み立てる。"""
        return f"{self.source_prefix(root_path)}**/*.parquet"

    def source_snapshot_key(self, root_path: str) -> str:
        """snapshot dataset の固定 source key を組み立てる。"""
        if not self.snapshot_file_name:
            raise ValueError(f"snapshot_file_name_required: {self.dataset_id}")
        return f"{self.source_prefix(root_path)}{self.snapshot_file_name}"

    def compacted_prefix(self, compacted_root: str) -> str:
        """compacted root から dataset prefix を組み立てる。"""
        return f"{_normalize_path(compacted_root)}{self.domain.value}/{self.path}/"

    def compacted_partition_key(
        self,
        compacted_root: str,
        *,
        year: int,
        month: int,
    ) -> str:
        """月次 compacted parquet key を組み立てる。"""
        return (
            f"{self.compacted_prefix(compacted_root)}"
            f"year={year}/month={month:02d}/data.parquet"
        )


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


class datasets:
    """Dataset 定義の名前空間。"""

    SPOTIFY_PLAYS = DatasetDefinition(
        dataset_id="spotify.plays",
        provider="spotify",
        domain=DataDomain.EVENTS,
        path="spotify/plays",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="played_at_utc",
        dedupe_key="play_id",
        sort_key="played_at_utc",
    )
    SPOTIFY_TRACKS = DatasetDefinition(
        dataset_id="spotify.tracks",
        provider="spotify",
        domain=DataDomain.MASTER,
        path="spotify/tracks",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="updated_at",
        dedupe_key="track_id",
        sort_key="updated_at",
    )
    SPOTIFY_ARTISTS = DatasetDefinition(
        dataset_id="spotify.artists",
        provider="spotify",
        domain=DataDomain.MASTER,
        path="spotify/artists",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="updated_at",
        dedupe_key="artist_id",
        sort_key="updated_at",
    )
    GITHUB_COMMITS = DatasetDefinition(
        dataset_id="github.commits",
        provider="github",
        domain=DataDomain.EVENTS,
        path="github/commits",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="committed_at_utc",
        dedupe_key="commit_event_id",
        sort_key="committed_at_utc",
    )
    GITHUB_PULL_REQUESTS = DatasetDefinition(
        dataset_id="github.pull_requests",
        provider="github",
        domain=DataDomain.EVENTS,
        path="github/pull_requests",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="updated_at_utc",
        dedupe_key="pr_event_id",
        sort_key="updated_at_utc",
    )
    GITHUB_REPOSITORIES = DatasetDefinition(
        dataset_id="github.repositories",
        provider="github",
        domain=DataDomain.MASTER,
        path="github/repositories",
        partition_policy=PartitionPolicy.RECURSIVE,
        compaction_strategy=CompactionStrategy.NONE,
        event_time_column="updated_at_utc",
    )
    BROWSER_HISTORY_PAGE_VIEWS = DatasetDefinition(
        dataset_id="browser_history.page_views",
        provider="browser_history",
        domain=DataDomain.EVENTS,
        path="browser_history/page_views",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="started_at_utc",
        dedupe_key="page_view_id",
        sort_key="started_at_utc",
    )
    YOUTUBE_WATCH_EVENTS = DatasetDefinition(
        dataset_id="youtube.watch_events",
        provider="youtube",
        domain=DataDomain.EVENTS,
        path="youtube/watch_events",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        event_time_column="watched_at_utc",
        dedupe_key="watch_event_id",
        sort_key="watched_at_utc",
    )
    YOUTUBE_VIDEOS = DatasetDefinition(
        dataset_id="youtube.videos",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/videos",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
    )
    YOUTUBE_CHANNELS = DatasetDefinition(
        dataset_id="youtube.channels",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/channels",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
    )
    GOOGLE_HEALTH_DAILY_METRICS = DatasetDefinition(
        dataset_id="google_health.daily_metrics",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/daily_metrics",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        event_time_column="date",
    )
    GOOGLE_HEALTH_SAMPLES = DatasetDefinition(
        dataset_id="google_health.samples",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/samples",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        event_time_column="measured_at_utc",
    )
    GOOGLE_HEALTH_INTERVALS = DatasetDefinition(
        dataset_id="google_health.intervals",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/intervals",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        event_time_column="started_at_utc",
    )
    GOOGLE_HEALTH_SESSIONS = DatasetDefinition(
        dataset_id="google_health.sessions",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/sessions",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        event_time_column="started_at_utc",
    )


ALL_DATASETS = (
    datasets.SPOTIFY_PLAYS,
    datasets.SPOTIFY_TRACKS,
    datasets.SPOTIFY_ARTISTS,
    datasets.GITHUB_COMMITS,
    datasets.GITHUB_PULL_REQUESTS,
    datasets.GITHUB_REPOSITORIES,
    datasets.BROWSER_HISTORY_PAGE_VIEWS,
    datasets.YOUTUBE_WATCH_EVENTS,
    datasets.YOUTUBE_VIDEOS,
    datasets.YOUTUBE_CHANNELS,
    datasets.GOOGLE_HEALTH_DAILY_METRICS,
    datasets.GOOGLE_HEALTH_SAMPLES,
    datasets.GOOGLE_HEALTH_INTERVALS,
    datasets.GOOGLE_HEALTH_SESSIONS,
)

def _build_datasets_by_id(
    dataset_definitions: tuple[DatasetDefinition, ...],
) -> dict[str, DatasetDefinition]:
    datasets_by_id: dict[str, DatasetDefinition] = {}
    for dataset in dataset_definitions:
        if dataset.dataset_id in datasets_by_id:
            raise ValueError(f"duplicate_dataset_id: {dataset.dataset_id}")
        datasets_by_id[dataset.dataset_id] = dataset
    return datasets_by_id


DATASETS_BY_ID = _build_datasets_by_id(ALL_DATASETS)

_MONTHLY_COMPACTION_BY_PROVIDER = {
    "spotify": (
        datasets.SPOTIFY_PLAYS,
        datasets.SPOTIFY_TRACKS,
        datasets.SPOTIFY_ARTISTS,
    ),
    "github": (
        datasets.GITHUB_COMMITS,
        datasets.GITHUB_PULL_REQUESTS,
    ),
    "browser_history": (datasets.BROWSER_HISTORY_PAGE_VIEWS,),
    "youtube": (datasets.YOUTUBE_WATCH_EVENTS,),
}


def get_dataset(dataset_id: str) -> DatasetDefinition:
    """dataset id から定義を返す。"""
    try:
        return DATASETS_BY_ID[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown_dataset: {dataset_id}") from exc


def monthly_compaction_datasets(provider: str) -> tuple[DatasetDefinition, ...]:
    """provider の月次 compaction 対象を返す。"""
    try:
        return _MONTHLY_COMPACTION_BY_PROVIDER[provider]
    except KeyError as exc:
        raise KeyError(f"unknown_provider: {provider}") from exc
