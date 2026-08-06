"""Google Health API v4 クライアント。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from requests import Response

from pipelines.sources.google_health.models import ConnectionStatus, OAuthToken
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.timezone import local_date_start_rfc3339
from pipelines.sources.google_health.token_cipher import TokenCipher

logger = logging.getLogger(__name__)

API_BASE_URL = "https://health.googleapis.com/v4"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleHealthAPIError(Exception):
    """Google Health API error の基底型。"""


class GoogleHealthAuthenticationError(GoogleHealthAPIError):
    """token が失効または revoke されている。"""


class GoogleHealthRateLimitError(GoogleHealthAPIError):
    """API rate limit に到達した。"""


class GoogleHealthServerError(GoogleHealthAPIError):
    """Google Health API の一時的な server error。"""


class GoogleHealthNetworkError(GoogleHealthAPIError):
    """Google Health API への network error。"""


class GoogleHealthClientError(GoogleHealthAPIError):
    """retry 不能な 4xx error。"""


_OAUTH_ERROR_SUMMARY_MAX_LENGTH = 500
_GOOGLE_ERROR_SUMMARY_MAX_LENGTH = 1_000
_GOOGLE_ERROR_MESSAGE_MAX_LENGTH = 500

# APIのエラーメッセージが、万一リクエスト由来の認証情報を反射した場合に備えて
# 例外メッセージ・last_error_messageへ保存する前に値を伏せる。
_GOOGLE_ERROR_SECRET_PATTERN = re.compile(
    r"(?i)[\"']?(?:authorization|bearer|access[_ -]?token|refresh[_ -]?token|"
    r"authorization[_ -]?code|client[_ -]?secret|token)[\"']?\s*[:=]\s*"
    r"[\"']?[^,\s}\"']+"
)

# OAuth refresh 失敗時に診断情報として使ってよい JSON field の許可リスト。
# 意図的に限定することで token / code / secret 等の秘密情報混入を防ぐ。
# error_description は OAuth 仕様上は許容 field だが、provider が自由に文章を
# 制御できるため token / code / client identifier 等が混入するリスクがある。
# そのため provider 由来の自由文は保存せず、構造化された固定値だけを記録する。

# OAuth 診断 field 値の永続化許可リスト。
# provider 由来の任意の文字列を無条件で信頼せず、field ごとに定義した明示的な
# 固定値集合に完全一致した場合だけ保存する。短い token や authorization code は
# OAuth 仕様の identifier 形状 (ASCII letter/digit と記号) を満たし得るため、
# 形状 check ではなく許可リストで制限する。ここに含まれない値はすべて保存
# 対象から除外する。keys がそのまま利用対象 field 名になる。
_OAUTH_ERROR_ALLOWED_VALUES: dict[str, frozenset[str]] = {
    "error": frozenset(
        {
            "invalid_request",
            "invalid_client",
            "invalid_grant",
            "unauthorized_client",
            "unsupported_grant_type",
            "invalid_scope",
        }
    ),
    "error_subtype": frozenset({"invalid_rapt"}),
}

# error 値と connection status の対応。一時障害(429/5xx)は含まない。
# 許可リスト内だがここに含まれない error (invalid_request 等) は未分類扱いで
# :attr:`ConnectionStatus.ERROR` になる。
_OAUTH_ERROR_CONNECTION_STATUS: dict[str, ConnectionStatus] = {
    "invalid_grant": ConnectionStatus.REVOKED,
    "invalid_client": ConnectionStatus.ERROR,
    "unauthorized_client": ConnectionStatus.ERROR,
}


def _safe_oauth_error_field(field: str, value: Any) -> str | None:
    """OAuth 診断 field 値が明示的許可リストに含まれる場合のみ返す。

    ``error`` / ``error_subtype`` は OAuth 仕様では短い identifier として
    定義されるが、短い token や authorization code も同じ identifier 形状に
    なり得る。そのため provider 由来の文字列を形状だけで受け入れず、
    :data:`_OAUTH_ERROR_ALLOWED_VALUES` の field ごとの許可リストと完全一致
    した場合だけ保存対象とする。許可リスト外の値は ``None`` を返し、
    保存対象から除外する。
    """
    allowed = _OAUTH_ERROR_ALLOWED_VALUES.get(field)
    if allowed is None or not isinstance(value, str):
        return None
    return value if value in allowed else None


def _oauth_error_summary(response: Response) -> str:
    """OAuth refresh 失敗時の安全な1行要約を返す。

    - JSON body の場合は ``error`` / ``error_subtype`` だけを使う
    - ただし値が field ごとの明示的許可リスト
      (:data:`_OAUTH_ERROR_ALLOWED_VALUES`) に完全一致しない場合はその
      field を要約から除外する。短い token や authorization code は
      identifier 形状になり得るため、形状ではなく許可リストで制限する
    - JSONでない場合は body を保存しない
    - access token / refresh token / authorization code / client secret /
      Authorization header / body 全体、および provider 由来の自由文
      (``error_description``) は絶対に含めない
    - この関数自体が例外を投げないよう、parse 失敗時は status のみ返す
    """
    status_code = response.status_code
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return f"oauth_refresh_failed: status={status_code}"[
            :_OAUTH_ERROR_SUMMARY_MAX_LENGTH
        ]
    parts: list[str] = [f"oauth_refresh_failed: status={status_code}"]
    for field in _OAUTH_ERROR_ALLOWED_VALUES:
        safe_value = _safe_oauth_error_field(field, payload.get(field))
        if safe_value is not None:
            parts.append(f"{field}={safe_value}")
    return " ".join(parts)[:_OAUTH_ERROR_SUMMARY_MAX_LENGTH]


def _refresh_failure_connection_status(
    response: Response,
) -> ConnectionStatus | None:
    """OAuth refresh 失敗時の connection status 遷移を返す。

    - ``invalid_grant`` -> :attr:`ConnectionStatus.REVOKED`
    - ``invalid_client`` / ``unauthorized_client`` -> :attr:`ConnectionStatus.ERROR`
    - 429 / 5xx -> ``None`` (一時障害なので connection status を更新しない)
    - JSONでない・未分類の 4xx -> :attr:`ConnectionStatus.ERROR`

    分類は ``error`` 値が ``error`` field の明示的許可リスト
    (:data:`_OAUTH_ERROR_ALLOWED_VALUES`) に完全一致し、かつ
    :data:`_OAUTH_ERROR_CONNECTION_STATUS` に含まれる場合のみ行う。
    許可リスト外の値、および許可リスト内だが status map にない値
    (``invalid_request`` 等) は未分類扱いとなり、4xx なら
    :attr:`ConnectionStatus.ERROR` になる。

    一時障害で誤って connection を inactive にすると、手動再認証ではなく
    DB状態修復が必要になるため ``None`` で更新を抑止する。
    """
    status_code = response.status_code
    if status_code == 429 or status_code >= 500:
        return None
    try:
        payload = response.json()
    except ValueError:
        return ConnectionStatus.ERROR
    if isinstance(payload, dict):
        error = _safe_oauth_error_field("error", payload.get("error"))
        if error is not None:
            return _OAUTH_ERROR_CONNECTION_STATUS.get(error, ConnectionStatus.ERROR)
    return ConnectionStatus.ERROR


def _safe_google_error_identifier(value: Any) -> str | None:
    """Google APIの構造化識別子を安全に要約する。"""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
        return None
    return value


def _safe_google_error_message(value: Any) -> str | None:
    """Google APIのエラーメッセージを短く、安全な一行へ変換する。"""
    if not isinstance(value, str):
        return None
    message = " ".join(value.split())
    if not message:
        return None
    message = _GOOGLE_ERROR_SECRET_PATTERN.sub("[REDACTED]", message)
    return message[:_GOOGLE_ERROR_MESSAGE_MAX_LENGTH]


def _google_error_summary(response: Response, *, method: str, url: str) -> str:
    """Google APIの4xx応答から安全な診断要約を作る。

    レスポンス本文全体やdetailsのmetadataは保存せず、Googleが返す構造化された
    status / reasonと、短く切り詰めたmessageだけを利用する。URLもquery stringを
    除いたpathだけを含める。
    """
    parts = [
        f"google_health_request_failed: status={response.status_code}",
        f"method={method.upper()}",
        f"path={urlsplit(url).path}",
    ]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        api_status = _safe_google_error_identifier(error.get("status"))
        if api_status is not None:
            parts.append(f"api_status={api_status}")

        reasons: list[str] = []
        for field in ("details", "errors"):
            entries = error.get(field)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                reason = _safe_google_error_identifier(entry.get("reason"))
                if reason is not None and reason not in reasons:
                    reasons.append(reason)
        if reasons:
            parts.append(f"reason={','.join(reasons[:3])}")

        message = _safe_google_error_message(error.get("message"))
        if message is not None:
            parts.append(f"message={message}")
    return " ".join(parts)[:_GOOGLE_ERROR_SUMMARY_MAX_LENGTH]


class GoogleHealthAPIClient:
    """token refresh と retry を備えた Google Health API client。"""

    def __init__(
        self,
        repository: GoogleHealthRepository,
        token_cipher: TokenCipher,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        timezone: ZoneInfo | None = None,
    ) -> None:
        self._repository = repository
        self._token_cipher = token_cipher
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._timezone = timezone or ZoneInfo("UTC")

    def list_data_points(
        self,
        connection_id: str,
        data_type: str,
        *,
        page_size: int = 1,
    ) -> dict[str, Any]:
        """指定 data type の data point を取得する。"""
        token = self._get_valid_token(connection_id)
        url = f"{API_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints"
        return self._request_json(
            "GET",
            url,
            connection_id=connection_id,
            token=token,
            params={"pageSize": page_size},
        )

    def reconcile_data_points(
        self,
        connection_id: str,
        data_type: str,
        *,
        filter_expression: str,
        page_size: int,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """指定期間のreconciled data pointを取得する。"""
        token = self._get_valid_token(connection_id)
        url = f"{API_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints:reconcile"
        params: dict[str, Any] = {
            "filter": filter_expression,
            "pageSize": page_size,
        }
        if page_token:
            params["pageToken"] = page_token
        return self._request_json(
            "GET",
            url,
            connection_id=connection_id,
            token=token,
            params=params,
        )

    def daily_rollup(
        self,
        connection_id: str,
        data_type: str,
        *,
        date_from: date,
        date_to: date,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """指定civil date範囲の日次rollupを取得する。"""
        token = self._get_valid_token(connection_id)
        url = f"{API_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        body: dict[str, Any] = {
            "range": {
                "start": _civil_midnight(date_from),
                "end": _civil_midnight(date_to),
            },
            "windowSizeDays": 1,
            "pageSize": 10_000,
        }
        if page_token:
            body["pageToken"] = page_token
        return self._request_json(
            "POST",
            url,
            connection_id=connection_id,
            token=token,
            json=body,
        )

    def rollup(
        self,
        connection_id: str,
        data_type: str,
        *,
        date_from: date,
        date_to: date,
        window_size_seconds: int,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """指定物理時間範囲を固定windowでrollupする。"""
        token = self._get_valid_token(connection_id)
        url = f"{API_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints:rollUp"
        body: dict[str, Any] = {
            "range": {
                "startTime": local_date_start_rfc3339(date_from, self._timezone),
                "endTime": local_date_start_rfc3339(date_to, self._timezone),
            },
            "windowSize": f"{window_size_seconds}s",
            "pageSize": 10_000,
        }
        if page_token:
            body["pageToken"] = page_token
        return self._request_json(
            "POST",
            url,
            connection_id=connection_id,
            token=token,
            json=body,
        )

    def _get_valid_token(self, connection_id: str) -> OAuthToken:
        encrypted = self._repository.get_encrypted_token(connection_id)
        connection = self._repository.get_connection()
        if (
            encrypted is None
            or connection is None
            or connection.connection_id != connection_id
        ):
            raise GoogleHealthAuthenticationError("google_health_connection_not_found")
        token = OAuthToken(
            access_token=self._token_cipher.decrypt(encrypted.access_token_encrypted),
            refresh_token=self._token_cipher.decrypt(encrypted.refresh_token_encrypted),
            expires_at=encrypted.expires_at,
            token_type=encrypted.token_type,
            scopes=connection.scopes,
        )
        if token.expires_at <= datetime.now(tz=UTC) + timedelta(seconds=30):
            return self._refresh_token(connection_id, token)
        return token

    def _refresh_token(
        self,
        connection_id: str,
        current_token: OAuthToken,
    ) -> OAuthToken:
        if not self._client_id or not self._client_secret:
            raise GoogleHealthAuthenticationError(
                "google_health_oauth_credentials_not_configured"
            )
        response = self._request_token_refresh(current_token.refresh_token)
        if response.status_code >= 400:
            error_summary = _oauth_error_summary(response)
            status = _refresh_failure_connection_status(response)
            if status is not None:
                self._repository.update_connection_status(
                    connection_id,
                    status,
                    error_summary,
                )
            raise GoogleHealthAuthenticationError(error_summary)
        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not access_token or not isinstance(expires_in, int):
            self._repository.update_connection_status(
                connection_id,
                ConnectionStatus.ERROR,
                "invalid refresh response",
            )
            raise GoogleHealthAuthenticationError(
                "invalid_google_health_refresh_response"
            )
        refreshed = OAuthToken(
            access_token=access_token,
            refresh_token=str(
                payload.get("refresh_token", current_token.refresh_token)
            ),
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=expires_in),
            token_type=str(payload.get("token_type", current_token.token_type)),
            scopes=current_token.scopes,
        )
        self._repository.update_token(
            connection_id,
            access_token_encrypted=self._token_cipher.encrypt(refreshed.access_token),
            refresh_token_encrypted=self._token_cipher.encrypt(refreshed.refresh_token),
            expires_at=refreshed.expires_at,
            token_type=refreshed.token_type,
        )
        return refreshed

    def _request_token_refresh(self, refresh_token: str) -> Response:
        """一時障害を retry して token refresh を実行する。"""
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=30,
                )
            except requests.RequestException:
                if attempt == self._max_attempts:
                    raise GoogleHealthNetworkError(
                        "google_health_token_refresh_network_error"
                    )
                self._sleep(2 ** (attempt - 1))
                continue
            if response.status_code not in (429,) and response.status_code < 500:
                return response
            if attempt == self._max_attempts:
                return response
            self._sleep(2 ** (attempt - 1))
        raise GoogleHealthNetworkError(  # pragma: no cover
            "google_health_token_refresh_failed"
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        connection_id: str,
        token: OAuthToken,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: GoogleHealthAPIError | None = None
        refreshed_after_unauthorized = False
        attempt = 1
        while attempt <= self._max_attempts:
            try:
                response = self._session.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {token.access_token}",
                        "Accept": "application/json",
                    },
                    params=params,
                    json=json,
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = GoogleHealthNetworkError("google_health_network_error")
                if attempt == self._max_attempts:
                    raise last_error from exc
                self._sleep(2 ** (attempt - 1))
                attempt += 1
                continue

            if response.status_code < 400:
                return response.json()
            if response.status_code == 401:
                if not refreshed_after_unauthorized:
                    token = self._refresh_token(connection_id, token)
                    refreshed_after_unauthorized = True
                    continue
                self._repository.update_connection_status(
                    connection_id,
                    ConnectionStatus.ERROR,
                    "access token rejected",
                )
                raise GoogleHealthAuthenticationError(
                    "google_health_access_token_rejected"
                )
            if response.status_code == 429:
                last_error = GoogleHealthRateLimitError(
                    "google_health_rate_limit_exceeded"
                )
            elif response.status_code >= 500:
                last_error = GoogleHealthServerError("google_health_server_error")
            else:
                raise GoogleHealthClientError(
                    _google_error_summary(response, method=method, url=url)
                )

            if attempt < self._max_attempts:
                logger.warning(
                    "Google Health request retrying: status=%d attempt=%d",
                    response.status_code,
                    attempt,
                )
                self._sleep(2 ** (attempt - 1))
            attempt += 1
        if last_error is None:  # pragma: no cover
            raise GoogleHealthAPIError("google_health_request_failed")
        raise last_error


def _civil_midnight(value: date) -> dict[str, Any]:
    """Google Health CivilDateTimeの日付境界を組み立てる。"""
    return {
        "date": {
            "year": value.year,
            "month": value.month,
            "day": value.day,
        },
        "time": {},
    }
