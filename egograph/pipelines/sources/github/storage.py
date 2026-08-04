"""GitHubデータのR2への保存を担当する。"""

import json
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from dataset_catalog import DatasetDefinition, datasets
from dataset_catalog.validation import (
    validate_parquet_bytes,
    validate_required_columns,
)

from pipelines.sources.common.compaction import (
    COMPACTED_ROOT,
    build_compacted_key,
    compact_records,
    dataframe_to_parquet_bytes,
    read_parquet_records_from_prefix,
)

logger = logging.getLogger(__name__)

DEFAULT_STATE_KEY = "state/github_worklog_ingest_state.json"


class StorageConsistencyError(RuntimeError):
    """既存データや状態ファイルの整合性が保てない場合の例外。"""


def _normalize_path(path: str) -> str:
    """パスを正規化して末尾に / を付ける。"""
    return path.rstrip("/") + "/"


class GitHubWorklogStorage:
    """GitHubデータの保存・永続化を管理するクラス。"""

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
        self.compacted_path = COMPACTED_ROOT

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )
        logger.info("Storage initialized for bucket: %s", bucket_name)

    def _upload_parquet(
        self,
        data: list[dict[str, Any]],
        key: str,
        description: str,
        dataset: DatasetDefinition,
    ) -> str | None:
        """データをParquet形式でS3にアップロードする共通処理。

        アップロード前に dataset の schema 契約（必須カラム・型）を検証し、
        違反があれば保存失敗（None）として扱う。

        Args:
            data: 保存するデータ(辞書のリスト)
            key: S3オブジェクトキー
            description: ログ用の説明
            dataset: schema 契約の基準となる DatasetDefinition

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        if not data:
            logger.warning("No data provided for %s.", description)
            return None

        try:
            df = pd.DataFrame(data)
            validate_required_columns(dataset, df.columns)
            buffer = BytesIO()
            df.to_parquet(buffer, index=False, engine="pyarrow")
            validate_parquet_bytes(dataset, buffer.getvalue())
            buffer.seek(0)

            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("Saved %s to %s", description, key)
            return key
        except ValueError:
            logger.exception("Schema validation failed for %s", description)
            return None
        except ImportError:
            logger.exception("Pandas or PyArrow is required for Parquet saving")
            return None
        except Exception:
            logger.exception("Failed to save %s", description)
            return None

    def _load_existing_commit_ids(self, year: int, month: int) -> set[str]:
        """既存Commit IDを読み込む（重複排除用）。

        Args:
            year: 対象年
            month: 対象月

        Returns:
            既存Commit IDのセット
        """
        prefix = f"{self.events_path}github/commits/year={year}/month={month:02d}/"
        existing_ids: set[str] = set()

        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    try:
                        obj_response = self.s3.get_object(
                            Bucket=self.bucket_name, Key=obj["Key"]
                        )
                        df = pd.read_parquet(BytesIO(obj_response["Body"].read()))
                        if "commit_event_id" in df.columns:
                            existing_ids.update(df["commit_event_id"].tolist())
                    except Exception as exc:
                        raise StorageConsistencyError(
                            f"Failed to read existing commits parquet: {obj['Key']}"
                        ) from exc

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    "No existing commits found for year=%s month=%s",
                    year,
                    month,
                )
            else:
                raise StorageConsistencyError(
                    "Failed to list existing commits parquet files"
                ) from e
        except StorageConsistencyError:
            raise
        except Exception as exc:
            raise StorageConsistencyError(
                "Unexpected error loading existing commit IDs"
            ) from exc

        return existing_ids

    def _load_existing_pr_event_ids(self, year: int, month: int) -> set[str]:
        prefix = (
            f"{self.events_path}github/pull_requests/year={year}/month={month:02d}/"
        )
        existing_ids: set[str] = set()

        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    try:
                        obj_response = self.s3.get_object(
                            Bucket=self.bucket_name,
                            Key=obj["Key"],
                        )
                        df = pd.read_parquet(BytesIO(obj_response["Body"].read()))
                        if "pr_event_id" in df.columns:
                            existing_ids.update(df["pr_event_id"].tolist())
                    except Exception as exc:
                        raise StorageConsistencyError(
                            "Failed to read existing pull request parquet: "
                            f"{obj['Key']}"
                        ) from exc

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info(
                    "No existing pull request events found for year=%s month=%s",
                    year,
                    month,
                )
            else:
                raise StorageConsistencyError(
                    "Failed to list existing pull request parquet files"
                ) from e
        except StorageConsistencyError:
            raise
        except Exception as exc:
            raise StorageConsistencyError(
                "Unexpected error loading existing pull request event IDs"
            ) from exc

        return existing_ids

    def save_raw_prs(
        self, data: list[dict[str, Any]], owner: str, repo: str
    ) -> str | None:
        """PR生データ(JSON)をR2に保存する。

        Path: raw/github/pull_requests/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json

        Args:
            data: 保存するPRデータ(辞書のリスト)
            owner: リポジトリオーナー
            repo: リポジトリ名

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        if not data:
            logger.warning("No PR data provided to save.")
            return None

        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]

        date_path = now.strftime("%Y/%m/%d")
        file_name = f"{timestamp_str}_{unique_id}.json"
        key = f"{self.raw_path}github/pull_requests/{date_path}/{file_name}"

        try:
            json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_bytes,
                ContentType="application/json",
            )
            logger.info("Saved raw PRs to %s", key)
            return key
        except ClientError:
            logger.exception("Failed to save raw PRs")
            return None

    def save_raw_commits(
        self, data: list[dict[str, Any]], owner: str, repo: str
    ) -> str | None:
        """Commit生データ(JSON)をR2に保存する。

        Path: raw/github/commits/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json

        Args:
            data: 保存するCommitデータ(辞書のリスト)
            owner: リポジトリオーナー
            repo: リポジトリ名

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        if not data:
            logger.warning("No commit data provided to save.")
            return None

        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]

        date_path = now.strftime("%Y/%m/%d")
        file_name = f"{timestamp_str}_{unique_id}.json"
        key = f"{self.raw_path}github/commits/{date_path}/{file_name}"

        try:
            json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_bytes,
                ContentType="application/json",
            )
            logger.info("Saved raw commits to %s", key)
            return key
        except ClientError:
            logger.exception("Failed to save raw commits")
            return None

    def save_commits_parquet(
        self,
        data: list[dict[str, Any]],
        year: int,
        month: int,
    ) -> str | None:
        """CommitイベントをParquet形式で保存する。

        Path: events/github/commits/year={YYYY}/month={MM}/{uuid}.parquet

        重複排除: _load_existing_commit_ids() で既存IDを取得し、新規IDのみ保存。

        Args:
            data: 保存するCommitイベントデータ(辞書のリスト)
            year: パーティション年
            month: パーティション月

        Returns:
            保存されたオブジェクトのキー (失敗時または新規データなし時はNone)
        """
        if not data:
            logger.warning("No commit data provided to save as Parquet.")
            return None

        # 既存Commit IDを取得して重複排除
        existing_ids = self._load_existing_commit_ids(year, month)
        new_commits = [c for c in data if c.get("commit_event_id") not in existing_ids]

        if not new_commits:
            logger.info("No new commits to save (all duplicates).")
            return None

        unique_id = str(uuid.uuid4())
        key = (
            f"{self.events_path}github/commits/"
            f"year={year}/month={month:02d}/{unique_id}.parquet"
        )

        return self._upload_parquet(
            new_commits, key, "commits Parquet", datasets.GITHUB_COMMITS
        )

    def save_commits_parquet_with_stats(
        self,
        data: list[dict[str, Any]],
        year: int,
        month: int,
    ) -> dict[str, int]:
        """Commitイベントを保存し、新規/重複/失敗件数を返す。"""
        if not data:
            return {"fetched": 0, "new": 0, "duplicates": 0, "failed": 0}

        existing_ids = self._load_existing_commit_ids(year, month)
        new_commits = [c for c in data if c.get("commit_event_id") not in existing_ids]
        duplicate_count = len(data) - len(new_commits)

        if not new_commits:
            logger.info("No new commits to save (all duplicates).")
            return {
                "fetched": len(data),
                "new": 0,
                "duplicates": duplicate_count,
                "failed": 0,
            }

        unique_id = str(uuid.uuid4())
        key = (
            f"{self.events_path}github/commits/"
            f"year={year}/month={month:02d}/{unique_id}.parquet"
        )
        saved = self._upload_parquet(
            new_commits, key, "commits Parquet", datasets.GITHUB_COMMITS
        )
        if saved is None:
            return {
                "fetched": len(data),
                "new": 0,
                "duplicates": duplicate_count,
                "failed": len(new_commits),
            }

        return {
            "fetched": len(data),
            "new": len(new_commits),
            "duplicates": duplicate_count,
            "failed": 0,
        }

    def save_pr_events_parquet_with_stats(
        self,
        data: list[dict[str, Any]],
        year: int,
        month: int,
    ) -> dict[str, int]:
        if not data:
            return {"fetched": 0, "new": 0, "duplicates": 0, "failed": 0}

        existing_ids = self._load_existing_pr_event_ids(year, month)
        new_events = [e for e in data if e.get("pr_event_id") not in existing_ids]
        duplicate_count = len(data) - len(new_events)

        if not new_events:
            logger.info("No new pull request events to save (all duplicates).")
            return {
                "fetched": len(data),
                "new": 0,
                "duplicates": duplicate_count,
                "failed": 0,
            }

        unique_id = str(uuid.uuid4())
        key = (
            f"{self.events_path}github/pull_requests/"
            f"year={year}/month={month:02d}/{unique_id}.parquet"
        )
        saved = self._upload_parquet(
            new_events,
            key,
            "pull request events Parquet",
            datasets.GITHUB_PULL_REQUESTS,
        )
        if saved is None:
            return {
                "fetched": len(data),
                "new": 0,
                "duplicates": duplicate_count,
                "failed": len(new_events),
            }

        return {
            "fetched": len(data),
            "new": len(new_events),
            "duplicates": duplicate_count,
            "failed": 0,
        }

    def save_repo_master(
        self,
        data: list[dict[str, Any]],
        owner: str,
        repo: str,
    ) -> str | None:
        """Repository MasterをParquet形式で保存する。

        Path: master/github/repositories/{owner}/{repo}.parquet

        Args:
            data: 保存するRepository Masterデータ(辞書のリスト)
            owner: リポジトリオーナー
            repo: リポジトリ名

        Returns:
            保存されたオブジェクトのキー (失敗時はNone)
        """
        if not data:
            logger.warning("No repository master data provided to save.")
            return None

        key = f"{self.master_path}github/repositories/{owner}/{repo}.parquet"

        return self._upload_parquet(
            data, key, "repository master Parquet", datasets.GITHUB_REPOSITORIES
        )

    def get_ingest_state(self, key: str = DEFAULT_STATE_KEY) -> dict[str, Any] | None:
        """インジェスト状態を取得する。

        Path: state/github_worklog_ingest_state.json

        Returns:
            状態辞書 (存在しない場合はNone)
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info("No ingest state found.")
                return None
            raise StorageConsistencyError("Failed to get ingest state") from e
        except Exception as exc:
            raise StorageConsistencyError("Failed to read ingest state") from exc

    def save_ingest_state(
        self, state: dict[str, Any], key: str = DEFAULT_STATE_KEY
    ) -> None:
        """インジェスト状態を保存する。

        Path: state/github_worklog_ingest_state.json

        Args:
            state: 保存する状態辞書
        """
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(state),
                ContentType="application/json",
            )
            logger.info("Saved ingest state to %s", key)
        except Exception as exc:
            raise StorageConsistencyError("Failed to save ingest state") from exc

    def compact_month(
        self,
        dataset: DatasetDefinition,
        year: int,
        month: int,
    ) -> str | None:
        """指定月のGitHubイベントParquetをcompact版として保存する。"""
        source_prefix = dataset.source_partition_prefix(
            self.events_path,
            year=year,
            month=month,
        )
        records = read_parquet_records_from_prefix(
            self.s3,
            self.bucket_name,
            source_prefix,
            dataset=dataset,
        )
        if not records:
            logger.info("No parquet records found for compaction: %s", source_prefix)
            return None

        compacted_df = compact_records(
            records,
            dedupe_key=dataset.required_dedupe_key(),
            sort_by=dataset.sort_key,
            dataset=dataset,
        )
        key = build_compacted_key(
            self.compacted_path,
            dataset,
            year=year,
            month=month,
        )
        try:
            validate_required_columns(dataset, compacted_df.columns)
            body = dataframe_to_parquet_bytes(compacted_df)
            validate_parquet_bytes(dataset, body)
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType="application/octet-stream",
            )
        except ClientError:
            logger.exception("Failed to save compacted parquet to %s", key)
            return None
        logger.info("Saved compacted parquet to %s", key)
        return key
