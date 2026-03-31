# EgoGraph 開発ガイドライン

## 概要

Personal AI Agent and Personal Data Warehouse and Personal Mobile App（サーバーレス・ローカルファースト）

構成: Python (uv workspace) + Kotlin Multiplatform / Compose Multiplatform

## アーキテクチャ

### ingest (データ収集)

ETL/ELT Pipeline: Provider → Collector → Transform → Storage → Data Lake

- Collector: API から生データ取得
- Transform: クレンジング & スキーママッピング
- Storage: Parquet (分析用) + JSON (Raw) を R2 に保存
- Stateful: R2 内のカーソル位置を追跡し、増分取り込みをサポート
- Tech Stack: Python 3.12+, DuckDB, boto3

### backend (Agent API)

DDD (Domain-Driven Design) - レイヤードアーキテクチャ

- api/: プレゼンテーション (FastAPI ルート、リクエスト/レスポンス)
- usecases/: アプリケーション (ユースケース、ツールファクトリ、LLM調整)
- infrastructure/: インフラストラクチャ (DuckDB、LLMプロバイダ、Repository実装)
- database/: DuckDB ステートレス設計（`:memory:`）、R2 から直接 Parquet 読み込み
- Tech Stack: FastAPI, Uvicorn, DuckDB, pandas, httpx, Pydantic

### frontend (Mobile App)

MVVM (StateFlow + Channel) - Kotlin Multiplatform + Compose Multiplatform

- core/domain/: DTOs, Repository インターフェース
- core/network/: HTTP クライアント (Ktor)
- features/: 機能モジュール (Screen + ScreenModel + State + Effect)
- di/: 依存性注入 (Koin)

| レイヤー    | 役割                       | 例                 |
| ----------- | -------------------------- | ------------------ |
| Screen      | Compose UI 表示            | ChatScreen.kt      |
| ScreenModel | ビジネスロジック・状態更新 | ChatScreenModel.kt |
| State       | UI 状態（データクラス）    | ChatState.kt       |
| Effect      | One-shot イベント          | ChatEffect.kt      |

- DI: Koin 4.0.0
- State Management: StateFlow + Channel (Kotlin Coroutines)
- Tech Stack: Kotlin 2.2.21, Compose Multiplatform 1.9.0, Ktor 3.3.3, Voyager 1.1.0-beta03, Kermit
- Testing: kotlin-test, Turbine, MockK, Ktor MockEngine

## 開発コマンド

```bash
# === Python Workspace ===
uv sync                           # 依存関係同期
uv run pytest                     # 全テスト
uv run ruff check .               # Lint
uv run ruff check . --fix         # Lint & Fix
uv run ruff format .              # Format

# === Ingest ===
uv run python -m ingest.spotify.main
uv run pytest ingest/tests --cov=ingest

# === Backend ===
tmux new-session -d -s fastapi 'uv run python -m backend.main'
uv run python -m backend.main
uv run pytest backend/tests --cov=backend
uv run python -m backend.dev_tools.chat_cli   # デバッグ用CLIツール

# === Frontend (cd frontend) ===
cd frontend # PJルートからはgradlewは使えないことに注意
./gradlew :androidApp:assembleDebug      # ビルド
./gradlew :androidApp:installDebug      # インストール
./gradlew :shared:testDebugUnitTest     # テスト
./gradlew :shared:koverHtmlReportDebug  # カバレッジ率
./gradlew ktlintCheck                   # Lint
./gradlew ktlintFormat                  # Format
./gradlew detekt                        # 静的解析
# NOTE: ktlintFormat/ktlintCheck は同一コマンドで連続実行せず、先に ktlintFormat 単体で実行する（同一Gradle実行内だと ktlintCheck が先に走って失敗することがあるため）

# === E2E Test (Maestro) ===
maestro test maestro/flows/           # 全テスト一括実行

# === Coderabbit review ===
coderabbit --prompt-only -t uncommitted              # Commit前
coderabbit --prompt-only -t committed --base main    # PR作成前
```

## 規約

### コーディング

#### 基本原則

