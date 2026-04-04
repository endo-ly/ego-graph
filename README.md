# EgoGraph

**Personal Data Warehouse in a File.**
DuckDB を用いた、プライバシー重視・サーバーレスな個人ログ分析 RAG システム。

## 概要

EgoGraph は、個人のデジタルライフログ（Spotify, Web, Bank, etc.）をローカルファイル（Parquet/DuckDB）に集約し、**高速な SQL 分析** と **ベクトル検索** を提供するエージェントシステムです。

## 特徴

- **Hybrid Architecture**: **DuckDB** (分析) と **Qdrant** (検索) のベストミックス構成。
- **Data Enrichment**: 外部 API と連携し、個人のログに豊かなコンテキストを付与。
- **Cost Effective**: 安価な VPS と無料のマネージドサービスで動作する、個人に最適な設計。
- **Mobile First**: スマホからいつでも自分のデータにアクセス・対話可能。

## System Architecture

![Architecture Diagram](./docs/10.architecture/diagrams/architecture_diagram.png)

詳細: [システムアーキテクチャ](./docs/10.architecture/01-overview/system-architecture.md)

---

## モノレポ構成

このプロジェクトは、Python (uv workspace) + Kotlin Multiplatform のモノレポです。

```text
ego-graph/
├── egograph/                # EgoGraph: データ収集＆提供
│   ├── backend/             #   FastAPI サーバー（uv workspace メンバー）
│   ├── pipelines/           #   ジョブ管理 + データ収集サービス（uv workspace メンバー）
│   └── browser-extension/   #   ブラウザ履歴収集（Chrome拡張）
├── egopulse/                # EgoPulse: Rust runtime foundation（Cargo workspace メンバー）
├── frontend/                # KMP Android アプリ（Gradle）
│   └── maestro/             #   E2Eテスト
│
├── docs/                    # プロジェクトドキュメント
├── .github/workflows/       # CI/CD ワークフロー
├── pyproject.toml           # Python workspace 設定
├── Cargo.toml               # Rust workspace 設定
└── uv.lock                  # Python 依存関係ロック
```

### コンポーネント概要

