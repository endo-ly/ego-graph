"""Google Takeout YouTube視聴履歴HTML → 新watch_events Parquet 変換スクリプト。

日本語ロケール形式専用:
  - 「を視聴しました」
  - タイムスタンプ: YYYY/MM/DD HH:MM:SS JST
  - 「サービス: YouTube」

使い方:
  uv run python scripts/convert_takeout_html.py watch-history.html --output /tmp/youtube_import
"""

import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup, SoupStrainer

_WATCH_EVENT_PREFIX = "youtube_watch_event_"
_JST_OFFSET = timezone(offset=timezone.utc.utcoffset(None) or __import__("datetime").timedelta(hours=9))


def extract_video_id(url: str) -> str | None:
    """YouTube URLからvideo_idを抽出する。"""
    if not url:
        return None

    # watch?v=
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # shorts/
    m = re.search(r"/shorts/([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # youtu.be/
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    return None


def extract_channel_id(url: str) -> str | None:
    """チャンネルURLからchannel_idを抽出する。"""
    if not url:
        return None
    m = re.search(r"/channel/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def detect_content_type(url: str) -> str:
    """URLからcontent_typeを判定する。"""
    if "/shorts/" in url:
        return "short"
    return "video"


def parse_jst_timestamp(ts_str: str) -> datetime:
    """日本語形式タイムスタンプをパースしてUTC datetimeに変換する。

    形式: YYYY/MM/DD HH:MM:SS JST
    """
    ts_str = ts_str.strip()
    # YYYY/MM/DD HH:MM:SS JST
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\s+JST", ts_str)
    if not m:
        return None

    dt = datetime(
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)),
        tzinfo=timezone(__import__("datetime").timedelta(hours=9)),
    )
    return dt.astimezone(timezone.utc)


def parse_watch_history_html(html_path: str) -> list[dict]:
    """HTMLをパースしてwatch eventリストを返す。"""
    path = Path(html_path)
    print(f"Reading {path.stat().st_size / 1024 / 1024:.1f} MB HTML file...")

    data = path.read_text(encoding="utf-8")

    # outer-cellだけをパース（高速化）
    strainer = SoupStrainer("div", class_=lambda c: c and "outer-cell" in c)
    print("Parsing HTML with lxml + SoupStrainer...")
    soup = BeautifulSoup(data, "lxml", parse_only=strainer)

    events = []
    skipped_no_video = 0
    skipped_no_ts = 0
    total_cells = 0

    for outer_div in soup.children:
        if not hasattr(outer_div, "find"):
            continue

        # YouTubeヘッダーの確認
        header_el = outer_div.find("p", class_="mdl-typography--title")
        if not header_el or "YouTube" not in header_el.text:
            continue

        # body content cell (text-right以外のbody-1)
        body_cells = outer_div.find_all(
            "div", class_=lambda c: c and "mdl-typography--body-1" in c
            and "mdl-typography--text-right" not in c
        )
        if not body_cells:
            continue

        body_cell = body_cells[0]
        total_cells += 1

        links = body_cell.find_all("a")
        text = body_cell.get_text()

        # video情報 (1つ目の<a>)
        video_url = links[0]["href"] if len(links) >= 1 else None
        video_title = links[0].text.strip() if len(links) >= 1 else None

        if not video_url:
            skipped_no_video += 1
            continue

        video_id = extract_video_id(video_url)
        if not video_id:
            skipped_no_video += 1
            continue

        # channel情報 (2つ目の<a>)
        channel_url = links[1]["href"] if len(links) >= 2 else None
        channel_name = links[1].text.strip() if len(links) >= 2 else None
        channel_id = extract_channel_id(channel_url) if channel_url else None

        # タイムスタンプ抽出
        ts_match = re.search(r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s+JST)", text)
        if not ts_match:
            skipped_no_ts += 1
            continue

        watched_at_utc = parse_jst_timestamp(ts_match.group(1))
        if watched_at_utc is None:
            skipped_no_ts += 1
            continue

        # 決定的ID生成
        watch_event_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"google_takeout:{video_id}:{watched_at_utc.isoformat()}",
        )

        events.append({
            "watch_event_id": f"{_WATCH_EVENT_PREFIX}{watch_event_uuid}",
            "watched_at_utc": watched_at_utc,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "video_title": video_title,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "content_type": detect_content_type(video_url),
            "source": "google_takeout",
            "source_event_id": video_id,
            "source_device": "google_takeout",
            "ingested_at_utc": datetime.now(timezone.utc),
        })

    print(f"\nParsed {total_cells} content cells")
    print(f"  Extracted events: {len(events)}")
    print(f"  Skipped (no video_id): {skipped_no_video}")
    print(f"  Skipped (no timestamp): {skipped_no_ts}")

    return events


