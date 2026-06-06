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
2. **Google Account Cookies**: MyActivity アクセス用 (`egograph/pipelines/.env` に JSON 文字列またはファイルパスで保存)

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

### Step 3: `egograph/pipelines/.env` の設定

`egograph/pipelines/.env.example` をコピーして `egograph/pipelines/.env` を作成し、
YouTube Data API key と Cookie を設定する。

| 環境変数名 | 値の内容 |
|------------|---------|
| `YOUTUBE_API_KEY` | Step 1 で取得した API キー |
| `GOOGLE_COOKIE_ACCOUNT1` | Step 2 で生成した `cookies_account1.json` のパス、または JSON 文字列 |
| `GOOGLE_COOKIE_ACCOUNT2` | (任意) `cookies_account2.json` のパス、または JSON 文字列 |

※ `R2_*` も同じ `egograph/pipelines/.env` に設定する。

### Step 4: 手動実行

`egograph/pipelines/.env` を配置したうえで、ローカルでは source module を直接実行できる。

```bash
cp egograph/pipelines/.env.example egograph/pipelines/.env
uv run python -m pipelines.sources.google_activity.main
```

---

## 3. 実行と運用

### 手動実行 (ローカル)

```bash
uv run python -m pipelines.sources.google_activity.main
```

### 自動実行 (Pipelines Service)

ワークフロー: `google_activity_ingest_workflow`

- **実行基盤**: `egograph/pipelines` 常駐サービスの APScheduler
- **スケジュール**: `0 14 * * *` (14:00 UTC = 23:00 JST)
- **動作**: 
  - 設定された全アカウント (`account1`, `account2`...) を順次処理
  - エラー発生時も他のアカウントの処理は継続 (Isolation)

### データの確認 (R2)

収集されたデータは以下のパスに保存されます。

- **視聴履歴 (Parquet)**: `s3://egograph/events/youtube/watch_history/year={YYYY}/month={MM:02d}/{uuid}.parquet`
- **状態ファイル (JSON)**: `s3://egograph/state/youtube_{account_id}_state.json`

### トラブルシューティング

**Q: "Authentication failed" エラーが出る**
A: Cookie の有効期限が切れています。Step 2 の手順で Cookie を再取得し、`egograph/pipelines/.env` を更新して `egograph-pipelines.service` を再起動してください。

**Q: "QuotaExceededError" エラーが出る**
A: YouTube Data API の1日あたりの割り当て (10,000 units) を使い切りました。翌日 (Pacific Time 0:00) にリセットされます。