- **「長期的な保守性」「コードの美しさ」「堅牢性」**を担保するようなコーディングを意識
  - SOLID原則
  - KISS (Keep It Simple, Stupid) & YAGNI (You Ain't Gonna Need It):
  - DRY (Don't Repeat Yourself)
  - 責務の分離 (Separation of Concerns): ビジネスロジック、UI、データアクセスなどが適切に分離されているか？
  - 可読性と美しさ

#### その他のルール

| 項目      | ルール                                             |
| --------- | -------------------------------------------------- |
| SQL       | プレースホルダ必須: `execute(query, (param,))`     |
| Logging   | 遅延評価 `logger.info("k=%s", v)`, 機密情報禁止    |
| APIエラー | 統一フォーマット `invalid_<field>: <reason>`       |
| Docstring | 日本語                                             |
| テスト    | AAA パターン必須、Python: pytest、Frontend: Kotest |

### Git / CI

- GitHub Flow: `main` 直接コミット禁止、ブランチ `<type>/<desc>`
- コミット: Conventional Commits（英語）
- ワークフロー: `ci-*.yml`(テスト), `job-*.yml`(定期), `deploy-*.yml`, `release-*.yml`

## デバッグ

### スキル選択

| シナリオ             | 使用スキル                             | 説明                                           |
| -------------------- | -------------------------------------- | ---------------------------------------------- |
| APIのみ          | `tmux-api-debug`                       | Backend APIの動作確認・デバッグ                |
| UI + API（E2E）  | `android-adb-debug` + `tmux-api-debug` | フロントエンドからバックエンドまでの統合テスト |
| LLM ToolCall検証 | `agent-tool-test`                      | 各LLMモデルの全ツール使用可否テスト            |

### 環境構成

```
Linux ─ Backend (tmux) + ADB Client
    ↓ Tailscale:100.x.x.x:5559
Windows ─ netsh (0.0.0.0:5559→127.0.0.1:5555) ─ Android Emulator (:5555)
```

※ 5559を外部公開する理由: エミュレータの:5555とのポート競合回避

### Frontend～Backend間の検証方法

1. Windows側でエミュ起動 or デバッグ用実機でadb待ち受け（ユーザー作業）
2. Linux から ADB 接続（`adb connect <WINDOWS_OR_ANDROID_IP>:PORT`）(エミュ:5559, 実機:5669)
3. Backend を起動（tmux推奨）
4. adb コマンドで現在の挙動を確認しながら実装
5. ビルド & インストール
6. adb コマンドでビルド内容の確認

# initial plan review request

## 必ず -m でモデルを指定すること
```bash
codex exec -m gpt-5.4 "このプランをレビューして。致命的な点だけ指摘して: {plan_full_path} (ref: {CLAUDE.md full_path})"
```

# updated plan review request
```bash 
resume --last をつけないと最初のレビューの文脈が失われるから注意
codex exec resume --last -m gpt-5.4 "プランを更新したからレビューして。致命的な点だけ指摘して: {plan_full_path} (ref: {CLAUDE.md full_path})"
```

## その他

- 質問は `AskUserQuestion` 等を積極的に活用
- サブエージェント活用でコンテキストをクリーンに（`delegate_task` を使用、`task` は使わない）
- コード変更後はテスト確認必須
- **コードレビューで一つも指摘されないレベル**のコード品質を目指す。不十分なコードの場合、レビュー指摘によりより多くの時間とトークンを消費します
- 目の前の目標を達成するためだけの場当たり的な対応は禁止
  - バグを潰すための場当たり的なフォールバック処理
  - テストやビルドを通すためだけの本質的ではない修正
- 「後方互換」は負債にしかならないため禁止 
- うまくいかない時にコードを増やし続けない。コードを削除する勇気を持つ。シンプルが最も美しい。
- ui/uxの調整タスクは言葉での認識合わせが難しいことを考慮し、必要に応じてASCII等を使いながらユーザーに確認する
- `.env`系を読むことは禁止
- ローカル秘密設定ファイル（例: `egopulse/egopulse.local.yaml`）も読まないこと。秘密が必要な場合はユーザーに値を明示してもらうか、実行時の環境変数/引数で受け取る前提で進める