| コンポーネント | 役割                        | 技術スタック                                                  | 実行環境                  |
| -------------- | --------------------------- | ------------------------------------------------------------- | ------------------------- |
| **egograph/pipelines/** | データ収集・変換・保存・ジョブ管理 | Python 3.12+, FastAPI, APScheduler, SQLite, DuckDB, boto3 | 常駐サービス |
| **egograph/backend/**   | Agent API・データアクセス   | FastAPI, DuckDB, LLM (DeepSeek/OpenAI)                        | VPS/GCP (常駐サーバー)    |
| **egopulse/**  | Rust runtime foundation     | Rust, Tokio, Reqwest, Clap                                    | Local/Server (常駐予定)   |
| **frontend/**  | チャット UI・Terminal UI    | Kotlin 2.2.21, Compose Multiplatform, MVVM (StateFlow + Channel) | Android (Gradle)          |

旧 React + Capacitor フロントエンドはモノレポから分離され、
[`endo-ava/egograph-frontend-capacitor-legacy`](https://github.com/endo-ava/egograph-frontend-capacitor-legacy)
で保守されています。

---

## Quick Start

### 前提条件

- **Python**: 3.12+ ([uv](https://github.com/astral-sh/uv) 推奨)
- **Rust/Cargo**: stable toolchain（EgoPulse ビルド用）
- **JDK**: 17+ (Android アプリビルド用)
- **Android SDK**: API 34 (Android アプリビルド用)
- **環境変数**: 各コンポーネント配下の `.env.example` を参考に `.env` を作成

### 1. 全体セットアップ

```bash
# uv のインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# Python 依存関係の同期（egograph/backend, egograph/pipelines を一括）
uv sync
```

### 2. コンポーネント別セットアップ

#### A. Pipelines（データ収集・ジョブ管理）

```bash
# 環境変数テンプレートを作成
# `.env.example` はユーザー固有値を中心に載せており、未記載の設定はコード既定値を使う
cp egograph/pipelines/.env.example egograph/pipelines/.env

# 常駐サービス起動
uv run python -m pipelines.main serve

# Workflow 一覧確認
uv run python -m pipelines.main workflow list --json

# テスト実行
uv run pytest egograph/pipelines/tests --cov=pipelines
```

**必要な環境変数**:

- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`
- `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`

#### B. Backend（API サーバー）

```bash
# 環境変数テンプレートを作成
cp egograph/backend/.env.example egograph/backend/.env

# 開発サーバー起動（自動リロード）
uv run uvicorn egograph.backend.main:app --reload --host 127.0.0.1 --port 8000

# ヘルスチェック
curl http://localhost:8000/health

# API ドキュメント
open http://localhost:8000/docs
```

**必要な環境変数**:

- `R2_*`（データアクセス）
- `LLM_*`（チャット機能）

#### C. Frontend（Android アプリ）

```bash
cd frontend

# デバッグビルド
./gradlew :androidApp:assembleDebug

# デバイスにインストール
./gradlew :androidApp:installDebug

# テスト実行
./gradlew :shared:testDebugUnitTest
```

**注意**: エミュレータから localhost にアクセスする場合は `10.0.2.2:8000` を使用してください。

#### D. EgoPulse（Rust runtime foundation）

起動方法と設定例は [`egopulse/README.md`](./egopulse/README.md) を参照してください。

---

## Git Worktree 自動セットアップ

`git worktree add` や `claude -w` で作成された worktree に対して、以下を自動実行できます。

- 設定/認証ファイルのコピー
- `uv sync`
- `npm install`（対象ディレクトリのみ）

### 導入

```bash
bash scripts/install-git-hooks.sh
```

このスクリプトは `core.hooksPath` を `.git/hooks` に設定します（`claude -w` 互換）。

### コピー対象・npm対象のカスタマイズ

- コピー対象: `.git-hooks/worktree-copy-files.txt`
- `npm install` 対象: `.git-hooks/worktree-npm-dirs.txt`

どちらも「1行1パス（リポジトリルートからの相対パス）」で指定します。  
空行と `#` コメントは無視されます。

### 他リポジトリへの流用

以下をコピーして `scripts/install-git-hooks.sh` を実行すれば流用できます。

- `.git-hooks/post-checkout`
- `.git-hooks/setup-worktree.sh`
- `.git-hooks/worktree-copy-files.txt`
- `.git-hooks/worktree-npm-dirs.txt`
- `scripts/install-git-hooks.sh`

---

## Development

### Claude / Codex 連携

Claude 用に管理している Skill / Command を Codex からも使いたい場合は、リポジトリルートで以下を実行してください。

```bash
mkdir -p ~/.codex/skills ~/.codex/prompts

find "$PWD/.claude/skills" -mindepth 1 -maxdepth 1 -type d \
  -exec ln -sfn {} ~/.codex/skills/ \;

find "$PWD/.claude/commands" -mindepth 1 -maxdepth 1 -type f -name '*.md' \
  -exec ln -sfn {} ~/.codex/prompts/ \;
```

- Codex では custom command は `~/.codex/prompts/` 配下の Markdown を slash command として扱います
- Claude の `.claude/commands/*.md` は、そのまま Codex 側の prompt として再利用できます
- Skill は `~/.codex/skills/` 配下に配置すると Codex から参照されます

### テスト実行

```bash
# Python 全テスト
uv run pytest

# コンポーネント別
uv run pytest egograph/pipelines/tests --cov=pipelines
uv run pytest egograph/backend/tests --cov=backend

# Frontend (KMP)
cd frontend && ./gradlew :shared:testDebugUnitTest
```

### Lint & Format

```bash
# Python (Ruff)
uv run ruff check .          # チェックのみ
uv run ruff format .         # フォーマット
uv run ruff check --fix .    # 自動修正

# Frontend (KMP)
cd frontend && ./gradlew ktlintCheck
cd frontend && ./gradlew ktlintFormat
```

### CI/CD

GitHub Actions でコンポーネント別に自動テストが実行されます。

- **ci-backend.yml**: `egograph/backend/` の変更時
- **ci-pipelines.yml**: `egograph/pipelines/` の変更時
- **ci-frontend.yml**: `frontend/` の変更時
- **deploy-backend.yml**: `main` push で backend/pipelines をデプロイ

---

## Documentation

### プロジェクト構成

```
docs/
├── CONCEPT.md                  # ビジョン・目的・Design Philosophy
├── 00.requirements/            # 機能要件定義
├── 10.architecture/            # アーキテクチャ設計
├── 20.technical_selections/    # ADR (技術選定記録)
├── 40.deploy/                  # デプロイ手順
├── 70.knowledge/               # ナレッジベース
└── 99.archive/                 # アーカイブ
```

### コンセプト・ビジョン

- **[CONCEPT.md](./docs/CONCEPT.md)**: EgoGraphのビジョン、解決する課題、Design Philosophy


### コンポーネント詳細 (コード内README)

各コンポーネントの詳細な使い方・セットアップは、各ディレクトリのREADMEを参照してください：

| コンポーネント | README | 内容 |
|--------------|--------|------|
| **Pipelines** | [egograph/pipelines](./egograph/pipelines) | データ収集、compaction、local mirror sync、workflow/run 管理 |
| **Backend** | [egograph/backend/README.md](./egograph/backend/README.md) | Agent API、DuckDB 接続、LLM 統合 |
| **Frontend** | [frontend/README.md](./frontend/README.md) | Android アプリ（KMP）、MVVM構成、リリース手順 |
