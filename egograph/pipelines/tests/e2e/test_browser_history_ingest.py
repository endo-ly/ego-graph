"""service orchestration の E2E 結合テスト。

`tests/ingest/integration/**` は source pipeline + storage の統合を検証する。
この階層では FastAPI ingest API + Dispatcher + Executor + fake S3 をまとめて通し、
service オーケストレーション境界の結合を検証する。
"""

import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.testclient import TestClient
from pydantic import SecretStr

from pipelines.app import create_app
from pipelines.config import PipelinesConfig


class _MemoryS3RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        return

    def do_PUT(self):
        bucket, key = self._bucket_key()
        length = int(self.headers.get("Content-Length", "0"))
        self.server.objects[(bucket, key)] = self.rfile.read(length)
        self._send(200, b"<PutObjectResult></PutObjectResult>")

    def do_GET(self):
        parsed = urlparse(self.path)
        bucket, key = self._bucket_key()
        query = parse_qs(parsed.query)
        if query.get("list-type") == ["2"]:
            prefix = query.get("prefix", [""])[0]
            keys = [
                object_key
                for object_bucket, object_key in sorted(self.server.objects)
                if object_bucket == bucket and object_key.startswith(prefix)
            ]
            contents = "".join(
                f"<Contents><Key>{object_key}</Key><Size>"
                f"{len(self.server.objects[(bucket, object_key)])}"
                "</Size></Contents>"
                for object_key in keys
            )
            response_body = (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>"
                f"<Name>{bucket}</Name>"
                f"<Prefix>{prefix}</Prefix>"
                f"<KeyCount>{len(keys)}</KeyCount>"
                "<MaxKeys>1000</MaxKeys>"
                "<IsTruncated>false</IsTruncated>"
                f"{contents}"
                "</ListBucketResult>"
            ).encode("utf-8")
            self._send(200, response_body)
            return

        object_body = self.server.objects.get((bucket, key))
        if object_body is None:
            self._send(404, b"<Error><Code>NoSuchKey</Code></Error>")
            return
        self._send(200, object_body, content_type="application/octet-stream")

    def _bucket_key(self) -> tuple[str, str]:
        path = self.path.split("?", 1)[0]
        parts = path.split("/", 2)
        bucket = unquote(parts[1]) if len(parts) > 1 else ""
        key = unquote(parts[2]) if len(parts) > 2 else ""
        return bucket, key

    def _send(
        self,
        status_code: int,
        body: bytes,
        *,
        content_type: str = "application/xml",
    ) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class _MemoryS3Server:
    def __init__(self):
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _MemoryS3RequestHandler,
        )
        self._server.objects = {}
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    @property
    def objects(self) -> dict[tuple[str, str], bytes]:
        return self._server.objects

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)


def test_browser_history_ingest_api_executes_compaction_pipeline_end_to_end(
    tmp_path,
    monkeypatch,
):
    """Browser History POST から compacted parquet 保存まで通しで実行できる。"""
    # Arrange
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    config = PipelinesConfig(
        database_path=tmp_path / "state.sqlite3",
        logs_root=tmp_path / "logs",
        dispatcher_poll_seconds=0.01,
        lock_heartbeat_seconds=1,
        api_key=SecretStr("test-api-key"),
    )
    payload = {
        "sync_id": "11111111-1111-4111-8111-111111111111",
        "source_device": "laptop-main",
        "browser": "chrome",
        "profile": "Default",
        "synced_at": f"{date_str}T{time_str}.000Z",
        "items": [
            {
                "url": "https://example.com/a",
                "visit_time": f"{date_str}T{time_str}.000Z",
                "title": "A",
                "visit_id": "visit-1",
                "transition": "link",
            }
        ],
    }

    with _MemoryS3Server() as memory_s3:
        monkeypatch.setenv("R2_ENDPOINT_URL", memory_s3.endpoint_url)
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
        app = create_app(config)

        # Act & Assert
        with TestClient(app) as client:
            ingest_response = client.post(
                "/v1/ingest/browser-history",
                headers={"X-API-Key": "test-api-key"},
                json=payload,
            )
            assert ingest_response.status_code == 202
            body = ingest_response.json()
            assert body["accepted"] == 1
            assert body["raw_saved"] is True
            assert body["events_saved"] is True
            assert body["youtube_run_id"]

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                run_response = client.get(
                    f"/v1/runs/{body['youtube_run_id']}",
                    headers={"X-API-Key": "test-api-key"},
                )
                assert run_response.status_code == 200
                run_detail = run_response.json()
                if run_detail["run"]["status"] == "succeeded":
                    assert run_detail["steps"][0]["status"] == "succeeded"
                    break
                if run_detail["run"]["status"] == "failed":
                    raise AssertionError(run_detail["run"]["last_error_message"])
                time.sleep(0.05)
            else:
                raise AssertionError("youtube ingest run did not succeed")

        object_keys = [key for _, key in memory_s3.objects]
        year_month_day = now.strftime("%Y/%m/%d")
        assert any(
            key.startswith(f"raw/browser_history/chrome/{year_month_day}/")
            for key in object_keys
        )
        assert any(
            key.startswith(
                f"compacted/events/browser_history/page_views/"
                f"year={now.year}/month={now.month:02d}/data.parquet"
            )
            for key in object_keys
        )
        assert "state/browser_history/laptop-main/chrome/Default.json" in object_keys
        assert (
            f"compacted/events/browser_history/page_views/year={now.year}/month={now.month:02d}/data.parquet"
            in object_keys
        )
