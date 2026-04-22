"""YouTube derived dataset storage."""

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


class YouTubeStorage:
    """YouTube watch events と master 保存、browser history 読み出しを扱う。"""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        *,
        events_path: str = "events/",
        master_path: str = "master/",
        state_path: str = "state/",
    ) -> None:
        self.bucket_name = bucket_name
        self.events_path = _normalize_path(events_path)
        self.master_path = _normalize_path(master_path)
        self.state_path = _normalize_path(state_path)
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def build_sync_state_key(self, sync_id: str) -> str:
        """browser history sync 単位の処理済み state key を返す。"""
        return f"{self.state_path}youtube/browser_history_syncs/{sync_id}.json"

    def is_sync_processed(self, sync_id: str) -> bool:
        """指定 sync_id が既に処理済みかを返す。"""
        key = self.build_sync_state_key(sync_id)
        try:
            self.s3.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                return False
            logger.exception("Failed to get youtube sync state")
            raise
        return True

    def mark_sync_processed(
        self,
        sync_id: str,
        *,
        processed_at: datetime,
        target_months: tuple[tuple[int, int], ...],
        watch_event_count: int,
    ) -> None:
        """sync 単位の処理完了 state を保存する。"""
        body = {
            "sync_id": sync_id,
            "processed_at": processed_at.isoformat(),
            "target_months": [
                {"year": year, "month": month} for year, month in target_months
            ],
            "watch_event_count": watch_event_count,
        }
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=self.build_sync_state_key(sync_id),
            Body=json.dumps(body).encode("utf-8"),
            ContentType="application/json",
        )

    def load_browser_history_page_views(
        self,
        *,
        sync_id: str,
        target_months: tuple[tuple[int, int], ...],
    ) -> list[dict[str, Any]]:
        """browser history parquet から対象 sync_id の page view rows を取得する。"""
        rows: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for year, month in target_months:
            prefix = (
                f"{self.events_path}browser_history/page_views/"
                f"year={year}/month={month:02d}/"
            )
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if not key.endswith(".parquet") or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
                    frame = pd.read_parquet(BytesIO(response["Body"].read()))
                    records = frame.to_dict(orient="records")
                    rows.extend(
                        row for row in records if str(row.get("sync_id")) == sync_id
                    )
        return rows

    def save_watch_events(
        self,
        rows: list[dict[str, Any]],
        *,
        year: int,
        month: int,
        sync_id: str,
    ) -> str | None:
        """watch events parquet を sync_id 単位の安定キーで保存する。"""
        if not rows:
            return None
        key = (
            f"{self.events_path}youtube/watch_events/year={year}/month={month:02d}/"
            f"sync_id={sync_id}.parquet"
        )
        return self._save_dataframe_key(rows, key)

    def save_video_master(
        self,
        rows: list[dict[str, Any]],
        *,
        year: int,
        month: int,
        sync_id: str,
    ) -> str | None:
        """video master parquet を保存する。"""
        if not rows:
            return None
        key = (
            f"{self.master_path}youtube/videos/year={year}/month={month:02d}/"
            f"sync_id={sync_id}.parquet"
        )
        return self._save_dataframe_key(rows, key)

    def save_channel_master(
        self,
        rows: list[dict[str, Any]],
        *,
        year: int,
        month: int,
        sync_id: str,
    ) -> str | None:
        """channel master parquet を保存する。"""
        if not rows:
            return None
        key = (
            f"{self.master_path}youtube/channels/year={year}/month={month:02d}/"
            f"sync_id={sync_id}.parquet"
        )
        return self._save_dataframe_key(rows, key)

    def _save_dataframe_key(self, rows: list[dict[str, Any]], key: str) -> str | None:
        try:
            buffer = BytesIO()
            pd.DataFrame(rows).to_parquet(buffer, index=False, engine="pyarrow")
            buffer.seek(0)
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
        except Exception:
            logger.exception("Failed to save youtube parquet: key=%s", key)
            return None
        return key
