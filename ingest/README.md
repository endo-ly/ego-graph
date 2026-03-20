# Ingest Service

データ収集、変換、および Parquet データレイク構築サービス。

## Overview

Ingest サービスは、外部プロバイダー（例：Spotify）からデータを取得し、構造化されたフォーマットに変換して、Data Lake（Cloudflare R2）に保存する役割を担います。

- **Idempotent**: 同じデータに対して何度再実行しても重複が発生しません。
- **Stateful**: R2 内のカーソル位置（例：`processed_at`）を追跡し、増分取り込みをサポートします。

## Architecture

```text
Providers (API) -> Collector -> Transform -> Storage -> Data Lake (R2)
```

- **Collector**: API から生データを取得します。
- **Transform**: データをクレンジングし、スキーマにマッピングします。
- **Storage**: Parquet（正本 / compact版）および JSON（監査用 Raw データ）ファイルを R2 に書き込みます。

### Data Lake Schema (R2)

- **Events**: `s3://egograph/events/spotify/plays/year=YYYY/month=MM/*.parquet`
  - 年月でパーティショニングされています。
  - ingest の append-only 正本です。
- **Master**: `s3://egograph/master/spotify/{tracks,artists}/year=YYYY/month=MM/*.parquet`
  - 参照系データの append-only 正本です。
- **Compacted Events**: `s3://egograph/compacted/events/<provider>/<dataset>/year=YYYY/month=MM/data.parquet`
  - backend の読み込み対象です。
- **Compacted Master**: `s3://egograph/compacted/master/<provider>/<dataset>/year=YYYY/month=MM/data.parquet`
  - master 系の読み込み対象です。
- **Raw**: `s3://egograph/raw/spotify/recently_played/YYYY/MM/DD/*.json`
  - 監査/再生用のオリジナルの API レスポンス。
- **State**: `s3://egograph/state/*.json`
  - 取り込み用のカーソルを保存します。

## Setup & Usage

### Prerequisites

- Python 3.12+
- `uv` パッケージマネージャー

### Environment Setup

1.  依存関係の同期:
    ```bash
    uv sync
    ```
2.  `.env` の設定:
    - `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`
    - `R2_*` クレデンシャル

### Running Ingestion

```bash
# 手動での取り込み実行 (Spotify)
uv run python -m ingest.spotify.main

# 初回 bootstrap 用に workflow 対象の compact を一括生成
uv run python -m ingest.bootstrap_compact

# 当月の compact 版を生成 (Spotify)
uv run python -m ingest.spotify.compact

# 当月の compact 版を生成 (GitHub)
uv run python -m ingest.github.compact
```

利用可能なモジュール:

- `ingest.spotify.main`: Spotify から最近の再生履歴を取得します。
- `ingest.bootstrap_compact`: workflow 管理対象 provider の compact 版を R2 上の全対象月について一括生成します。
- `ingest.spotify.compact`: Spotify の events/master を月次 compact 化します。
- `ingest.github.compact`: GitHub の events を月次 compact 化します。

## Initial Bootstrap Note

`ingest.bootstrap_compact` は `backend/.env` を自動では読みません。
初回手動実行時は、`R2_*` 環境変数をシェルに読み込んでから実行してください。

```bash
set -a
source <(grep '^R2_' backend/.env)
set +a

uv run python -m ingest.bootstrap_compact
```

## Automation

取り込みジョブは GitHub Actions で自動化されています:

- `.github/workflows/job-ingest-spotify.yml`
- スケジュール: 1 日 2 回 (02:00 UTC, 14:00 UTC)。
- ingest 完了後に当月の compact 版を再生成します。

## Testing

```bash
# 全ての取り込みテストを実行
uv run pytest ingest/tests

# カバレッジ付きで実行
uv run pytest ingest/tests --cov=ingest
```
