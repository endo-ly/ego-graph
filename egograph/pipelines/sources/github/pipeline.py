"""In-process GitHub pipeline entrypoints for workflow steps."""

import logging
from collections.abc import Iterable

from dataset_catalog import monthly_compaction_datasets

from pipelines.compaction import (
    DatasetCompactionTarget,
    compaction_targets_from_run,
    resolve_run_compaction_targets,
)
from pipelines.domain.workflow import WorkflowRun
from pipelines.sources.common.config import Config
from pipelines.sources.common.settings import PipelinesSettings
from pipelines.sources.github.ingest_pipeline import (
    run_pipeline as _run_ingest_pipeline,
)
from pipelines.sources.github.storage import GitHubWorklogStorage

logger = logging.getLogger(__name__)


def run_github_ingest(config: Config | None = None) -> dict[str, object]:
    """GitHub ingest を in-process で実行する。"""
    resolved_config = config or PipelinesSettings.load()
    _run_ingest_pipeline(resolved_config)
    return {"provider": "github", "operation": "ingest", "status": "succeeded"}


def run_github_compact(
    config: Config | None = None,
    *,
    year: int | None = None,
    month: int | None = None,
    targets: Iterable[DatasetCompactionTarget] | None = None,
) -> dict[str, object]:
    """GitHub monthly compaction を in-process で実行する。"""
    resolved_config = config or PipelinesSettings.load()
    if not resolved_config.duckdb or not resolved_config.duckdb.r2:
        raise ValueError("R2 configuration is required for compaction")

    r2_conf = resolved_config.duckdb.r2
    storage = GitHubWorklogStorage(
        endpoint_url=r2_conf.endpoint_url,
        access_key_id=r2_conf.access_key_id,
        secret_access_key=r2_conf.secret_access_key.get_secret_value(),
        bucket_name=r2_conf.bucket_name,
        raw_path=r2_conf.raw_path,
        events_path=r2_conf.events_path,
        master_path=r2_conf.master_path,
    )

    compaction_targets = resolve_run_compaction_targets(
        "github",
        targets=targets,
        year=year,
        month=month,
    )
    datasets_by_id = {
        dataset.dataset_id: dataset for dataset in monthly_compaction_datasets("github")
    }
    compacted_keys: list[str] = []
    skipped_targets: list[str] = []
    failures: list[str] = []
    for target in compaction_targets:
        dataset = datasets_by_id[target.dataset_id]
        try:
            key = storage.compact_month(
                dataset=dataset,
                year=target.year,
                month=target.month,
            )
        except Exception:
            logger.exception(
                "GitHub compaction failed: dataset=%s year=%d month=%02d",
                dataset.path,
                target.year,
                target.month,
            )
            failures.append(f"{dataset.path}:{target.year}-{target.month:02d}")
            continue
        if key is None:
            skipped_targets.append(f"{dataset.path}:{target.year}-{target.month:02d}")
        else:
            compacted_keys.append(key)

    if failures:
        raise RuntimeError(f"GitHub compaction failed for: {', '.join(failures)}")

    return {
        "provider": "github",
        "operation": "compact",
        "target_months": sorted(
            {f"{target.year}-{target.month:02d}" for target in compaction_targets}
        ),
        "compacted_keys": compacted_keys,
        "skipped_targets": skipped_targets,
    }


def run_github_compact_from_run(run: WorkflowRun) -> dict[str, object]:
    """manual compaction run の対象datasetとpartitionを復元して実行する。"""
    return run_github_compact(targets=compaction_targets_from_run(run))
