# YouTube 視聴履歴収集セットアップガイド

EgoGraph の YouTube 視聴履歴収集システムは、**Google MyActivity** からのスクレイピングと **YouTube Data API v3** を組み合わせることで、高精度かつ詳細な視聴ログを収集・保存します。

本ガイドでは、このシステムのセットアップ手順と運用方法を説明します。

## 1. 概要

### アーキテクチャ
- **Source 1: Google MyActivity**: 視聴日時、動画ID、タイトルを取得 (Playwright / Cookie認証)
- **Source 2: YouTube Data API v3**: 動画の長さ、カテゴリ、タグなどのメタデータを取得 (API Key)
- **Destination: Cloudflare R2**: Parquet形式 (Hive-style partitioning) で保存

### 必要なクレデンシャル
1. **YouTube Data API v3 Key**: メタデータ取得用
2. **Google Account Cookies**: MyActivity アクセス用 (GitHub Actions Secrets に JSON 形式で保存)

---

## 2. セットアップ手順

### Step 1: YouTube Data API v3 APIキーの取得

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス。
2. プロジェクトを作成または選択。
3. "APIs & Services" > "Library" から "YouTube Data API v3" を検索し有効化。
4. "Credentials" から "Create Credentials" > "API Key" を選択。
5. 作成されたキーを保存 (後で使用)。

### Step 2: Google Cookie のエクスポート

MyActivity にアクセスするための Cookie をブラウザから抽出します。専用のスクリプトを用意しています。

```bash
# 依存関係のインストール (Playwright ブラウザ含む)
uv sync
uv run playwright install chromium

# アカウント1の Cookie エクスポート
uv run python egograph/pipelines/sources/google_activity/scripts/export_cookies.py --account account1

# (オプション) アカウント2がある場合
uv run python egograph/pipelines/sources/google_activity/scripts/export_cookies.py --account account2
```

スクリプトを実行するとブラウザが起動します：
1. Google アカウントにログインしてください。
2. ログイン完了後、ターミナルに戻り Enter キーを押します。
3. `cookies_account1.json` というファイルが生成されます。

### Step 3: GitHub Secrets の設定

GitHub リポジトリの Settings > Secrets and variables > Actions に以下の Secret を追加します。

| Secret名 | 値の内容 |
|----------|---------|
| `YOUTUBE_API_KEY` | Step 1 で取得した API キー |
| `GOOGLE_COOKIE_ACCOUNT1` | Step 2 で生成した `cookies_account1.json` の中身 (Raw JSON) |
| `GOOGLE_COOKIE_ACCOUNT2` | (任意) `cookies_account2.json` の中身 |

※ `R2_*` 関連の Secret は既に設定済みであることを前提とします。

### Step 4: 環境変数の設定 (ローカル開発用)

ローカルで実行する場合は、`.env` ファイルに以下を追加します。

```env
# YouTube Data API
YOUTUBE_API_KEY=your_api_key_here

# Google Cookies (ローカルパスまたはJSON文字列)
# ローカル開発時はファイルパスを指定すると便利です
GOOGLE_COOKIE_ACCOUNT1=./cookies_account1.json
```

---

## 3. 実行と運用

### 手動実行 (ローカル)

```bash
uv run python -m pipelines.sources.google_activity.main
```

### 自動実行 (GitHub Actions)

ワークフロー: `.github/workflows/job-ingest-google-youtube.yml`

- **スケジュール**: 毎日 04:00 (UTC)
- **トリガー**: `egograph/pipelines/sources/google_activity/**` の変更時にも実行
- **動作**: 
  - 設定された全アカウント (`account1`, `account2`...) を順次処理
  - エラー発生時も他のアカウントの処理は継続 (Isolation)

### データの確認 (R2)

収集されたデータは以下のパスに保存されます。

- **視聴履歴 (Parquet)**: `s3://egograph/events/youtube/watch_history/year={YYYY}/month={MM:02d}/{uuid}.parquet`
- **状態ファイル (JSON)**: `s3://egograph/state/youtube_{account_id}_state.json`

### トラブルシューティング

**Q: "Authentication failed" エラーが出る**
A: Cookie の有効期限が切れています。Step 2 の手順で Cookie を再取得し、GitHub Secrets を更新してください。

**Q: "QuotaExceededError" エラーが出る**
A: YouTube Data API の1日あたりの割り当て (10,000 units) を使い切りました。翌日 (Pacific Time 0:00) にリセットされます。
