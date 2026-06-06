<p align="center">
  <img src="./docs/assets/readme/hero.png" width="600">
</p>

<p align="center">
  <strong>Personal Data Warehouse</strong><br>
  散在する個人データを一箇所に集約し、Parquet + DuckDB で自由にクエリ可能なデータ基盤を構築する
</p>

## Why EgoGraph

個人のデジタルデータは数多くのサービスに分散している。「去年の夏によく聴いていた曲は？」「あの技術記事をいつ読んだっけ？」といった問いに答えるには、各サービスを個別に開いて探すしかない。また、汎用的なAIに質問しても、ユーザー個人のデータにはアクセスできないため答えることができない。

EgoGraphは、この課題を「データの統合」で解決する。

- **データ層（EgoGraph）**: 各種サービスからデータを定期収集し、Parquetファイルとして一元管理する。一度集めればDuckDBで自由にクエリできるため、データをエクスポートして死蔵させることはない。
- **AIエージェント** — [EgoPulse](https://github.com/endo-ly/egopulse)（別レポジトリ）が EgoGraph を主要なデータソースのひとつとして利用し、個人の文脈に基づいた対話や自律実行を担う

## Quick Start

### Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.12+（[uv](https://github.com/astral-sh/uv) 推奨） |
| JDK | 17+（Android アプリビルド用・任意） |

### 1. Clone & Setup

```bash
git clone https://github.com/endo-ava/egograph.git
cd egograph
uv sync
```

### 2. EgoGraph（Pipelines & API）

```bash
# Pipelines Service 起動（スケジュール駆動でデータ収集）
uv run python -m egograph.pipelines.main serve

# Data API / MCP Server 起動 → http://localhost:8000/docs
uv run python -m egograph.backend.main
```

環境変数は `.env.example` を参照。

### 3. Frontend（Android アプリ・任意）

```bash
cd frontend
./gradlew :androidApp:assembleDebug
./gradlew :androidApp:installDebug
```

## Features & Architecture

![architecture](./docs/assets/readme/architecture.png)

### EgoGraph — Personal Data Warehouse

- **常駐 Pipelines Service** — APScheduler によるスケジュール駆動。SQLite で workflow / run / step / lock を管理
- **マルチソース収集** — Spotify、ブラウザ履歴、GitHub、Google Activity、ローカルミラー同期に対応
- **Parquet + R2** — 分析用データを Parquet 形式で Cloudflare R2 またはローカルに保存
- **DuckDB 即時分析** — `:memory:` モードで R2 から直接 Parquet を読み込み、サーバーレスで SQL 分析
- **Data API + MCP Server** — REST API と MCP で蓄積データへのアクセスを提供し、可視化や外部エージェント連携の土台になる
- **増分取り込み** — カーソルで前回位置を追跡し、差分のみを取得

### Frontend — Mobile App

- **Kotlin Multiplatform** — Compose Multiplatform によるネイティブ Android アプリ
- **ストリーミングチャット** — AI チャットインターフェース（ストリーミング対応）
- **データ可視化** — 個人データのグラフ・チャート表示（WIP）

詳細なアーキテクチャ設計は [docs/architecture/](./docs/architecture/) を参照。

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| EgoGraph Pipelines | Working | 常駐 Pipelines Service。Spotify / ブラウザ履歴 / GitHub / Google Activity 対応済み |
| EgoGraph Backend | Working | FastAPI + DuckDB + REST API / MCP Server |
| Frontend (Android) | Active Development | チャット UI 実装済み。データ可視化は WIP |

## Documentation

| Document | Description |
|----------|-------------|
| [CONCEPT.md](./docs/CONCEPT.md) | ビジョン・目的・設計思想 |
| [Architecture](./docs/architecture/) | システムアーキテクチャ設計 |
| [Tech Stack](./docs/knowledge/technical-selections/) | 技術選定記録（ADR） |
| [Deploy](./docs/deploy/) | デプロイ手順 |

### Component READMEs

| Component | README |
|-----------|--------|
| Pipelines | [egograph/pipelines/README.md](./egograph/pipelines/README.md) |
| Backend | [egograph/backend/README.md](./egograph/backend/README.md) |
| Frontend | [frontend/README.md](./frontend/README.md) |
| Browser Extension | [egograph/browser-extension/chromium-history/README.md](./egograph/browser-extension/chromium-history/README.md) |

### Related Repositories

| Repository | Description |
|-----------|-------------|
| [endo-ly/egopulse](https://github.com/endo-ly/egopulse) | AI Agent Runtime — TUI / Web / Discord / Telegram を単一バイナリで提供する Rust 製エージェントランタイム |
