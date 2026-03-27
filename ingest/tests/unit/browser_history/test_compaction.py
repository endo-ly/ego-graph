from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ingest.browser_history.compaction import (
    collect_compaction_targets,
    compact_browser_history_targets,
)


def test_collect_compaction_targets_returns_unique_sorted_months():
    rows = [
        {"started_at_utc": datetime(2026, 4, 1, tzinfo=timezone.utc)},
        {"started_at_utc": datetime(2026, 3, 31, tzinfo=timezone.utc)},
        {"started_at_utc": datetime(2026, 4, 2, tzinfo=timezone.utc)},
    ]

    result = collect_compaction_targets(rows)

    assert result == ((2026, 3), (2026, 4))


def test_compact_browser_history_targets_runs_each_month_once():
    storage = MagicMock()

    compact_browser_history_targets(storage, [(2026, 3), (2026, 4), (2026, 3)])

    assert storage.compact_month.call_count == 2
    storage.compact_month.assert_any_call(year=2026, month=3)
    storage.compact_month.assert_any_call(year=2026, month=4)


def test_compact_browser_history_targets_wraps_storage_errors():
    storage = MagicMock()
    storage.compact_month.side_effect = RuntimeError("boom")

    with pytest.raises(
        RuntimeError,
        match="Browser history compaction failed for 2026-03",
    ) as exc_info:
        compact_browser_history_targets(storage, [(2026, 3)])

    assert exc_info.value.__cause__ is not None


def test_compact_browser_history_targets_attempts_all_targets_before_raising():
    storage = MagicMock()

    def side_effect(*, year: int, month: int):
        if (year, month) == (2026, 3):
            raise RuntimeError("march failed")
        return None

    storage.compact_month.side_effect = side_effect

    with pytest.raises(
        RuntimeError,
        match="Browser history compaction failed for 2026-03",
    ):
        compact_browser_history_targets(storage, [(2026, 3), (2026, 4)])

    storage.compact_month.assert_any_call(year=2026, month=3)
    storage.compact_month.assert_any_call(year=2026, month=4)
    assert storage.compact_month.call_count == 2


def test_compact_browser_history_targets_aggregates_multiple_failures():
    storage = MagicMock()

    def side_effect(*, year: int, month: int):
        raise RuntimeError(f"failed-{year}-{month:02d}")

    storage.compact_month.side_effect = side_effect

    with pytest.raises(
        RuntimeError,
        match=(
            "Browser history compaction failed for: "
            "2026-03: RuntimeError: failed-2026-03, "
            "2026-04: RuntimeError: failed-2026-04"
        ),
    ) as exc_info:
        compact_browser_history_targets(storage, [(2026, 3), (2026, 4)])

    assert exc_info.value.__cause__ is not None


def test_compact_browser_history_targets_handles_empty_targets():
    storage = MagicMock()

    compact_browser_history_targets(storage, [])

    storage.compact_month.assert_not_called()