def save_parquet_local(events: list[dict], output_dir: str) -> None:
    """イベントを月次パーティションでローカルParquetに保存する。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 月次グルーピング
    monthly: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in events:
        watched_at = event["watched_at_utc"]
        monthly[(watched_at.year, watched_at.month)].append(event)

    print(f"\nSaving to {out}/")
    for (year, month), rows in sorted(monthly.items()):
        partition_dir = out / f"year={year}" / f"month={month:02d}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        df = pd.DataFrame(rows)
        filepath = partition_dir / "data.parquet"
        df.to_parquet(filepath, index=False, engine="pyarrow")

        # サマリー表示
        unique_videos = df["video_id"].nunique()
        unique_channels = df["channel_id"].nunique()
        print(
            f"  {year}-{month:02d}: {len(rows):>5} events, "
            f"{unique_videos} videos, {unique_channels} channels"
        )

    # 全体サマリー
    total_df = pd.DataFrame(events)
    print(f"\n=== Summary ===")
    print(f"Total events: {len(events)}")
    print(f"Unique videos: {total_df['video_id'].nunique()}")
    print(f"Unique channels: {total_df['channel_id'].nunique()}")
    print(f"Date range: {total_df['watched_at_utc'].min()} ~ {total_df['watched_at_utc'].max()}")
    print(f"Content types: {total_df['content_type'].value_counts().to_dict()}")
    print(f"Null channel_id: {total_df['channel_id'].isna().sum()}")
    print(f"Null channel_name: {total_df['channel_name'].isna().sum()}")


def filter_events(
    events: list[dict],
    *,
    before: datetime | None = None,
    after: datetime | None = None,
) -> list[dict]:
    """watched_at_utc で絞り込む。"""
    result = events
    if after:
        result = [e for e in result if e["watched_at_utc"] >= after]
    if before:
        result = [e for e in result if e["watched_at_utc"] < before]
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Google Takeout YouTube視聴履歴HTML → Parquet 変換",
    )
    parser.add_argument("html_path", help="入力HTMLファイルパス")
    parser.add_argument("--output", default="/tmp/youtube_import", help="出力ディレクトリ")
    parser.add_argument(
        "--before",
        help="この日時(JST)より前のイベントのみ抽出 (例: 2023/08/17)",
    )
    parser.add_argument(
        "--after",
        help="この日時(JST)以降のイベントのみ抽出 (例: 2021/09/01)",
    )
    args = parser.parse_args()

    before_utc = None
    after_utc = None
    jst = timezone(__import__("datetime").timedelta(hours=9))
    if args.before:
        dt = datetime.strptime(args.before, "%Y/%m/%d").replace(tzinfo=jst)
        before_utc = dt.astimezone(timezone.utc)
    if args.after:
        dt = datetime.strptime(args.after, "%Y/%m/%d").replace(tzinfo=jst)
        after_utc = dt.astimezone(timezone.utc)

    events = parse_watch_history_html(args.html_path)
    if not events:
        print("No events extracted!")
        sys.exit(1)

    if before_utc or after_utc:
        before_label = args.before or "—"
        after_label = args.after or "—"
        print(f"\nFiltering: after={after_label}, before={before_label}")
        events = filter_events(events, before=before_utc, after=after_utc)
        print(f"  Events after filter: {len(events)}")

    if not events:
        print("No events after filtering!")
        sys.exit(1)

    save_parquet_local(events, args.output)
    print(f"\nDone! Files saved to {args.output}")
