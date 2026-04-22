"""YouTube derived dataset storage."""

import json
import logging
import random
import time
from datetime import datetime
from io import BytesIO
from typing import Any

import boto3
import pandas as pd
import pyarrow.parquet as pq
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MAX_MASTER_SAVE_RETRIES = 3
MASTER_SAVE_BACKOFF_SECONDS = 0.2


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
        required_columns = [
            "sync_id",
            "page_view_id",
            "started_at_utc",
            "url",
            "title",
            "source_device",
            "ingested_at_utc",
        ]
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
                    table = pq.read_table(
                        BytesIO(response["Body"].read()),
                        columns=required_columns,
                        filters=[("sync_id", "==", sync_id)],
                    )
                    if table.num_rows == 0:
                        continue
                    frame = table.to_pandas()
                    rows.extend(frame.to_dict(orient="records"))
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

    def build_video_master_key(self) -> str:
        """video master の固定保存キーを返す。"""
        return f"{self.master_path}youtube/videos/data.parquet"

    def build_channel_master_key(self) -> str:
        """channel master の固定保存キーを返す。"""
        return f"{self.master_path}youtube/channels/data.parquet"

    def load_video_master(self) -> list[dict[str, Any]]:
        """既存 video master snapshot を読み込む。"""
        return self._load_master_rows(self.build_video_master_key())

    def load_channel_master(self) -> list[dict[str, Any]]:
        """既存 channel master snapshot を読み込む。"""
        return self._load_master_rows(self.build_channel_master_key())

    def save_video_master(
        self,
        rows: list[dict[str, Any]],
    ) -> str | None:
        """video master snapshot を upsert 保存する。"""
        if not rows:
            return None
        return self._save_master_snapshot_with_retry(
            rows=rows,
            id_key="video_id",
            key=self.build_video_master_key(),
        )

    def save_channel_master(
        self,
        rows: list[dict[str, Any]],
    ) -> str | None:
        """channel master snapshot を upsert 保存する。"""
        if not rows:
            return None
        return self._save_master_snapshot_with_retry(
            rows=rows,
            id_key="channel_id",
            key=self.build_channel_master_key(),
        )

    def _load_master_rows(self, key: str) -> list[dict[str, Any]]:
        rows, _ = self._load_master_rows_with_etag(key)
        return rows

    def _load_master_rows_with_etag(
        self, key: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                return [], None
            logger.exception("Failed to load youtube master snapshot: key=%s", key)
            raise
        frame = pd.read_parquet(BytesIO(response["Body"].read()), engine="pyarrow")
        etag = response.get("ETag") if isinstance(response.get("ETag"), str) else None
        return frame.to_dict(orient="records"), etag

    def _merge_master_rows(
        self,
        *,
        existing_rows: list[dict[str, Any]],
        incoming_rows: list[dict[str, Any]],
        id_key: str,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for row in existing_rows:
            row_id = row.get(id_key)
            if isinstance(row_id, str) and row_id:
                merged[row_id] = row
        for row in incoming_rows:
            row_id = row.get(id_key)
            if isinstance(row_id, str) and row_id:
                merged[row_id] = row
        return [merged[row_id] for row_id in sorted(merged)]

    def _save_dataframe_key(self, rows: list[dict[str, Any]], key: str) -> str | None:
        return self._save_dataframe_key_with_condition(rows, key)

    def _save_master_snapshot_with_retry(
        self,
        *,
        rows: list[dict[str, Any]],
        id_key: str,
        key: str,
    ) -> str | None:
        for attempt in range(MAX_MASTER_SAVE_RETRIES):
            existing_rows, etag = self._load_master_rows_with_etag(key)
            merged_rows = self._merge_master_rows(
                existing_rows=existing_rows,
                incoming_rows=rows,
                id_key=id_key,
            )
            try:
                return self._save_dataframe_key_with_condition(
                    merged_rows,
                    key,
                    if_match=etag if etag else None,
                    if_none_match="*" if etag is None else None,
                    reraise=True,
                )
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code")
                status_code = exc.response.get("ResponseMetadata", {}).get(
                    "HTTPStatusCode"
                )
                is_conflict = (
                    error_code
                    in {
                        "PreconditionFailed",
                        "ConditionalRequestConflict",
                    }
                    or status_code == 412
                )
                if not is_conflict:
                    logger.exception(
                        "Failed to save youtube master snapshot: key=%s", key
                    )
                    return None

                if attempt >= MAX_MASTER_SAVE_RETRIES - 1:
                    logger.error(
                        "Master snapshot save conflict exceeded retries: key=%s",
                        key,
                    )
                    return None

                sleep_seconds = MASTER_SAVE_BACKOFF_SECONDS * (
                    2**attempt
                ) + random.uniform(0.0, 0.05)
                logger.warning(
                    "Master snapshot save conflict (attempt %d/%d). "
                    "Retrying in %.2fs: key=%s",
                    attempt + 1,
                    MAX_MASTER_SAVE_RETRIES,
                    sleep_seconds,
                    key,
                )
                time.sleep(sleep_seconds)
        return None

    def _save_dataframe_key_with_condition(
        self,
        rows: list[dict[str, Any]],
        key: str,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
        reraise: bool = False,
    ) -> str | None:
        try:
            buffer = BytesIO()
            pd.DataFrame(rows).to_parquet(buffer, index=False, engine="pyarrow")
            buffer.seek(0)
            put_kwargs: dict[str, Any] = {}
            if if_match is not None:
                put_kwargs["IfMatch"] = if_match
            if if_none_match is not None:
                put_kwargs["IfNoneMatch"] = if_none_match
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
                **put_kwargs,
            )
        except Exception:
            logger.exception("Failed to save youtube parquet: key=%s", key)
            if reraise:
                raise
            return None
        return key
