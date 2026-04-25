# Plan: EgoPulse の別リポジトリ（endo-ly/egopulse）への切り出し

EgoPulse を egograph モノレポから独立リポジトリに切り出す。306コミットの履歴を保持し、ドキュメント・CI/CD・インストールスクリプト・Claude設定も移行する。

> **Note**: 以下の具体的な手順・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **履歴保持**: `git filter-repo --subdirectory-filter` で egopulse/ 配下の全306コミットを移行
- **ドキュメント移行**: egopulse固有ドキュメントをすべて新レポに移し、新レポ内で自己完結させる
- **Claude設定移行**: `.claude/` 内の Rust/React 関連設定・汎用スキル・エージェント・コマンドを新レポにコピー
- **参照更新**: 新レポ内のURL・パス・リンクを `endo-ly/egopulse` 向けに更新
- **egograph側のクリーンアップ**: WTを作成し、残留ファイル・参照を削除して EgoGraph 単体として整える
- **Issue移行**: `gh issue transfer` で egopulse関連Issue（open/closed全14件）を新レポに移転

## Plan スコープ

新レポ作成＋履歴抽出 → egograph側は **WT作成** してクリーンアップ → 動作確認

## 移行対象一覧

### 新レポ（endo-ly/egopulse）に移すもの

| カテゴリ | 現在のパス | 新パス | 移行方式 |
|---|---|---|---|
| **ソースコード** | `egopulse/` | `/`（ルート） | `git filter-repo --subdirectory-filter` で履歴保持 |
| **CI** | `.github/workflows/ci-egopulse.yml` | `.github/workflows/ci.yml` | コピー（履歴は消える） |
| **CI** | `.github/workflows/release-egopulse.yml` | `.github/workflows/release.yml` | コピー |
| **インストールスクリプト** | `scripts/install-egopulse.sh` | `scripts/install.sh` | コピー |
| **ドキュメント** | `docs/30.egopulse/` (10ファイル) | `docs/` | コピー |
| **ドキュメント** | `docs/50.deploy/egopulse.md` | `docs/deploy.md` | コピー |
| **ドキュメント** | `docs/70.knowledge/system_prompt_design.md` | `docs/knowledge/system-prompt-design.md` | コピー |
| **README** | `egopulse/README.md` | `README.md`（既存をベースに更新） | コピー＋更新 |
| **Claude Agents** | `.claude/agents/` (3ファイル) | `.claude/agents/` | コピー |
| **Claude Commands** | `.claude/commands/` (10ファイル) | `.claude/commands/` | コピー |
| **Claude Rules** | `.claude/rules/rust-best-practices.md` | `.claude/rules/rust-best-practices.md` | コピー |
| **Claude Rules** | `.claude/rules/react-best-practices.md` | `.claude/rules/react-best-practices.md` | コピー |
| **Claude Skill** | `.claude/skills/brainstorming/` | `.claude/skills/brainstorming/` | コピー |
| **Claude Skill** | `.claude/skills/github-raw-fetch/` | `.claude/skills/github-raw-fetch/` | コピー |
| **Claude Skill** | `.claude/skills/implementation-plan/` | `.claude/skills/implementation-plan/` | コピー |
| **Claude Skill** | `.claude/skills/pr-review-back-workflow/` | `.claude/skills/pr-review-back-workflow/` | コピー |
| **Claude Skill** | `.claude/skills/pr-review-extraction/` | `.claude/skills/pr-review-extraction/` | コピー |
| **Claude Skill** | `.claude/skills/requirements-definition/` | `.claude/skills/requirements-definition/` | コピー |
| **Claude Skill** | `.claude/skills/tmux-api-debug/` | `.claude/skills/tmux-api-debug/` | コピー |
| **Claude Skill** | `.claude/skills/worktree-create/` | `.claude/skills/worktree-create/` | コピー |
| **Claude Skill** | `.claude/skills/agent-tool-test/` | `.claude/skills/agent-tool-test/` | コピー |

### egograph に残す .claude/ ファイル

| パス | 理由 |
|---|---|
| `.claude/rules/python-best-practices.md` | Python 固有 |
| `.claude/rules/backend-testing.md` | Python テスト固有 |
| `.claude/skills/adb-connection-troubleshoot/` | Android 固有 |
| `.claude/skills/android-adb-debug/` | Android 固有 |
| `.claude/skills/pipelines-debug/` | EgoGraph Pipelines 固有 |

