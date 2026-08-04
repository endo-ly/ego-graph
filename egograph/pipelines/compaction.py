"""外部から指定された dataset compaction の入力と dispatch を扱う。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dataset_catalog import (
    ALL_DATASETS,
    CompactionStrategy,
    DatasetDefinition,
    PartitionPolicy,
    get_dataset,
    monthly_compaction_datasets,
)

from pipelines.domain.workflow import WorkflowRun
from pipelines.sources.common.compaction import resolve_target_months

MANUAL_COMPACTION_WORKFLOW_BY_PROVIDER = {
    "spotify": "spotify_compact_workflow",
    "github": "github_compact_workflow",
    "browser_history": "browser_history_compact_workflow_manual",
    "youtube": "youtube_compact_workflow",
}


@dataclass(frozen=True)
class DatasetCompactionTarget:
    """月次 compaction の対象 dataset と partition。"""

    dataset_id: str
    year: int
    month: int

    def __post_init__(self) -> None:
        if not self.dataset_id.strip():
            raise ValueError("invalid_dataset_id: dataset_id is required")
        if not 1 <= self.year <= 9999:
            raise ValueError("invalid_year: year must be 1..9999")
        if not 1 <= self.month <= 12:
            raise ValueError("invalid_month: month must be 1..12")

    def to_dict(self) -> dict[str, object]:
        """run の result_summary に保存できる辞書へ変換する。"""
        return {
            "dataset_id": self.dataset_id,
            "year": self.year,
            "month": self.month,
        }


def validate_compaction_targets(
    targets: Iterable[DatasetCompactionTarget],
) -> tuple[DatasetCompactionTarget, ...]:
    """manual compaction の対象をcatalog契約に基づいて検証する。

    現在の manual compaction API は、月次 ``APPEND_DEDUPE`` datasetを対象とする。
    同一run内の対象providerを一つに制限することで、既存workflowのprovider単位
    lockと定期ingestとの排他を維持する。
    """
    normalized = tuple(dict.fromkeys(targets))
    if not normalized:
        raise ValueError("invalid_targets: at least one target is required")

    providers: set[str] = set()
    for target in normalized:
        try:
            dataset = get_dataset(target.dataset_id)
        except KeyError as exc:
            raise ValueError(
                f"invalid_dataset_id: unknown dataset: {target.dataset_id}"
            ) from exc

        if dataset.partition_policy is not PartitionPolicy.MONTHLY:
            raise ValueError(
                "invalid_dataset_id: dataset does not use monthly partitions: "
                f"{target.dataset_id}"
            )
        if dataset.compaction_strategy is not CompactionStrategy.APPEND_DEDUPE:
            raise ValueError(
                "invalid_dataset_id: dataset compaction strategy is not supported: "
                f"{target.dataset_id}"
            )
        if dataset.provider not in MANUAL_COMPACTION_WORKFLOW_BY_PROVIDER:
            raise ValueError(
                "invalid_dataset_id: provider does not support manual compaction: "
                f"{dataset.provider}"
            )
        providers.add(dataset.provider)

    if len(providers) != 1:
        raise ValueError(
            "invalid_targets: all targets must belong to the same provider"
        )
    return normalized


def compaction_workflow_id(
    targets: Iterable[DatasetCompactionTarget],
) -> str:
    """対象providerに対応するmanual compaction workflow IDを返す。"""
    validated = validate_compaction_targets(targets)
    dataset = get_dataset(validated[0].dataset_id)
    return MANUAL_COMPACTION_WORKFLOW_BY_PROVIDER[dataset.provider]


def compaction_targets_from_run(
    run: WorkflowRun,
) -> tuple[DatasetCompactionTarget, ...]:
    """run の result_summary から compaction target を復元する。"""
    summary = run.result_summary or {}
    raw_targets = summary.get("compaction_targets")
    if not isinstance(raw_targets, list):
        raise ValueError("invalid_targets: compaction targets are required")

    targets: list[DatasetCompactionTarget] = []
    for index, raw_target in enumerate(raw_targets):
        if not isinstance(raw_target, Mapping):
            raise ValueError(f"invalid_targets: target at index {index} is invalid")
        dataset_id = raw_target.get("dataset_id")
        year = raw_target.get("year")
        month = raw_target.get("month")
        if not isinstance(dataset_id, str):
            raise ValueError(
                f"invalid_targets: target at index {index} has invalid dataset_id"
            )
        if isinstance(year, bool) or not isinstance(year, int):
            raise ValueError(
                f"invalid_targets: target at index {index} has invalid year"
            )
        if isinstance(month, bool) or not isinstance(month, int):
            raise ValueError(
                f"invalid_targets: target at index {index} has invalid month"
            )
        targets.append(
            DatasetCompactionTarget(
                dataset_id=dataset_id,
                year=year,
                month=month,
            )
        )
    return validate_compaction_targets(targets)


def select_compaction_datasets(
    provider: str,
    dataset_ids: Iterable[str] | None = None,
) -> tuple[DatasetDefinition, ...]:
    """provider の月次compaction対象をcatalogから選択する。"""
    try:
        available = monthly_compaction_datasets(provider)
    except KeyError as exc:
        raise ValueError(f"invalid_provider: unsupported provider: {provider}") from exc

    if dataset_ids is None:
        return available

    requested_ids = tuple(dict.fromkeys(dataset_ids))
    available_by_id = {dataset.dataset_id: dataset for dataset in available}
    unknown_ids = [
        dataset_id for dataset_id in requested_ids if dataset_id not in available_by_id
    ]
    if unknown_ids:
        raise ValueError(
            "invalid_dataset_id: dataset is not a monthly compaction target: "
            f"{', '.join(sorted(unknown_ids))}"
        )
    return tuple(available_by_id[dataset_id] for dataset_id in requested_ids)


def resolve_provider_compaction_targets(
    provider: str,
    *,
    year: int | None = None,
    month: int | None = None,
    dataset_ids: Iterable[str] | None = None,
) -> tuple[DatasetCompactionTarget, ...]:
    """既存scheduled compact用のprovider対象を解決する。"""
    datasets = select_compaction_datasets(provider, dataset_ids)
    months = resolve_target_months(year, month)
    return tuple(
        DatasetCompactionTarget(
            dataset_id=dataset.dataset_id,
            year=target_year,
            month=target_month,
        )
        for target_year, target_month in months
        for dataset in datasets
    )


def resolve_run_compaction_targets(
    provider: str,
    *,
    targets: Iterable[DatasetCompactionTarget] | None = None,
    year: int | None = None,
    month: int | None = None,
    dataset_ids: Iterable[str] | None = None,
) -> tuple[DatasetCompactionTarget, ...]:
    """workflow入力またはscheduled compact用の対象を解決する。"""
    if targets is not None:
        if year is not None or month is not None or dataset_ids is not None:
            raise ValueError(
                "invalid_targets: targets cannot be combined with year, month, "
                "or dataset_ids"
            )
        validated = validate_compaction_targets(targets)
        invalid_provider_targets = [
            target.dataset_id
            for target in validated
            if get_dataset(target.dataset_id).provider != provider
        ]
        if invalid_provider_targets:
            raise ValueError(
                "invalid_targets: target does not belong to provider: "
                f"{', '.join(invalid_provider_targets)}"
            )
        return validated

    return resolve_provider_compaction_targets(
        provider,
        year=year,
        month=month,
        dataset_ids=dataset_ids,
    )


def dataset_metadata(dataset: DatasetDefinition) -> dict[str, Any]:
    """dataset catalogの公開用メタデータを返す。"""
    return {
        "dataset_id": dataset.dataset_id,
        "path": dataset.path,
        "provider": dataset.provider,
        "domain": dataset.domain.value,
        "partition_policy": dataset.partition_policy.value,
        "compaction_strategy": dataset.compaction_strategy.value,
        "compaction_supported": (
            dataset.provider in MANUAL_COMPACTION_WORKFLOW_BY_PROVIDER
            and dataset.partition_policy is PartitionPolicy.MONTHLY
            and dataset.compaction_strategy is CompactionStrategy.APPEND_DEDUPE
        ),
        "schema_version": dataset.schema_version,
    }


def list_dataset_metadata() -> list[dict[str, Any]]:
    """全datasetの公開用メタデータをcatalog順で返す。"""
    return [dataset_metadata(dataset) for dataset in ALL_DATASETS]
