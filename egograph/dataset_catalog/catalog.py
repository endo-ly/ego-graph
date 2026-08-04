"""Parquet dataset catalog definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import SimpleNamespace

from dataset_catalog.canonical import VALID_CANONICAL_TYPES


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
    schema_version: int = 1
    required_columns: tuple[str, ...] = ()
    column_types: dict[str, str] = field(default_factory=dict)
    # 過去世代のsourceには任意列がない場合があるため、全日時列の一覧は
    # required schema契約と分離し、存在する場合だけ正規化できるようにする。
    timestamp_columns: tuple[str, ...] = ()

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
        if not self.required_columns:
            raise ValueError(
                f"invalid_schema: required_columns_empty: {self.dataset_id}"
            )
        if len(self.required_columns) != len(set(self.required_columns)):
            raise ValueError(
                f"invalid_schema: duplicate_required_columns: {self.dataset_id}"
            )
        if len(self.timestamp_columns) != len(set(self.timestamp_columns)):
            raise ValueError(
                f"invalid_schema: duplicate_timestamp_columns: {self.dataset_id}"
            )
        missing_column_types = set(self.required_columns) - set(self.column_types)
        if missing_column_types:
            raise ValueError(
                "invalid_schema: required_column_type_missing: "
                f"{self.dataset_id} "
                f"<{', '.join(sorted(missing_column_types))}>"
            )
        for role, column in (
            ("time_column", self.time_column),
            ("dedupe_key", self.dedupe_key),
            ("sort_key", self.sort_key),
        ):
            if column is not None and column not in self.required_columns:
                raise ValueError(
                    f"invalid_schema: {role}_not_required: {self.dataset_id} <{column}>"
                )
        for column in self.column_types:
            if column not in self.required_columns:
                raise ValueError(
                    f"invalid_schema: column_type_not_required: "
                    f"{self.dataset_id} <{column}>"
                )
            if self.column_types[column] not in VALID_CANONICAL_TYPES:
                raise ValueError(
                    f"invalid_schema: unknown_column_type: "
                    f"{self.dataset_id} <{column}={self.column_types[column]}>"
                )
        for column in self.timestamp_columns:
            canonical_type = self.column_types.get(column)
            if canonical_type is not None and canonical_type != "timestamp":
                raise ValueError(
                    f"invalid_schema: timestamp_column_type_mismatch: "
                    f"{self.dataset_id} <{column}={canonical_type}>"
                )

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
        required_columns=("play_id", "played_at_utc", "track_id", "track_name"),
        column_types={
            "play_id": "string",
            "played_at_utc": "timestamp",
            "track_id": "string",
            "track_name": "string",
        },
        timestamp_columns=("played_at_utc", "ingested_at_utc"),
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
        required_columns=("track_id", "name", "updated_at"),
        column_types={
            "track_id": "string",
            "name": "string",
            "updated_at": "timestamp",
        },
        timestamp_columns=("updated_at",),
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
        required_columns=("artist_id", "name", "updated_at"),
        column_types={
            "artist_id": "string",
            "name": "string",
            "updated_at": "timestamp",
        },
        timestamp_columns=("updated_at",),
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
        required_columns=(
            "commit_event_id",
            "repo_full_name",
            "sha",
            "committed_at_utc",
        ),
        column_types={
            "commit_event_id": "string",
            "repo_full_name": "string",
            "sha": "string",
            "committed_at_utc": "timestamp",
        },
        timestamp_columns=("committed_at_utc", "ingested_at_utc"),
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
        required_columns=(
            "pr_event_id",
            "repo_full_name",
            "pr_number",
            "updated_at_utc",
        ),
        column_types={
            "pr_event_id": "string",
            "repo_full_name": "string",
            "pr_number": "integer",
            "updated_at_utc": "timestamp",
        },
        timestamp_columns=(
            "created_at_utc",
            "updated_at_utc",
            "closed_at_utc",
            "merged_at_utc",
            "ingested_at_utc",
        ),
    ),
    GITHUB_REPOSITORIES=DatasetDefinition(
        dataset_id="github.repositories",
        provider="github",
        domain=DataDomain.MASTER,
        path="github/repositories",
        partition_policy=PartitionPolicy.RECURSIVE,
        compaction_strategy=CompactionStrategy.NONE,
        time_column="updated_at_utc",
        required_columns=("repo_id", "repo_full_name", "updated_at_utc"),
        column_types={
            "repo_id": "integer",
            "repo_full_name": "string",
            "updated_at_utc": "timestamp",
        },
        timestamp_columns=(
            "created_at_utc",
            "updated_at_utc",
            "pushed_at_utc",
            "summary_updated_at_utc",
        ),
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
        required_columns=(
            "page_view_id",
            "started_at_utc",
            "url",
            "source_device",
            "ingested_at_utc",
        ),
        column_types={
            "page_view_id": "string",
            "started_at_utc": "timestamp",
            "url": "string",
            "source_device": "string",
            "ingested_at_utc": "timestamp",
        },
        timestamp_columns=(
            "started_at_utc",
            "ended_at_utc",
            "synced_at_utc",
            "ingested_at_utc",
        ),
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
        required_columns=(
            "watch_event_id",
            "watched_at_utc",
            "video_id",
            "source_event_id",
        ),
        column_types={
            "watch_event_id": "string",
            "watched_at_utc": "timestamp",
            "video_id": "string",
            "source_event_id": "string",
        },
        timestamp_columns=("watched_at_utc", "ingested_at_utc"),
    ),
    YOUTUBE_VIDEOS=DatasetDefinition(
        dataset_id="youtube.videos",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/videos",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
        required_columns=("video_id", "title", "updated_at"),
        column_types={
            "video_id": "string",
            "title": "string",
            "updated_at": "timestamp",
        },
        timestamp_columns=("published_at", "updated_at"),
    ),
    YOUTUBE_CHANNELS=DatasetDefinition(
        dataset_id="youtube.channels",
        provider="youtube",
        domain=DataDomain.MASTER,
        path="youtube/channels",
        partition_policy=PartitionPolicy.SNAPSHOT,
        compaction_strategy=CompactionStrategy.SNAPSHOT_UPSERT,
        snapshot_file_name="data.parquet",
        required_columns=("channel_id", "channel_name", "updated_at"),
        column_types={
            "channel_id": "string",
            "channel_name": "string",
            "updated_at": "timestamp",
        },
        timestamp_columns=("published_at", "updated_at"),
    ),
    GOOGLE_HEALTH_DAILY_METRICS=DatasetDefinition(
        dataset_id="google_health.daily_metrics",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/daily_metrics",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="date",
        required_columns=("connection_id", "date", "metric_name", "value"),
        column_types={
            "connection_id": "string",
            "date": "date",
            "metric_name": "string",
            "value": "float",
        },
        timestamp_columns=("ingested_at_utc",),
    ),
    GOOGLE_HEALTH_SAMPLES=DatasetDefinition(
        dataset_id="google_health.samples",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/samples",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="measured_at_utc",
        required_columns=("connection_id", "measured_at_utc", "value"),
        column_types={
            "connection_id": "string",
            "measured_at_utc": "timestamp",
            "value": "float",
        },
        timestamp_columns=("measured_at_utc", "ingested_at_utc"),
    ),
    GOOGLE_HEALTH_INTERVALS=DatasetDefinition(
        dataset_id="google_health.intervals",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/intervals",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="started_at_utc",
        required_columns=("connection_id", "started_at_utc", "value"),
        column_types={
            "connection_id": "string",
            "started_at_utc": "timestamp",
            "value": "float",
        },
        timestamp_columns=(
            "started_at_utc",
            "ended_at_utc",
            "ingested_at_utc",
        ),
    ),
    GOOGLE_HEALTH_SESSIONS=DatasetDefinition(
        dataset_id="google_health.sessions",
        provider="google_health",
        domain=DataDomain.EVENTS,
        path="google_health/sessions",
        partition_policy=PartitionPolicy.MONTHLY,
        compaction_strategy=CompactionStrategy.RANGE_REPLACE,
        time_column="started_at_utc",
        required_columns=("connection_id", "session_id", "started_at_utc"),
        column_types={
            "connection_id": "string",
            "session_id": "string",
            "started_at_utc": "timestamp",
        },
        timestamp_columns=(
            "started_at_utc",
            "ended_at_utc",
            "ingested_at_utc",
        ),
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