### egograph に残すもの（参照更新のみ）

| ファイル | 変更内容 |
|---|---|
| `README.md` | EgoPulseセクション削除、別レポへの参照に変更 |
| `AGENTS.md` | egopulse関連セクション削除 |
| `CLAUDE.md` | egopulse関連セクション削除 |
| `docs/CONCEPT.md` | Agent Runtime節を「別レポ」として再構成 |
| `docs/10.architecture/system-architecture.md` | EgoPulse節削除・参照更新 |
| `docs/10.architecture/README.md` | EgoPulseリンク更新 |
| `docs/assets/readme/architecture.prompt.md` | Layer 4（EgoPulse）削除 |
| `docs/assets/readme/architecture.png` | 再生成 |

### egograph から削除するもの

| パス | 備考 |
|---|---|
| `egopulse/` | ソースコード全体 |
| `Cargo.toml`（ルート） | メンバーが egopulse のみなので不要になる |
| `Cargo.lock`（ルート） | 同上 |
| `docs/30.egopulse/` | 新レポに移行済み |
| `docs/50.deploy/egopulse.md` | 新レポに移行済み |
| `docs/70.knowledge/system_prompt_design.md` | 新レポに移行済み |
| `.github/workflows/ci-egopulse.yml` | 新レポに移行済み |
| `.github/workflows/release-egopulse.yml` | 新レポに移行済み |
| `scripts/install-egopulse.sh` | 新レポに移行済み |

### Issue移行対象（全14件: open 2 / closed 12）

| Issue番号 | 状態 | タイトル |
|---|---|---|
| #96 | CLOSED | [REQ] EgoPulse MVP Issue 1 Runtime Foundation |
| #97 | CLOSED | [REQ] EgoPulse MVP Issue 2 Persistent Agent Core |
| #98 | CLOSED | [REQ] EgoPulse MVP — Surfaces & MVP Completion (Parent) |
| #102 | CLOSED | [REQ] EgoPulse Issue 2.5: local TUI and config polish |
| #104 | CLOSED | [REQ] #3 Gateway Foundation — EgoPulse サーバー化 |
| #123 | CLOSED | security: EgoPulse Config の Secret 管理 |
| #135 | CLOSED | refactor: egopulse God Module 分割 + ネスト解消 |
| #136 | CLOSED | fix: egopulse 生産コードのパニック根絶 |
| #137 | CLOSED | improve: egopulse 設定の外部化 + セキュリティ改善 |
| #138 | CLOSED | improve: egopulse 品質磨き上げ |
| #155 | OPEN | [Egopulse] 設定の即時反映境界を整理する |
| #156 | CLOSED | [Egopulse] config / setup / config persistence の責務を整理する |
| #157 | CLOSED | [Egopulse] ToolRegistry と MCP の責務境界を整理する |
| #158 | OPEN | EgoPulse: マルチアカウント機構（1チャネル複数Bot）の実装 |

---
---

# 🔵 新レポ担当（endo-ly/egopulse）

以下は新レポで完結する作業。egograph レポへの変更は一切ない。

---

## 🔵 Step 1: GitHub に新レポジトリ作成

```bash
gh repo create endo-ly/egopulse --public --description "Self-hosted AI agent runtime (Rust/Tokio). TUI / Web UI / Discord / Telegram in a single binary."
```

---

## 🔵 Step 2: 履歴保持で egopulse/ を抽出

```bash
git clone https://github.com/endo-ly/egograph.git /tmp/egopulse-extract
cd /tmp/egopulse-extract

# egopulse/ をルートに昇格（306コミット履歴保持）
git filter-repo --subdirectory-filter egopulse/ --force

# リモートを新レポに変更
git remote set-url origin https://github.com/endo-ly/egopulse.git
```

**注意**: `--subdirectory-filter` により egopulse/ 内のファイルがルートに展開される。
`src/`, `Cargo.toml`, `build.rs`, `web/`, `README.md`, `THIRD_PARTY_NOTICES.md`, `egopulse.config.example.yaml` が配置される。

---

