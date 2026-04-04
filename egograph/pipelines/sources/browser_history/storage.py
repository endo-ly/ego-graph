"""Browser history storage helpers."""

import json
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote

import boto3
import pandas as pd
from botocore.exceptions import ClientError

from pipelines.sources.common.compaction import (
    COMPACTED_ROOT,
    build_compacted_key,
    compact_records,
    dataframe_to_parquet_bytes,
    read_parquet_records_from_prefix,
)

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    return path.rstrip("/") + "/"


def _key_part(value: str) -> str:
    return quote(value, safe="")


class BrowserHistoryStorage:
    """Browser history の raw/events/state 保存を扱う。"""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        raw_path: str = "raw/",
        events_path: str = "events/",
        master_path: str = "master/",
        state_path: str = "state/",
    ):
        self.bucket_name = bucket_name
        self.raw_path = _normalize_path(raw_path)
        self.events_path = _normalize_path(events_path)
        self.master_path = _normalize_path(master_path)
        self.state_path = _normalize_path(state_path)
        self.compacted_path = COMPACTED_ROOT
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def build_state_key(self, source_device: str, browser: str, profile: str) -> str:
        """state JSON キーを返す。"""
        return (
            f"{self.state_path}browser_history/"
            f"{_key_part(source_device)}/{_key_part(browser)}/{_key_part(profile)}.json"
        )

    def save_raw_json(
        self,
        payload: dict[str, Any],
        *,
        browser: str,
        now: datetime | None = None,
    ) -> str | None:
        """raw payload を保存する。"""
        current = now or datetime.now(timezone.utc)
        timestamp_str = current.strftime("%Y%m%d_%H%M%S")
        date_path = current.strftime("%Y/%m/%d")
        key = (
            f"{self.raw_path}browser_history/{browser}/{date_path}/"
            f"{timestamp_str}_{str(uuid.uuid4())[:8]}.json"
        )
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
            )
        except ClientError:
            logger.exception("Failed to save browser history raw JSON")
            return None
        return key

    def save_parquet(
        self,
        rows: list[dict[str, Any]],
        *,
        year: int,
        month: int,
        prefix: str = "browser_history/page_views",
    ) -> str | None:
        """events parquet を保存する。"""
        if not rows:
            return None
        key = (
            f"{self.events_path}{prefix}/year={year}/month={month:02d}/"
            f"{uuid.uuid4()}.parquet"
        )
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
            logger.exception("Failed to save browser history parquet")
            return None
        return key

    def get_state(
        self,
        *,
        source_device: str,
        browser: str,
        profile: str,
    ) -> dict[str, Any] | None:
        """最新 state JSON を取得する。"""
        key = self.build_state_key(source_device, browser, profile)
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.exception("Failed to get browser history state")
            return None
        except Exception:
            logger.exception("Failed to parse browser history state")
            return None

    def save_state(
        self,
        state: dict[str, Any],
        *,
        source_device: str,
        browser: str,
        profile: str,
    ) -> None:
        """最新 state JSON を保存する。"""
        key = self.build_state_key(source_device, browser, profile)
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=json.dumps(state).encode("utf-8"),
            ContentType="application/json",
        )

    def compact_month(
        self,
        *,
        year: int,
        month: int,
        dataset_path: str = "browser_history/page_views",
        dedupe_key: str = "page_view_id",
        sort_by: str | None = "ingested_at_utc",
    ) -> str | None:
        """指定月の browser history events を compact する。"""
        source_prefix = (
            f"{self.events_path}{dataset_path}/year={year}/month={month:02d}/"
        )
        records = read_parquet_records_from_prefix(
            self.s3,
            self.bucket_name,
            source_prefix,
        )
        if not records:
            logger.info("No parquet records found for compaction: %s", source_prefix)
            return None

        compacted_df = compact_records(
            records,
            dedupe_key=dedupe_key,
            sort_by=sort_by,
        )
        key = build_compacted_key(
            self.compacted_path,
            data_domain="events",
            dataset_path=dataset_path,
            year=year,
            month=month,
        )
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=dataframe_to_parquet_bytes(compacted_df),
                ContentType="application/octet-stream",
            )
        except Exception:
            logger.exception(
                "Failed to save compacted browser history parquet: "
                "dataset=%s year=%d month=%02d key=%s",
                dataset_path,
                year,
                month,
                key,
            )
            raise
        logger.info("Saved compacted browser history parquet to %s", key)
        return key
