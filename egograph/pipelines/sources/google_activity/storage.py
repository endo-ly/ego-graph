"""YouTubeデータのR2への保存を担当する。"""

import json
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError


def _serialize_datetime(obj: Any) -> str:
    """JSONシリアライズ用のdatetimeハンドラー。

    Args:
        obj: シリアライズ対象のオブジェクト

    Returns:
        ISO8601形式の文字列、またはその他の変換
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """パスを正規化して末尾に / を付ける。"""
    return path.rstrip("/") + "/"


class YouTubeStorage:
    """YouTubeデータの保存・永続化を管理するクラス。"""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        raw_path: str = "raw/",
        events_path: str = "events/",
        master_path: str = "master/",
    ):
        """Storageを初期化する。

        Args:
            endpoint_url: R2エンドポイント
            access_key_id: アクセスキーID
            secret_access_key: シークレットアクセスキー
            bucket_name: バケット名
            raw_path: 生データの保存先プレフィックス
            events_path: イベントデータの保存先プレフィックス
            master_path: マスターデータの保存先プレフィックス
        """
        self.bucket_name = bucket_name
        self.raw_path = _normalize_path(raw_path)
        self.events_path = _normalize_path(events_path)
        self.master_path = _normalize_path(master_path)

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )
        logger.info("YouTube Storage initialized for bucket: %s", bucket_name)

    def _upload_parquet(
        self, data: list[dict[str, Any]], key: str, description: str
    ) -> str | None:
        """データをParquet形式でS3にアップロードする共通処理。

        Args:
            data: 保存するデータ(辞書のリスト)
            key: S3オブジェクトキー
            description: ログ用の説明

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        if not data:
            logger.warning("No data provided for %s.", description)
            return None

        try:
            df = pd.DataFrame(data)
            buffer = BytesIO()
            df.to_parquet(buffer, index=False, engine="pyarrow")
            buffer.seek(0)

            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("Saved %s to %s", description, key)
            return key
        except ImportError:
            logger.exception("Pandas or PyArrow is required for Parquet saving")
            return None
        except Exception:
            logger.exception("Failed to save %s", description)
            return None

    def save_raw_json(
        self,
        data: list[dict[str, Any]] | dict[str, Any],
        prefix: str,
        account_id: str | None = None,
    ) -> str | None:
        """生データ(JSON)をR2に保存する。

        Path format:
        - With account_id: raw/{prefix}/YYYY/MM/DD/{timestamp}_{uuid}_{account_id}.json
        - Without account_id: raw/{prefix}/YYYY/MM/DD/{timestamp}_{uuid}.json

        Args:
            data: 保存するデータ(リストまたは辞書)
            prefix: データカテゴリー(例: "youtube/activity", "youtube/videos")
            account_id: アカウント識別子（例: "account1"）

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]

        date_path = now.strftime("%Y/%m/%d")

        if account_id:
            file_name = f"{timestamp_str}_{unique_id}_{account_id}.json"
        else:
            file_name = f"{timestamp_str}_{unique_id}.json"

        key = f"{self.raw_path}{prefix}/{date_path}/{file_name}"

        try:
            json_bytes = json.dumps(
                data, ensure_ascii=False, default=_serialize_datetime
            ).encode("utf-8")
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_bytes,
                ContentType="application/json",
            )
            logger.info("Saved raw JSON to %s", key)
            return key
        except (ClientError, TypeError):
            logger.exception("Failed to save raw JSON")
            return None

    def save_parquet(
        self,
        data: list[dict[str, Any]],
        year: int,
        month: int,
        prefix: str = "youtube/watch_history",
    ) -> str | None:
        """データをParquet形式で保存する。

        Path format: events/{prefix}/year={YYYY}/month={MM}/{uuid}.parquet

        Args:
            data: 保存するデータ(辞書のリスト)
            year: パーティション年
            month: パーティション月
            prefix: イベントカテゴリー

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        unique_id = str(uuid.uuid4())
        key = (
            f"{self.events_path}{prefix}/"
            f"year={year}/month={month:02d}/{unique_id}.parquet"
        )
        return self._upload_parquet(data, key, "Parquet")

    def save_master_parquet(
        self,
        data: list[dict[str, Any]],
        prefix: str,
        year: int | None = None,
        month: int | None = None,
    ) -> str | None:
        """マスターデータをParquet形式で保存する。

        Path format:
        - With partition: master/{prefix}/year={YYYY}/month={MM}/{uuid}.parquet
        - Without partition: master/{prefix}/{uuid}.parquet

        Args:
            data: 保存するデータ(辞書のリスト)
            prefix: マスターデータカテゴリー
            year: パーティション年
            month: パーティション月

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        unique_id = str(uuid.uuid4())

        if year is not None and month is not None:
            key = (
                f"{self.master_path}{prefix}/"
                f"year={year}/month={month:02d}/{unique_id}.parquet"
            )
        else:
            key = f"{self.master_path}{prefix}/{unique_id}.parquet"

        return self._upload_parquet(data, key, "master Parquet")

    def get_ingest_state(self, account_id: str) -> dict[str, Any] | None:
        """インジェスト状態(カーソル)を取得する。

        Args:
            account_id: アカウント識別子

        Returns:
            状態辞書 (存在しない場合はNone)
        """
        key = f"state/youtube_{account_id}_state.json"

        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info("No ingest state found for %s.", account_id)
                return None
            logger.exception("Failed to get ingest state")
            return None
        except Exception:
            logger.exception("Failed to read ingest state")
            return None

    def save_ingest_state(self, state: dict[str, Any], account_id: str) -> None:
        """インジェスト状態(カーソル)を保存する。

        Args:
            state: 保存する状態辞書
            account_id: アカウント識別子
        """
        key = f"state/youtube_{account_id}_state.json"

        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(state),
                ContentType="application/json",
            )
            logger.info("Saved ingest state for %s to %s", account_id, key)
        except Exception:
            logger.exception("Failed to save ingest state")