## 🔵 Step 3: ドキュメント・CI・スクリプト・Claude設定を追加

egograph レポ（`/root/workspace/ego-graph`）から新レポ（`/tmp/egopulse-extract`）にコピー。

```bash
# ドキュメント
cp -r /root/workspace/ego-graph/docs/30.egopulse/* /tmp/egopulse-extract/docs/
mkdir -p /tmp/egopulse-extract/docs/knowledge
cp /root/workspace/ego-graph/docs/70.knowledge/system_prompt_design.md /tmp/egopulse-extract/docs/knowledge/system-prompt-design.md
cp /root/workspace/ego-graph/docs/50.deploy/egopulse.md /tmp/egopulse-extract/docs/deploy.md

# CI
mkdir -p /tmp/egopulse-extract/.github/workflows
cp /root/workspace/ego-graph/.github/workflows/ci-egopulse.yml /tmp/egopulse-extract/.github/workflows/ci.yml
cp /root/workspace/ego-graph/.github/workflows/release-egopulse.yml /tmp/egopulse-extract/.github/workflows/release.yml

# インストールスクリプト
mkdir -p /tmp/egopulse-extract/scripts
cp /root/workspace/ego-graph/scripts/install-egopulse.sh /tmp/egopulse-extract/scripts/install.sh

# Claude設定
mkdir -p /tmp/egopulse-extract/.claude/agents
mkdir -p /tmp/egopulse-extract/.claude/commands
mkdir -p /tmp/egopulse-extract/.claude/rules

cp /root/workspace/ego-graph/.claude/agents/*.md /tmp/egopulse-extract/.claude/agents/
cp /root/workspace/ego-graph/.claude/commands/*.md /tmp/egopulse-extract/.claude/commands/
cp /root/workspace/ego-graph/.claude/rules/rust-best-practices.md /tmp/egopulse-extract/.claude/rules/
cp /root/workspace/ego-graph/.claude/rules/react-best-practices.md /tmp/egopulse-extract/.claude/rules/

# Claude Skills
mkdir -p /tmp/egopulse-extract/.claude/skills
for skill in brainstorming github-raw-fetch implementation-plan pr-review-back-workflow pr-review-extraction requirements-definition tmux-api-debug worktree-create agent-tool-test; do
  cp -r /root/workspace/ego-graph/.claude/skills/$skill /tmp/egopulse-extract/.claude/skills/
done
```

### コミット

`chore: add docs, CI, scripts, and Claude config from egograph monorepo`

---

## 🔵 Step 4: 参照を更新

| ファイル | 変更内容 |
|---|---|
| `README.md` | リンク先を `../docs/30.egopulse/xxx.md` → `./docs/xxx.md` に変更。インストールURLを `endo-ly/egopulse` に変更 |
| `scripts/install.sh` | `REPO="endo-ly/egograph"` → `REPO="endo-ly/egopulse"` |
| `.github/workflows/ci.yml` | `paths` フィルタから `egopulse/**` プレフィックスを削除。`Cargo.toml` 参照パスを修正 |
| `.github/workflows/release.yml` | `egopulse/Cargo.toml` → `Cargo.toml`。`egopulse/web/` → `web/`。リポジトリ参照を更新 |
| `docs/deploy.md` | `endo-ly/egograph` → `endo-ly/egopulse`。ソースビルド手順の `cd egograph` → `cd egopulse` |
| `.claude/skills/*/SKILL.md` | `endo-ly/egograph` 参照があれば `endo-ly/egopulse` に更新 |

### コミット

`chore: update references to endo-ly/egopulse`

---

## 🔵 Step 5: .gitignore と AGENTS.md を作成

### .gitignore

```gitignore
# Rust
/target/
**/*.rs.bk

# Node
web/node_modules/
web/dist/

# OS
.DS_Store

# IDE
.idea/
.vscode/
*.swp

# Local runtime data
.egopulse/
*.db
```

### AGENTS.md

Rust単体プロジェクト用に最適化:
- 開発コマンド（cargo fmt, check, clippy, test）
- WebUI開発コマンド（npm）
- コーディング規約（AGENTS.md の Rust 関連部分を抽出）
- セキュリティ（.env 読み取り禁止など）
- Claude設定（.claude/ の構成説明）

