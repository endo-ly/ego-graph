"""Parquet dataset catalog definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import SimpleNamespace


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
    time_column: str | None = None
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

    def source_root(self, events_path: str, master_path: str) -> str:
        """domain に応じた source root を返す。

        source 側は events / master で root が分かれているため、domain ごとに
        対応する root を選択する。compacted 側は単一 root 配下に domain 階層を
        持つため本メソッドの対象外（``compacted_prefix`` を使用）。
        """
        return events_path if self.domain is DataDomain.EVENTS else master_path

    def source_prefix(self, root_path: str) -> str:
        """events/master root から dataset prefix を組み立てる。

        source 側の root は domain 判別済み（events_path / master_path）のため、
        戻り値に domain は含まない。compacted 側は ``compacted_prefix`` を使用。
        """
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

    def required_dedupe_key(self) -> str:
        """dedupe_key を返す。未設定の場合はエラー。"""
        if self.dedupe_key is None:
            raise ValueError(f"dedupe_key_required: {self.dataset_id}")
        return self.dedupe_key

    def compacted_prefix(self, compacted_root: str) -> str:
        """compacted root から dataset prefix を組み立てる。

        compacted 側は単一 root 配下に domain ごとの階層を持つため、戻り値に
        domain を含む。source 側は domain 判別済み root を使うため
        ``source_prefix`` では domain を含まない（これが両者の非対称性）。
        """
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


# DatasetDefinition の名前付きレジストリ。class ではなく SimpleNamespace で
# 「インスタンス（値）」であることを明示する（PEP 8: 型名ではないので小文字）。
datasets = SimpleNamespace(
    SPOTIFY_PLAYS=DatasetDefinition(
        dataset_id="spotify.plays",
        provider="spotify",
        domain=DataDomain.EVENTS,
        path="spotify/plays",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="played_at_utc",
        dedupe_key="play_id",
        sort_key="played_at_utc",
    ),
    SPOTIFY_TRACKS=DatasetDefinition(
        dataset_id="spotify.tracks",
        provider="spotify",
        domain=DataDomain.MASTER,
        path="spotify/tracks",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="updated_at",
        dedupe_key="track_id",
        sort_key="updated_at",
    ),
    SPOTIFY_ARTISTS=DatasetDefinition(
        dataset_id="spotify.artists",
        provider="spotify",
        domain=DataDomain.MASTER,
        path="spotify/artists",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="updated_at",
        dedupe_key="artist_id",
        sort_key="updated_at",
    ),
    GITHUB_COMMITS=DatasetDefinition(
        dataset_id="github.commits",
        provider="github",
        domain=DataDomain.EVENTS,
        path="github/commits",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="committed_at_utc",
        dedupe_key="commit_event_id",
        sort_key="committed_at_utc",
    ),
    GITHUB_PULL_REQUESTS=DatasetDefinition(
        dataset_id="github.pull_requests",
        provider="github",
        domain=DataDomain.EVENTS,
        path="github/pull_requests",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="updated_at_utc",
        dedupe_key="pr_event_id",
        sort_key="updated_at_utc",
    ),
    GITHUB_REPOSITORIES=DatasetDefinition(
        dataset_id="github.repositories",
        provider="github",
        domain=DataDomain.MASTER,
        path="github/repositories",
        partition_policy=PartitionPolicy.RECURSIVE,
        compaction_strategy=CompactionStrategy.NONE,
        time_column="updated_at_utc",
    ),
    BROWSER_HISTORY_PAGE_VIEWS=DatasetDefinition(
        dataset_id="browser_history.page_views",
        provider="browser_history",
        domain=DataDomain.EVENTS,
        path="browser_history/page_views",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="started_at_utc",
        dedupe_key="page_view_id",
        # page_view_id は started_at_utc から生成されるため sort_key として
        # started_at_utc を使うと重複行間で同値になり決定性が失われる。
        # ingested_at_utc で「最新 run のレコード」を確定勝者とする。
        sort_key="ingested_at_utc",
    ),
    YOUTUBE_WATCH_EVENTS=DatasetDefinition(
        dataset_id="youtube.watch_events",
        provider="youtube",
        domain=DataDomain.EVENTS,
        path="youtube/watch_events",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.APPEND_DEDUPE,
        time_column="watched_at_utc",
        dedupe_key="watch_event_id",
        sort_key="watched_at_utc",
    ),
    YOUTUBE_VIDEOS=DatasetDefinition(
        dataset_id="youtube.videos",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/videos",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
    ),
    YOUTUBE_CHANNELS=DatasetDefinition(
        dataset_id="youtube.channels",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/channels",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
    ),
    GOOGLE_HEALTH_DAILY_METRICS=DatasetDefinition(
        dataset_id="google_health.daily_metrics",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/daily_metrics",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="date",
    ),
    GOOGLE_HEALTH_SAMPLES=DatasetDefinition(
        dataset_id="google_health.samples",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/samples",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="measured_at_utc",
    ),
    GOOGLE_HEALTH_INTERVALS=DatasetDefinition(
        dataset_id="google_health.intervals",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/intervals",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="started_at_utc",
    ),
    GOOGLE_HEALTH_SESSIONS=DatasetDefinition(
        dataset_id="google_health.sessions",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/sessions",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="started_at_utc",
    ),
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


def get_dataset(dataset_id: str) -> DatasetDefinition:
    """dataset id から定義を返す。"""
    try:
        return DATASETS_BY_ID[dataset_id]
    except KeyError as exc:
        raise KeyError(f"unknown_dataset: {dataset_id}") from exc


def monthly_compaction_datasets(provider: str) -> tuple[DatasetDefinition, ...]:
    """provider の月次 append-dedupe compaction 対象を ``ALL_DATASETS`` から導出する。

    ``ALL_DATASETS`` の定義順を維持し、``partition_policy=MONTHLY`` かつ
    ``compaction_strategy=APPEND_DEDUPE`` の dataset のみを返す。新規 dataset 追加時に
    別リストをメンテする必要がなく、リストと定義の drift を構造的に排除する。
    range_replace / snapshot の dataset は自動的に除外される。
    """
    result = tuple(
        dataset
        for dataset in ALL_DATASETS
        if dataset.provider == provider
        and dataset.partition_policy is PartitionPolicy.MONTHLY
        and dataset.compaction_strategy is CompactionStrategy.APPEND_DEDUPE
    )
    if not result:
        raise KeyError(f"unknown_provider: {provider}")
    return result
