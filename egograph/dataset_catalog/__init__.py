"""共有 Dataset Catalog。

Pipelines の保存契約と Backend の読み取り契約を同じ定義から参照する。
"""

from dataset_catalog.catalog import (
    ALL_DATASETS,
    DATASETS_BY_ID,
    CompactionStrategy,
    DataDomain,
    DatasetDefinition,
    PartitionPolicy,
    datasets,
    get_dataset,
    monthly_compaction_datasets,
)

__all__ = [
    "ALL_DATASETS",
    "DATASETS_BY_ID",
    "CompactionStrategy",
    "DataDomain",
    "DatasetDefinition",
    "PartitionPolicy",
    "datasets",
    "get_dataset",
    "monthly_compaction_datasets",
]
