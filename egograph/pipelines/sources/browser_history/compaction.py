"""Browser history compaction helpers."""

import logging
from collections.abc import Iterable
from datetime import datetime

from pipelines.sources.browser_history.storage import BrowserHistoryStorage

logger = logging.getLogger(__name__)

CompactionTarget = tuple[int, int]


def collect_compaction_targets(
    rows: Iterable[dict[str, object]],
) -> tuple[CompactionTarget, ...]:
    """保存対象 rows から compaction 対象月を抽出する。"""
    targets = {
        (started_at.year, started_at.month)
        for row in rows
        if isinstance(started_at := row.get("started_at_utc"), datetime)
    }
    return tuple(sorted(targets))


def compact_browser_history_targets(
    storage: BrowserHistoryStorage,
    targets: Iterable[CompactionTarget],
) -> None:
    """指定月の browser history compact を実行する。"""
    errors: list[tuple[CompactionTarget, Exception]] = []

    for year, month in sorted(set(targets)):
        try:
            key = storage.compact_month(year=year, month=month)
            if key is None:
                logger.info(
                    "Browser history compaction skipped because no records were found "
                    "for target=%s",
                    (year, month),
                )
        except Exception as exc:
            target = (year, month)
            errors.append((target, exc))
            logger.exception(
                "Browser history compaction failed for target=%s",
                target,
            )

    if not errors:
        return

    if len(errors) == 1:
        (year, month), error = errors[0]
        raise RuntimeError(
            f"Browser history compaction failed for {year}-{month:02d}"
        ) from error

    joined_targets = ", ".join(
        f"{year}-{month:02d}: {type(error).__name__}: {error}"
        for (year, month), error in errors
    )
    raise RuntimeError(
        f"Browser history compaction failed for: {joined_targets}"
    ) from errors[0][1]
