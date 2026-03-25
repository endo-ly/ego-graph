"""データ API スキーマ。

Spotify などのデータ API レスポンスモデルを定義します。
"""

from datetime import datetime

from pydantic import BaseModel


class TopTrackResponse(BaseModel):
    """トップトラック API レスポンス。

    Attributes:
        track_name: 曲名
        artist: アーティスト名
        play_count: 再生回数
        total_minutes: 総再生時間（分）
    """

    track_name: str
    artist: str
    play_count: int
    total_minutes: float


class ListeningStatsResponse(BaseModel):
    """視聴統計 API レスポンス。

    Attributes:
        period: 期間（日付文字列）
        total_ms: 総再生時間（ミリ秒）
        track_count: 再生トラック数
        unique_tracks: ユニーク曲数
    """

    period: str
    total_ms: int
    track_count: int
    unique_tracks: int


class WatchHistoryResponse(BaseModel):
    """視聴履歴 API レスポンス。

    Attributes:
        watch_id: 視聴ID
        watched_at_utc: 視聴日時（UTC）
        video_id: 動画ID
        video_title: 動画タイトル
        channel_id: チャンネルID
        channel_name: チャンネル名
        duration_seconds: 動画長（秒、未取得の場合はNone）
        video_url: 動画URL
    """

    watch_id: str
    watched_at_utc: str
    video_id: str
    video_title: str
    channel_id: str
    channel_name: str
    duration_seconds: int | None = None
    video_url: str


class WatchingStatsResponse(BaseModel):
    """視聴統計 API レスポンス。

    Attributes:
        period: 期間（日付文字列）
        total_seconds: 総視聴時間（秒）
        video_count: 視聴動画数
        unique_videos: ユニーク動画数
    """

    period: str
    total_seconds: int
    video_count: int
    unique_videos: int


class TopChannelResponse(BaseModel):
    """トップチャンネル API レスポンス。

    Attributes:
        channel_id: チャンネルID
        channel_name: チャンネル名
        video_count: 視聴動画数
        total_seconds: 総視聴時間（秒）
    """

    channel_id: str
    channel_name: str
    video_count: int
    total_seconds: int


class PageViewResponse(BaseModel):
    """Browser History page view レスポンス。"""

    page_view_id: str
    started_at_utc: datetime
    ended_at_utc: datetime
    url: str
    title: str | None = None
    browser: str
    profile: str
    transition: str | None = None
    visit_span_count: int


class TopDomainResponse(BaseModel):
    """Browser History top domains レスポンス。"""

    domain: str
    page_view_count: int
    unique_urls: int
