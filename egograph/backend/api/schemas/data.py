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


class WatchEventResponse(BaseModel):
    """視聴イベント API レスポンス。

    Attributes:
        watch_event_id: 視聴イベントID
        watched_at_utc: 視聴日時（UTC）
        video_id: 動画ID
        video_url: 動画URL
        video_title: 動画タイトル
        channel_id: チャンネルID
        channel_name: チャンネル名
        content_type: コンテンツ種別（video / short）
    """

    watch_event_id: str
    watched_at_utc: str
    video_id: str
    video_url: str
    video_title: str
    channel_id: str | None = None
    channel_name: str | None = None
    content_type: str


class WatchingStatsResponse(BaseModel):
    """視聴統計 API レスポンス。

    Attributes:
        period: 期間（日付文字列）
        watch_event_count: 視聴イベント数
        unique_video_count: ユニーク動画数
        unique_channel_count: ユニークチャンネル数
    """

    period: str
    watch_event_count: int
    unique_video_count: int
    unique_channel_count: int


class TopChannelResponse(BaseModel):
    """トップチャンネル API レスポンス。

    Attributes:
        channel_id: チャンネルID
        channel_name: チャンネル名
        watch_event_count: 視聴イベント数
        unique_video_count: ユニーク動画数
    """

    channel_id: str | None = None
    channel_name: str | None = None
    watch_event_count: int
    unique_video_count: int


class TopVideoResponse(BaseModel):
    """トップ動画 API レスポンス。

    Attributes:
        video_id: 動画ID
        video_title: 動画タイトル
        channel_id: チャンネルID
        channel_name: チャンネル名
        watch_event_count: 視聴イベント数
    """

    video_id: str
    video_title: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    watch_event_count: int


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
