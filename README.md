<p align="center">
  <img src="./docs/assets/readme/hero.png" width="600">
</p>

<p align="center">
  <strong>Personal Data Warehouse × AI Agent Runtime</strong><br>
  散在する個人データを一箇所に集約し、自分自身の文脈を理解するAIエージェントを構築する
</p>

## Why EgoGraph

個人のデジタルデータは数多くのサービスに分散している。「去年の夏によく聴いていた曲は？」「あの技術記事をいつ読んだっけ？」といった問いに答えるには、各サービスを個別に開いて探すしかない。また、汎用的なAIに質問しても、ユーザー個人のデータにはアクセスできないため答えることができない。

EgoGraphは、この課題を「データの統合」と「AIエージェントによる活用」の2層で解決する。

- **データ層（EgoGraph）**: 各種サービスからデータを定期収集し、Parquetファイルとして一元管理する。一度集めればDuckDBで自由にクエリできるため、データをエクスポートして死蔵させることはない。
- **エージェント層（EgoPulse）** — LLM Agent が EgoGraph の蓄積データにツール経由でアクセスし、個人の文脈に基づいた回答を返す。TUI / Web / Discord / Telegram のいずれからでも同じデータにアクセスできる

## Quick Start

### Prerequisites

| Component | Requirement |
|-----------|-------------|
| Python | 3.12+（[uv](https://github.com/astral-sh/uv) 推奨） |
| Rust | stable（EgoPulse ビルド用） |
| JDK | 17+（Android アプリビルド用・任意） |

### 1. Clone & Setup

```bash
git clone https://github.com/endo-ava/ego-graph.git
cd ego-graph
uv sync
```

### 2. EgoGraph（Pipelines & API）

```bash
# Pipelines Service 起動（スケジュール駆動でデータ収集）
uv run python -m egograph.pipelines.main serve

# Agent API サーバー起動 → http://localhost:8000/docs
uv run python -m egograph.backend.main
```

環境変数は `.env.example` を参照。

### 3. EgoPulse（AI エージェント）

```bash
# バイナリインストール(推奨)
curl -fsSL https://raw.githubusercontent.com/endo-ava/ego-graph/main/scripts/install-egopulse.sh | bash
egopulse setup                     # 初回セットアップウィザード
egopulse run                      # 全チャネル起動（Web / Discord / Telegram）

# またはソースから起動
cargo run -p egopulse -- run         # 全チャネル起動（Web / Discord / Telegram）
```

OpenAI 互換エンドポイント（OpenRouter, Ollama 等）に対応。詳細は [egopulse/README.md](./egopulse/README.md) を参照。

### 4. Frontend（Android アプリ・任意）

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
- **Agent API** — LLM が定義済みツールを呼び出して蓄積データにアクセスし、ユーザーの問い合わせに応答する
- **増分取り込み** — カーソルで前回位置を追跡し、差分のみを取得

### EgoPulse — AI Agent Runtime

- **マルチチャネル** — TUI / Web UI（React + SSE + WebSocket）/ Discord / Telegram を単一バイナリで提供
- **永続セッション** — SQLite で会話履歴を管理。セッションの再開・切り替えに対応
- **OpenAI 互換** — OpenAI、OpenRouter、Ollama、ローカル LLM など幅広く対応
- **セットアップウィザード** — `egopulse setup` で対話型 TUI から初期設定
- **systemd 統合** — `egopulse gateway install` で本番サーバーにデプロイ
- **Rust 製** — Tokio 非同期ランタイムで軽量・高速に動作

### Frontend — Mobile App

- **Kotlin Multiplatform** — Compose Multiplatform によるネイティブ Android アプリ
- **ストリーミングチャット** — AI チャットインターフェース（ストリーミング対応）
- **データ可視化** — 個人データのグラフ・チャート表示（WIP）

詳細なアーキテクチャ設計は [docs/10.architecture/](./docs/10.architecture/) を参照。

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| EgoGraph Pipelines | Working | 常駐 Pipelines Service。Spotify / ブラウザ履歴 / GitHub / Google Activity 対応済み |
| EgoGraph Backend | Working | FastAPI + DuckDB + LLM Tool Use |
| EgoPulse | Working | TUI / Web UI / Discord / Telegram 対応済み。systemd 統合済み |
| Frontend (Android) | Active Development | チャット UI 実装済み。データ可視化は WIP |

> 個人プロジェクトとして開発中のため、破壊的変更が随時発生します。

## Documentation

| Document | Description |
|----------|-------------|
| [CONCEPT.md](./docs/CONCEPT.md) | ビジョン・目的・設計思想 |
| [Architecture](./docs/10.architecture/) | システムアーキテクチャ設計 |
| [Tech Stack](./docs/70.knowledge/technical-selections/) | 技術選定記録（ADR） |
| [Deploy](./docs/50.deploy/) | デプロイ手順 |

### Component READMEs

| Component | README |
|-----------|--------|
| Pipelines | [egograph/pipelines/README.md](./egograph/pipelines/README.md) |
| Backend | [egograph/backend/README.md](./egograph/backend/README.md) |
| EgoPulse | [egopulse/README.md](./egopulse/README.md) |
| Frontend | [frontend/README.md](./frontend/README.md) |
