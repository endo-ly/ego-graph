"""Daily Timeline の MCP 向け compact 表現。"""

from typing import Any


def compact_daily_timeline(response: dict[str, Any]) -> dict[str, Any]:
    """Daily Timeline の完全形を MCP 向けの軽量な表現へ変換する。

    REST API と内部の canonical response は変更せず、MCP の表示に必要な
    情報だけを残す。``0`` や ``False`` は有効値のため削除しない。
    """
    compact: dict[str, Any] = dict(response)
    compact["range"] = _compact_range(response.get("range"))
    compact["items"] = [_compact_item(item) for item in response.get("items", [])]
    compact["correlations"] = [
        _compact_correlation(correlation)
        for correlation in response.get("correlations", [])
    ]
    compact["gaps"] = [_compact_gap(gap) for gap in response.get("gaps", [])]
    compact["meta"] = {
        **(response.get("meta") or {}),
        "format": "compact",
    }
    return _drop_empty(compact)


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    """Timeline item の重複時刻・metadata・event_id・空値を省く。"""
    return _drop_empty(
        {
            "started_at": item.get("started_at_local"),
            "ended_at": item.get("ended_at_local"),
            "source": item.get("source"),
            "kind": item.get("kind"),
            "duration_seconds": item.get("duration_seconds"),
            "title": item.get("title"),
            "subtitle": item.get("subtitle"),
            "url": item.get("url"),
            "raw_ref": item.get("raw_ref"),
        }
    )


def _compact_correlation(correlation: dict[str, Any]) -> dict[str, Any]:
    """Correlation からイベントID参照を省く。"""
    return _drop_empty(
        {
            "correlation_id": correlation.get("correlation_id"),
            "kind": correlation.get("kind"),
            "confidence": correlation.get("confidence"),
            "reason": correlation.get("reason"),
        }
    )


def _compact_range(time_range: dict[str, Any] | None) -> dict[str, Any]:
    """対象範囲を要求された timezone の local 時刻だけで表す。"""
    if not time_range:
        return {}
    return _drop_empty(
        {
            "start": time_range.get("start_local"),
            "end": time_range.get("end_local"),
        }
    )


def _compact_gap(gap: dict[str, Any]) -> dict[str, Any]:
    """Gap の UTC/local 重複とイベントID参照を省き、local 時刻を返す。"""
    return _drop_empty(
        {
            "gap_id": gap.get("gap_id"),
            "kind": gap.get("kind"),
            "start": gap.get("start_local"),
            "end": gap.get("end_local"),
            "duration_minutes": gap.get("duration_minutes"),
        }
    )


def _drop_empty(value: Any) -> Any:
    """JSON値から ``None`` と空コンテナだけを再帰的に除く。"""
    if isinstance(value, dict):
        compact = {key: _drop_empty(item) for key, item in value.items()}
        return {key: item for key, item in compact.items() if not _is_empty(item)}
    if isinstance(value, list):
        compact = [_drop_empty(item) for item in value]
        return [item for item in compact if not _is_empty(item)]
    return value


def _is_empty(value: Any) -> bool:
    """``0`` と ``False`` を除き、JSON上の空値だけを判定する。"""
    if value is None:
        return True
    if isinstance(value, (str, list, dict)):
        return not value
    return False
