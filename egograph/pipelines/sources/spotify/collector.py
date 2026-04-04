"""Spotifyデータコレクター。

Spotify Web APIに接続し、以下を収集します:
- 最近再生したトラック(視聴履歴)
- ユーザーのプレイリストとトラック一覧
"""

import logging
from collections.abc import Callable
from typing import Any

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import (
    MAX_RETRIES,
    PLAYLISTS_LIMIT,
    RECENTLY_PLAYED_LIMIT,
    RETRY_BACKOFF_FACTOR,
)

logger = logging.getLogger(__name__)

# 共通リトライデコレータ
spotify_retry = retry(
    retry=retry_if_exception_type(
        (spotipy.SpotifyException, requests.exceptions.RequestException)
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=RETRY_BACKOFF_FACTOR, min=2, max=10),
)


def _paginate(
    fetch_fn: Callable[..., dict[str, Any]],
    limit: int,
    *,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """ページネーションを使用してすべてのアイテムを取得する汎用ヘルパー。

    Args:
        fetch_fn: offset と limit を受け取り、API レスポンス辞書を返す関数
        limit: 1ページあたりの最大アイテム数
        max_items: 取得する最大アイテム数 (None の場合は無制限)

    Returns:
        すべてのアイテムのリスト
    """
    items: list[dict[str, Any]] = []
    offset = 0

    while True:
        results = fetch_fn(offset=offset, limit=limit)
        if not isinstance(results, dict):
            logger.warning(
                "Pagination fetch returned non-dict result; stopping. type=%s",
                type(results).__name__,
            )
            break
        page_items = results.get("items", [])

        if not page_items:
            break

        if max_items is not None:
            remaining = max_items - len(items)
            if remaining <= 0:
                break
            items.extend(page_items[:remaining])
            if len(items) >= max_items:
                break
        else:
            items.extend(page_items)
        offset += len(page_items)

        if not results.get("next"):
            break

    if max_items is not None:
        return items[:max_items]
    return items


class SpotifyCollector:
    """Spotify APIデータコレクター。

    Spotify Web APIからのOAuth認証とデータ収集を処理します。
    レート制限や一時的なエラーを処理するためのリトライロジックを実装しています。
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        redirect_uri: str = "http://127.0.0.1:8888/callback",
        scope: str = (
            "user-read-recently-played playlist-read-private "
            "playlist-read-collaborative"
        ),
    ):
        """Spotifyコレクターを初期化します。

        Args:
            client_id: SpotifyアプリのクライアントID
            client_secret: Spotifyアプリのクライアントシークレット
            refresh_token: OAuthリフレッシュトークン
            redirect_uri: OAuthリダイレクトURI
            scope: OAuthスコープ(スペース区切り)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token

        self.auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            open_browser=False,
        )

        self.auth_manager.refresh_access_token(refresh_token)
        logger.info("Successfully refreshed Spotify access token")

        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
        logger.info("Spotify collector initialized")

    @spotify_retry
    def get_recently_played(
        self, limit: int = RECENTLY_PLAYED_LIMIT, after: int | None = None
    ) -> list[dict[str, Any]]:
        """最近再生したトラックを取得します。

        Args:
            limit: 取得するトラックの最大数(最大50)
            after: この時刻以降の再生履歴のみ取得するUnixミリ秒タイムスタンプ。
                   Noneの場合は全件取得(デフォルト)。

        Returns:
            メタデータを含むトラック辞書のリスト

        Raises:
            spotipy.SpotifyException: リトライ後にAPI呼び出しが失敗した場合

        Note:
            afterパラメータを使用すると、指定したタイムスタンプより後の
            再生履歴のみが返されます(タイムスタンプ自体は含まれません)。
        """
        if after is not None:
            logger.info(
                "Fetching recently played tracks incrementally (limit=%d, after=%d ms)",
                limit,
                after,
            )
        else:
            logger.info("Fetching recently played tracks (limit=%d)", limit)

        api_params: dict[str, Any] = {"limit": limit}
        if after is not None:
            api_params["after"] = after

        results = self.sp.current_user_recently_played(**api_params)
        items = results.get("items", [])

        if after is not None and len(items) == 0:
            logger.info("No new tracks found since last fetch. Database is up to date.")
        else:
            logger.info("Successfully fetched %d recently played tracks", len(items))

        return items

    @spotify_retry
    def get_user_playlists(self, limit: int = PLAYLISTS_LIMIT) -> list[dict[str, Any]]:
        """ユーザーのプレイリストを取得します。

        Args:
            limit: 1ページあたりに取得するプレイリストの最大数

        Returns:
            メタデータを含むプレイリスト辞書のリスト

        Raises:
            spotipy.SpotifyException: リトライ後にAPI呼び出しが失敗した場合
        """
        logger.info("Fetching user playlists (limit=%d)", limit)

        playlists = _paginate(
            lambda offset, limit: self.sp.current_user_playlists(
                limit=limit, offset=offset
            ),
            limit,
        )

        logger.info("Successfully fetched %d playlists", len(playlists))
        return playlists

    @spotify_retry
    def get_playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """プレイリストから全トラックを取得します。

        Args:
            playlist_id: SpotifyプレイリストID

        Returns:
            メタデータを含むトラック辞書のリスト

        Raises:
            spotipy.SpotifyException: リトライ後にAPI呼び出しが失敗した場合
        """
        logger.debug("Fetching tracks for playlist %s", playlist_id)
        limit = 100

        tracks = _paginate(
            lambda offset, limit: self.sp.playlist_tracks(
                playlist_id, limit=limit, offset=offset
            ),
            limit,
        )

        logger.debug("Fetched %d tracks from playlist %s", len(tracks), playlist_id)
        return tracks

    def get_playlists_with_tracks(
        self, limit: int = PLAYLISTS_LIMIT
    ) -> list[dict[str, Any]]:
        """ユーザーのプレイリストと全トラックを取得します。

        これは、完全なプレイリストデータを取得するために
        get_user_playlists() と get_playlist_tracks() を組み合わせた便利なメソッドです。

        Args:
            limit: 取得するプレイリストの最大数

        Returns:
            'tracks' フィールドが入力されたプレイリスト辞書のリスト

        Raises:
            spotipy.SpotifyException: API呼び出しが失敗した場合
        """
        playlists = self.get_user_playlists(limit=limit)
        enriched_playlists = []

        for playlist in playlists:
            playlist_id = playlist.get("id")
            if not playlist_id:
                logger.warning("Skipping playlist without ID: %s", playlist.get("name"))
                continue

            try:
                tracks = self.get_playlist_tracks(playlist_id)
                playlist["full_tracks"] = tracks
            except spotipy.SpotifyException as e:
                logger.warning(
                    "Failed to fetch tracks for playlist %s: %s",
                    playlist.get("name"),
                    e,
                )

            enriched_playlists.append(playlist)

        logger.info(
            "Successfully enriched %d playlists with tracks", len(enriched_playlists)
        )
        return enriched_playlists

    @spotify_retry
    def get_audio_features(self, track_ids: list[str]) -> list[dict[str, Any]]:
        """複数のトラックのAudio Features(特徴量)を取得します。

        Args:
            track_ids: SpotifyトラックIDのリスト(最大100個)

        Returns:
            Audio Featuresオブジェクトのリスト。
            IDに対応する特徴量が見つからない場合はNoneが含まれる可能性があります。

        Note:
            取得できる特徴量:
            - danceability: 踊りやすさ
            - energy: エネルギッシュさ
            - valence: ポジティブ度(感情)
            - tempo: テンポ(BPM)
            - acousticness: アコースティック感
            etc.
        """
        if not track_ids:
            return []

        logger.debug("Fetching audio features for %d tracks", len(track_ids))

        try:
            all_features = self._fetch_in_chunks(
                track_ids,
                chunk_size=100,
                fetch_fn=lambda chunk: self.sp.audio_features(tracks=chunk),
            )
            logger.info(
                "Successfully fetched audio features for %d tracks", len(all_features)
            )
            return all_features
        except spotipy.SpotifyException as e:
            if e.http_status == 403:
                logger.warning(
                    "Failed to fetch audio features. "
                    "Your account is restricted (403). "
                    "This feature is deprecated for new Spotify Apps "
                    "created after Nov 2024."
                )
                return []
            raise

    @spotify_retry
    def get_tracks(self, track_ids: list[str]) -> list[dict[str, Any]]:
        """複数のトラック情報を取得します。"""
        if not track_ids:
            return []

        logger.debug("Fetching track details for %d tracks", len(track_ids))

        all_tracks = self._fetch_in_chunks(
            track_ids,
            chunk_size=50,
            fetch_fn=lambda chunk: self.sp.tracks(chunk),
            response_key="tracks",
        )
        logger.info("Successfully fetched %d track details", len(all_tracks))
        return all_tracks

    @spotify_retry
    def get_artists(self, artist_ids: list[str]) -> list[dict[str, Any]]:
        """複数のアーティスト情報を取得します。"""
        if not artist_ids:
            return []

        logger.debug("Fetching artist details for %d artists", len(artist_ids))

        all_artists = self._fetch_in_chunks(
            artist_ids,
            chunk_size=50,
            fetch_fn=lambda chunk: self.sp.artists(chunk),
            response_key="artists",
        )
        logger.info("Successfully fetched %d artist details", len(all_artists))
        return all_artists

    def _fetch_in_chunks(
        self,
        ids: list[str],
        chunk_size: int,
        fetch_fn: Callable[[list[str]], Any],
        response_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """IDリストをチャンクに分割してAPIを呼び出す共通ヘルパー。

        Args:
            ids: 取得対象のIDリスト
            chunk_size: 1回のAPIコールで処理するID数
            fetch_fn: チャンクを受け取りAPIレスポンスを返す関数
            response_key: レスポンスから抽出するキー(Noneの場合はレスポンス全体を使用)

        Returns:
            取得したアイテムのリスト(Noneを除外)
        """
        all_items: list[dict[str, Any]] = []

        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            response = fetch_fn(chunk)

            if response_key:
                items = response.get(response_key, []) if response else []
            else:
                items = response if response else []

            all_items.extend([item for item in items if item])

        return all_items
