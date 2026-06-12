"""Google Health OAuth 2.0 認証。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from pipelines.sources.google_health.models import (
    GoogleHealthConnection,
    OAuthToken,
)
from pipelines.sources.google_health.repository import GoogleHealthRepository
from pipelines.sources.google_health.token_cipher import TokenCipher

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
)


class GoogleHealthAuth:
    """Google OAuth authorization code flow を管理する。"""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        repository: GoogleHealthRepository,
        token_cipher: TokenCipher,
        scopes: tuple[str, ...] = DEFAULT_SCOPES,
        session: requests.Session | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._repository = repository
        self._token_cipher = token_cipher
        self._scopes = scopes
        self._session = session or requests.Session()

    def start_authorization(self) -> str:
        """OAuth 認可 URL を生成し、CSRF state を保存する。"""
        state = secrets.token_urlsafe(32)
        self._repository.save_oauth_state(
            state,
            datetime.now(tz=UTC) + timedelta(minutes=10),
        )
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._scopes),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{AUTHORIZATION_URL}?{query}"

    def complete_authorization(
        self,
        *,
        code: str,
        state: str,
    ) -> GoogleHealthConnection:
        """authorization code を token に交換して暗号化保存する。"""
        if not self._repository.consume_oauth_state(state):
            raise ValueError("invalid_oauth_state: state is expired or already used")
        response = self._session.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self._redirect_uri,
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise ValueError(
                f"google_health_token_exchange_failed: status={response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(
                "google_health_token_exchange_failed: invalid response body"
            ) from exc
        token = self._parse_token_response(payload)
        return self._repository.save_connection(
            token=token,
            access_token_encrypted=self._token_cipher.encrypt(token.access_token),
            refresh_token_encrypted=self._token_cipher.encrypt(token.refresh_token),
        )

    def _parse_token_response(self, payload: dict[str, Any]) -> OAuthToken:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        if not access_token or not refresh_token or not isinstance(expires_in, int):
            raise ValueError(
                "invalid_google_health_token_response: "
                "access_token, refresh_token and expires_in are required"
            )
        scopes = tuple(str(payload.get("scope", "")).split()) or self._scopes
        return OAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=expires_in),
            token_type=str(payload.get("token_type", "Bearer")),
            scopes=scopes,
        )