### コミット

`chore: add .gitignore and AGENTS.md`

---

## 🔵 Step 6: push して動作確認

```bash
cd /tmp/egopulse-extract
git push -u origin main
git push origin --tags

# 動作確認
cargo fmt --check
cargo check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

### 新レポのコミット分割（全4コミット）

1. `chore: initial commit with git history from egograph` — filter-repo push
2. `chore: add docs, CI, scripts, and Claude config from egograph monorepo` — ドキュメント・CI・スクリプト・Claude設定追加
3. `chore: update references to endo-ly/egopulse` — README・スクリプト・CI・Claude内のURL更新
4. `chore: add .gitignore and AGENTS.md` — プロジェクト設定

---
---

# 🟠 元レポ担当（endo-ly/egograph）

以下は egograph レポでのみ行う作業。新レポへの影響は一切ない。
**前提**: 🔵新レポ担当の Step 6（push）が完了していること。

---

## 🟠 Step 1: WT作成

```bash
cd /root/workspace/ego-graph
git worktree add ../wt-extract-egopulse -b chore/extract-egopulse
cd ../wt-extract-egopulse
```

---

## 🟠 Step 2: ファイル削除

```bash
# ソース・設定
rm -rf egopulse/
rm Cargo.toml Cargo.lock

# ドキュメント
rm -rf docs/30.egopulse/
rm docs/50.deploy/egopulse.md
rm docs/70.knowledge/system_prompt_design.md

# CI
rm .github/workflows/ci-egopulse.yml
rm .github/workflows/release-egopulse.yml

# スクリプト
rm scripts/install-egopulse.sh
```

### コミット

`chore: remove egopulse source, docs, CI workflows and install script`

---

## 🟠 Step 3: 参照更新

| ファイル | 変更内容 |
|---|---|
| `README.md` | Quick Start の EgoPulse セクションを「別レポ → [endo-ly/egopulse](https://github.com/endo-ly/egopulse)」に変更。Features の EgoPulse ブロックを「関連リポジトリ」セクションに移動。Current Status テーブルから EgoPulse 行を削除 |
| `AGENTS.md` | プロジェクトコンセプトから「エージェント層（EgoPulse）」の記述を別レポ参照に変更。アーキテクチャセクションから egopulse を削除。開発コマンドから EgoPulse セクションを削除。デバッグシナリオから egopulse 関連を削除 |
| `CLAUDE.md` | egopulse 関連の記述があれば削除 |
| `docs/CONCEPT.md` | "Agent Runtime — EgoPulse" 節を「独立リポジトリ → [endo-ly/egopulse](https://github.com/endo-ly/egopulse)」に変更 |
| `docs/10.architecture/system-architecture.md` | 1.1 構成要素テーブルから EgoPulse 行を削除。1.2 モノレポ構成から egopulse/ を削除。2.3 EgoPulse 節を削除。3.4 EgoPulse 節を削除。CI/CD・セキュリティ・ステータステーブルから egopulse 行を削除 |
| `docs/10.architecture/README.md` | EgoPulse リンクを別レポ参照に変更 |
| `docs/assets/readme/architecture.prompt.md` | Layer 4（EgoPulse）の記述を削除し、3層構成に変更 |

### コミット

`docs: update references to egopulse as external repository`

---

## 🟠 Step 4: 動作確認 → push → PR作成

```bash
# 動作確認
cd /root/workspace/ego-graph/../wt-extract-egopulse
uv sync
uv run pytest
uv run ruff check .

# リンク切れチェック: egopulse 参照が意図せず残っていないか
rg -l "egopulse" docs/ README.md AGENTS.md

