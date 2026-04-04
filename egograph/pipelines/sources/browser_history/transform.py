"""Browser history payload transformation."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from pipelines.sources.browser_history.schema import (
    BrowserHistoryItem,
    BrowserHistoryPayload,
)

PAGE_VIEW_CLUSTER_WINDOW = timedelta(seconds=2)
_TRANSITION_PRIORITY = {
    "typed": 0,
    "link": 1,
    "auto_bookmark": 2,
    "form_submit": 3,
    "reload": 4,
    "keyword": 5,
    "keyword_generated": 6,
    "manual_subframe": 7,
    "auto_subframe": 8,
}


def ensure_utc(value: datetime) -> datetime:
    """datetime を UTC aware に正規化する。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_page_view_id(
    *,
    source_device: str,
    browser: str,
    profile: str,
    url: str,
    started_at: datetime,
    ended_at: datetime,
    transition: str | None,
) -> str:
    """安定した page_view_id を生成する。"""
    parts = [
        source_device,
        browser,
        profile,
        url,
        ensure_utc(started_at).isoformat(),
        ensure_utc(ended_at).isoformat(),
        transition or "",
    ]
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"browser_history_page_view_{digest}"


def _pick_transition(items: list[BrowserHistoryItem]) -> str | None:
    ranked = [item.transition for item in items if item.transition is not None]
    if not ranked:
        return None
    return min(ranked, key=lambda value: (_TRANSITION_PRIORITY.get(value, 999), value))


def _pick_title(items: list[BrowserHistoryItem]) -> str | None:
    for item in reversed(items):
        if item.title:
            return item.title
    return None


def _cluster_items(items: list[BrowserHistoryItem]) -> list[list[BrowserHistoryItem]]:
    if not items:
        return []

    sorted_items = sorted(items, key=lambda item: ensure_utc(item.visit_time))
    clusters: list[list[BrowserHistoryItem]] = [[sorted_items[0]]]

    for item in sorted_items[1:]:
        previous_item = clusters[-1][-1]
        gap = ensure_utc(item.visit_time) - ensure_utc(previous_item.visit_time)
        if gap <= PAGE_VIEW_CLUSTER_WINDOW:
            clusters[-1].append(item)
        else:
            clusters.append([item])

    return clusters


def transform_payload_to_page_view_rows(
    payload: BrowserHistoryPayload,
    *,
    ingested_at: datetime | None = None,
) -> list[dict[str, object]]:
    """受信 payload を page view parquet 行へ変換する。"""
    normalized_ingested_at = ensure_utc(ingested_at or datetime.now(timezone.utc))
    normalized_synced_at = ensure_utc(payload.synced_at)

    items_by_url: dict[str, list[BrowserHistoryItem]] = defaultdict(list)
    for item in payload.items:
        items_by_url[item.url].append(item)

    rows: list[dict[str, object]] = []
    for url, items in items_by_url.items():
        for cluster in _cluster_items(items):
            started_at = ensure_utc(cluster[0].visit_time)
            ended_at = ensure_utc(cluster[-1].visit_time)
            transition = _pick_transition(cluster)
            rows.append(
                {
                    "page_view_id": build_page_view_id(
                        source_device=payload.source_device,
                        browser=payload.browser,
                        profile=payload.profile,
                        url=url,
                        started_at=started_at,
                        ended_at=ended_at,
                        transition=transition,
                    ),
                    "started_at_utc": started_at,
                    "ended_at_utc": ended_at,
                    "url": url,
                    "title": _pick_title(cluster),
                    "browser": payload.browser,
                    "profile": payload.profile,
                    "source_device": payload.source_device,
                    "transition": transition,
                    "visit_span_count": len(cluster),
                    "synced_at_utc": normalized_synced_at,
                    "ingested_at_utc": normalized_ingested_at,
                }
            )

    return sorted(rows, key=lambda row: row["started_at_utc"], reverse=True)
