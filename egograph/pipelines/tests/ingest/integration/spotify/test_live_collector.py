import logging
import os

from dotenv import load_dotenv

# モジュールとして実行されることを想定
# python -m pipelines.sources.spotify.test_live_collector
from pipelines.sources.spotify.collector import SpotifyCollector

# ロギング設定
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    # .env ファイルの読み込み
    load_dotenv()

    # Arrange: 環境変数の取得と検証
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")

    missing_vars = []
    if not client_id:
        missing_vars.append("SPOTIFY_CLIENT_ID")
    if not client_secret:
        missing_vars.append("SPOTIFY_CLIENT_SECRET")
    if not refresh_token:
        missing_vars.append("SPOTIFY_REFRESH_TOKEN")

    if missing_vars:
        logger.error(f"必要な環境変数が不足しています: {', '.join(missing_vars)}")
        logger.error(".envファイルを確認してください。")
        return

    try:
        # Act 1: Collector の初期化
        logger.info("SpotifyCollectorを初期化しています...")
        collector = SpotifyCollector(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )

        # Act 2: 最近再生した曲の取得
        logger.info("get_recently_played() を実行中...")
        tracks = collector.get_recently_played(limit=5)

        # Assert (Manual): 取得結果の表示
        print("\n" + "=" * 50)
        print("🎵 最近再生した曲 (最新5件)")
        print("=" * 50)

        if not tracks:
            print("再生履歴が見つかりませんでした。")

        for i, item in enumerate(tracks, 1):
            track = item.get("track", {})
            name = track.get("name", "Unknown Title")
            artists = ", ".join([artist["name"] for artist in track.get("artists", [])])
            played_at = item.get("played_at", "Unknown Time")

            print(f"{i}. {name}")
            print(f"   Artist: {artists}")
            print(f"   Played At: {played_at}")
            print("-" * 30)

        print("=" * 50 + "\n")
        logger.info("テストが正常に完了しました。")

    except Exception:
        logger.exception("テスト実行中にエラーが発生しました。")


if __name__ == "__main__":
    main()
