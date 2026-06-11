"""Google Health API v4 クライアント。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from requests import Response

from pipelines.sources.google_health.models import ConnectionStatus, OAuthToken
from pipelines.sources.google_health.repository import GoogleHealthRepository
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
    ) -> None:
        self._repository = repository
        self._token_cipher = token_cipher
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_attempts = max_attempts

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
            status = (
                ConnectionStatus.REVOKED
                if response.status_code in (400, 401)
                else ConnectionStatus.ERROR
            )
            self._repository.update_connection_status(
                connection_id,
                status,
                "access token refresh failed",
            )
            raise GoogleHealthAuthenticationError("google_health_token_refresh_failed")
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
                    f"google_health_request_failed: status={response.status_code}"
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
