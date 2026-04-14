# EgoGraph

## プロジェクトコンセプト

- 散在する個人データを一箇所に集約し、自分自身の文脈を理解するAIエージェントを構築する
- 以下の2層で実現
  - データ層（EgoGraph）: 各種サービスからデータを定期収集し、Parquetファイルとして一元管理する。データ提供APIをMCPとして提供するエージェントファースト設計。
  - エージェント層（EgoPulse）: Openclaw, Microclaw風の完全自律型AIエージェント。EgoGraph の蓄積データにツール経由でアクセス。

## アーキテクチャ

Python (uv workspace) + Rust (Cargo) + Kotlin Multiplatform / Compose Multiplatform

コンポーネントごとの詳しい説明は`docs/`配下にまとまっている。調査する際はまずそこを読む

### egograph/pipelines (データ収集・ジョブ実行)

常駐 Pipelines Service + ETL/ELT Pipeline。R2 に Parquet + JSON を保存し、SQLite でジョブ状態を管理。
詳細: @docs/20.egograph/pipelines/

### egograph/backend (データ提供API)

DDD レイヤードアーキテクチャ（api / usecases / infrastructure / database）。DuckDBでParquet読み込み。
詳細: @docs/20.egograph/backend/

### frontend (Mobile App)

MVVM (StateFlow + Channel) - Kotlin Multiplatform + Compose Multiplatform。
features/ 配下に Screen + ScreenModel + State + Effect の各モジュール。DI は Koin。
将来的に、収集データの可視化やエージェントの管理画面などで使用する予定。
詳細: @docs/40.frontend/

### egopulse (Personal Agent Runtime)

シングルバイナリの常駐 AI エージェントランタイム。TUI / Web / Discord / Telegram で永続セッションを共有。
詳細: @docs/30.egopulse/

## 開発コマンド

```bash
# === Python Workspace ===
uv sync                           # 依存関係同期
uv run pytest                     # 全テスト
uv run ruff check .               # Lint
uv run ruff check . --fix         # Lint & Fix
uv run ruff format .              # Format

# === Pipelines ===
uv run python -m pipelines.main serve
uv run python -m pipelines.main workflow list --json
uv run pytest egograph/pipelines/tests --cov=pipelines

# === Backend ===
uv run python -m egograph.backend.main
uv run pytest egograph/backend/tests --cov=backend
uv run python -m egograph.backend.dev_tools.chat_cli

# === Frontend (cd frontend) ===
# ※ルートからはgradlew不可。必ず cd frontend してから実行
# ※ktlintFormat と ktlintCheck は別々に実行（同一Gradle実行内だと競合）
./gradlew :androidApp:assembleDebug
./gradlew :androidApp:installDebug
./gradlew :shared:testDebugUnitTest
./gradlew ktlintFormat
./gradlew ktlintCheck
./gradlew detekt

# === EgoPulse (cd egopulse) ===
cargo fmt --check
cargo check -p egopulse
cargo clippy --all-targets --all-features -- -D warnings
cargo test -p egopulse

# === Coderabbit review ===
coderabbit --prompt-only -t uncommitted
coderabbit --prompt-only -t committed --base main
```

## 規約

### コーディング

- **「長期的な保守性」「コードの美しさ」「堅牢性」** を担保するコーディング
  - SOLID 原則
  - KISS (Keep It Simple, Stupid) & YAGNI (You Ain't Gonna Need It)
  - DRY (Don't Repeat Yourself)
  - 責務の分離: ビジネスロジック、UI、データアクセスなどが適切に分離されているか
  - 可読性と美しさ
- **コードレビューで一つも指摘されないレベル**のコード品質を目指す。Coderabbit,Codexのレビューはとても細かいです。
- 場当たり的な対応は禁止（バグフォールバック、ビルド/テスト通過のためだけの本質的でない修正）
- 「後方互換」は負債。既存利用維持のための互換分岐や旧仕様フォールバックは追加しない。新仕様へ一直線に置き換える
- うまくいかない時にコードを増やし続けない。コードを削除する勇気を持つ。シンプルが最も美しい
- frontend実装はエミュレータ―接続前提。目視確認のため、`installDebug`までおこなうこと。接続されてない場合は報告。
- Rust実装後は`fmt`,`test`,`check`,`clippy`必須

| 項目      | ルール                                             |
| --------- | -------------------------------------------------- |
| SQL       | プレースホルダ必須: `execute(query, (param,))`     |
| Logging   | 遅延評価 `logger.info("k=%s", v)`, 機密情報禁止    |
| APIエラー | 統一フォーマット `invalid_<field>: <reason>`       |
| Docstring | 日本語                                             |
| テスト    | AAA パターン必須、Python: pytest、Frontend: Kotest |

### 文書

- 文書作成時はどんな時でも **MECE** を意識する（セクション構成、要件定義、設計書、PR詳細などすべて）
- 実装後、関連内容が`docs/`にある場合は必ず反映する

### Git / CI / PR

- GitHub Flow: ブランチ `<type>/<desc>`
- コミット: Conventional Commits（英語）
- ワークフロー: `ci-*.yml`(テスト), `job-*.yml`(定期), `deploy-*.yml`, `release-*.yml`
- Issue, Planなど、**計画あり**で進めた実装: Git Worktreeを作成しその中で作業する（`worktree-create` skill使用）
- ブレインストーミングや壁打ち系など、**計画なし**で進めた実装: mainブランチで作業やプッシュしてよい
- PR description は日本語。該当Issueがある場合は `Close #XX` 明記
- PR レビューはCoderabbitが自動で提供。PR作成後10分程度の時間差あり。レビューバックは`pr-review-back-workflow` skill使用

### セキュリティ

- `.env` 系・ローカル秘密設定ファイルの読み取り禁止。秘密が必要な場合はユーザーに明示してもらう

## デバッグ

| シナリオ             | 使用スキル                             |
| -------------------- | -------------------------------------- |
| APIのみ          | `tmux-api-debug`                       |
| UI + API（E2E）  | `android-adb-debug` + `tmux-api-debug` |
| LLM ToolCall検証 | `agent-tool-test`                      |

## Plan作成方針

- Planのスコープ: WT作成 -> 実装(TDD) -> コミット(意味ごとに分離) -> PR作成 （必ずWT作成と明示する）
- 計画には必ずUTや動作確認などの検証を入れる
- プランではコード(How) を書きすぎない。また、プラン冒頭に以下文言を記載する
  - 「Howはあくまで参考であり、よりよい設計方針があれば各自で判断し採用する」

- プラン作成後は以下の方法でレビュー依頼

初回:
```bash
codex exec -m gpt-5.4 "このプランをレビューして。致命的な点だけ指摘して: {plan_path}"
```
更新:
```bash
codex exec resume --last -m gpt-5.4 "プランを更新したからレビューして。致命的な点だけ指摘して: {plan_path}"
```