# push → PR作成
git push -u origin chore/extract-egopulse
gh pr create --title "chore: extract egopulse to separate repository" --body "..."
```

### 元レポのコミット分割（全2コミット）

1. `chore: remove egopulse source, docs, CI workflows and install script` — ファイル一括削除
2. `docs: update references to egopulse as external repository` — README, AGENTS.md, docs/ の参照更新

---
---

# ⚪ 共通作業（両方完了後）

新レポ・元レポの両方のPRがマージされた後に実施。

---

## ⚪ Step 1: Issue移行（全14件）

```bash
# Closed Issues
gh issue transfer 96 endo-ly/egopulse
gh issue transfer 97 endo-ly/egopulse
gh issue transfer 98 endo-ly/egopulse
gh issue transfer 102 endo-ly/egopulse
gh issue transfer 104 endo-ly/egopulse
gh issue transfer 123 endo-ly/egopulse
gh issue transfer 135 endo-ly/egopulse
gh issue transfer 136 endo-ly/egopulse
gh issue transfer 137 endo-ly/egopulse
gh issue transfer 138 endo-ly/egopulse
gh issue transfer 155 endo-ly/egopulse
gh issue transfer 156 endo-ly/egopulse
gh issue transfer 157 endo-ly/egopulse

# Open Issues
gh issue transfer 158 endo-ly/egopulse
```

**注意**: `gh issue transfer` は open/closed 問わず移転可能。移転後は元レポで自動クローズされ、新レポに移動される。

---

## ⚪ Step 2: WT後片付け

```bash
cd /root/workspace/ego-graph
git worktree remove ../wt-extract-egopulse
git branch -d chore/extract-egopulse
```

---
---

# 依存関係マップ

```
🔵 新レポ担当                         🟠 元レポ担当
━━━━━━━━━━━━━━━━━━                    ━━━━━━━━━━━━━━━━

Step 1: レポ作成
    ↓
Step 2: filter-repo
    ↓
Step 3: ファイル追加
    ↓
Step 4: 参照更新
    ↓
Step 5: gitignore等
    ↓
Step 6: push+確認
    ↓
    ╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍
    ↓ （push完了が前提）               Step 1: WT作成
                                         ↓
                                       Step 2: ファイル削除
                                         ↓
                                       Step 3: 参照更新
                                         ↓
                                       Step 4: push+確認+PR

⚪ 共通（両方のPRマージ後）
━━━━━━━━━━━━━━━━━━━━━━━

Step 1: Issue移行
    ↓
Step 2: WT後片付け
```

---

## 新レポの最終構造

```
egopulse/
├── .claude/
│   ├── agents/                ← 汎用エージェント (3ファイル)
│   ├── commands/              ← 汎用コマンド (10ファイル)
│   ├── rules/
│   │   ├── rust-best-practices.md
│   │   └── react-best-practices.md
│   └── skills/                ← 汎用スキル (8個)
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
├── docs/
│   ├── commands.md
│   ├── config.md
│   ├── db.md
│   ├── directory.md
│   ├── mcp.md
│   ├── security.md
│   ├── session-lifecycle.md
│   ├── system-prompt.md
│   ├── tools.md
│   ├── microclaw-reference/
│   ├── deploy.md
│   └── knowledge/
│       └── system-prompt-design.md
├── scripts/
│   └── install.sh
├── src/                        ← (filter-repoでルートに展開済み)
├── web/                        ← (同上)
├── Cargo.toml
├── build.rs
├── README.md                   ← (内容はStep 4で更新)
├── AGENTS.md                   ← 新規作成 (Step 5)
├── .gitignore                  ← 新規作成 (Step 5)
├── egopulse.config.example.yaml
└── THIRD_PARTY_NOTICES.md
```

---

## 工数見積もり

| 担当 | Step | 内容 | 見積もり |
|---|---|---|---|
| 🔵 | Step 1 | GitHub新レポ作成 | ~5行 |
| 🔵 | Step 2 | git filter-repo で抽出 | ~10行（コマンド） |
| 🔵 | Step 3 | ファイルコピー + Claude設定 | ~30ファイル |
| 🔵 | Step 4 | 参照更新 | ~100行の編集 |
| 🔵 | Step 5 | .gitignore + AGENTS.md | ~150行の新規 |
| 🔵 | Step 6 | push + 動作確認 | ~15行 |
| 🟠 | Step 1 | WT作成 | ~5行 |
| 🟠 | Step 2 | ファイル削除 | ~10行 |
| 🟠 | Step 3 | 参照更新 | ~250行の編集 |
| 🟠 | Step 4 | 動作確認 + push + PR | ~15行 |
| ⚪ | Step 1 | Issue移行（14件） | ~15行 |
| ⚪ | Step 2 | WT後片付け | ~5行 |
| **合計** | | | **~580行 + ファイル移動** |
