"""Browser history payload transformation."""

from datetime import datetime, timezone
from hashlib import sha256

from ingest.browser_history.schema import BrowserHistoryItem, BrowserHistoryPayload


def ensure_utc(value: datetime) -> datetime:
    """datetime を UTC aware に正規化する。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_event_id(
    *,
    source_device: str,
    browser: str,
    profile: str,
    item: BrowserHistoryItem,
) -> str:
    """安定した event_id を生成する。"""
    parts = [
        source_device,
        browser,
        profile,
        item.url,
        ensure_utc(item.visit_time).isoformat(),
        item.visit_id or "",
        item.referring_visit_id or "",
        item.transition or "",
    ]
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"browser_history_{digest}"


def transform_payload_to_event_rows(
    payload: BrowserHistoryPayload,
    *,
    ingested_at: datetime | None = None,
) -> list[dict[str, object]]:
    """受信 payload を event parquet 行へ変換する。"""
    normalized_ingested_at = ensure_utc(ingested_at or datetime.now(timezone.utc))
    normalized_synced_at = ensure_utc(payload.synced_at)

    rows: list[dict[str, object]] = []
    for item in payload.items:
        visited_at = ensure_utc(item.visit_time)
        rows.append(
            {
                "event_id": build_event_id(
                    source_device=payload.source_device,
                    browser=payload.browser,
                    profile=payload.profile,
                    item=item,
                ),
                "visited_at_utc": visited_at,
                "url": item.url,
                "title": item.title,
                "browser": payload.browser,
                "profile": payload.profile,
                "source_device": payload.source_device,
                "visit_id": item.visit_id,
                "referring_visit_id": item.referring_visit_id,
                "transition": item.transition,
                "visit_count": item.visit_count,
                "synced_at_utc": normalized_synced_at,
                "ingested_at_utc": normalized_ingested_at,
            }
        )

    return rows
