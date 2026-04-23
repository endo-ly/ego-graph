# Pipelines Deploy (LXC + Tailscale)

本番 Pipelines Service を Proxmox LXC (Ubuntu) にデプロイする手順。

## 前提

- [backend.md](./backend.md) の §1〜4（LXC構成、Tailscale、uv、デプロイ配置、依存同期）が完了していること
- GitHub Secrets に `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `SSH_HOST`, `SSH_USER`, `SSH_KEY` が登録済みであること

## 1. systemd 常駐

ingest / compact / local mirror sync の定期実行と Browser History 受信 API は
`pipelines` が担当する。
backend は `repo` の兄弟 `data/parquet` に local mirror がなければ R2 compacted parquet
へフォールバックして起動できるため、`egograph-pipelines.service` への hard dependency は
設定しない。

内部の APScheduler が定期実行を担うため systemd timer は使わない。

`/etc/systemd/system/egograph-pipelines.service`:

```bash
sudo touch /etc/systemd/system/egograph-pipelines.service
sudo nano /etc/systemd/system/egograph-pipelines.service
```

```ini
[Unit]
Description=EgoGraph Pipelines Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/egograph/repo
EnvironmentFile=/opt/egograph/repo/egograph/pipelines/.env
Environment=USE_ENV_FILE=false
ExecStart=/root/.local/bin/uv run python -m pipelines.main serve --host 127.0.0.1 --port 8001
Restart=always
RestartSec=10
User=root
Group=root

[Install]
WantedBy=multi-user.target
```

### 環境変数

起動前に `egograph/pipelines/.env` を作成する。
`.env.example` はユーザー固有値を中心に載せており、
未記載のスケジューラ/バッチサイズ等はコード既定値を使う。

```bash
sudo cp /opt/egograph/repo/egograph/pipelines/.env.example /opt/egograph/repo/egograph/pipelines/.env
sudo nano /opt/egograph/repo/egograph/pipelines/.env
```

`PIPELINES_API_KEY` を必ず設定すること。
未設定なら `/v1/health` 以外の API リクエストは 500 エラーとなる。

### 起動確認

```bash
sudo systemctl daemon-reload
sudo systemctl enable egograph-pipelines
sudo systemctl start egograph-pipelines
sudo systemctl status egograph-pipelines
journalctl -u egograph-pipelines.service -n 100 --no-pager
```

## 2. 疎通確認

### API ヘルスチェック

```bash
curl http://127.0.0.1:8001/v1/health
# => {"status":"ok"}
```

### CLI で workflow / run 状態を確認

主要コマンドはエージェント運用しやすいよう `--json` 出力を使う。

```bash
cd /opt/egograph/repo
uv run python -m pipelines.main workflow list --json
uv run python -m pipelines.main run list --json
```

### Browser History 拡張機能

Browser History 拡張機能の送信先 `Server URL` は backend ではなく
`egograph-pipelines.service` 側の URL を設定する。

## 3. GitHub Actions で main をデプロイ

main への push をトリガーに本番へデプロイする。
ワークフローは `.github/workflows/deploy-pipelines.yml` を使用。

### トリガー条件

以下のパスに変更があった場合、main への push で自動デプロイされる：

- `egograph/pipelines/**`
- `pyproject.toml`
- `uv.lock`
- `.github/workflows/deploy-pipelines.yml`

手動実行も可能（workflow_dispatch）。

### デプロイフロー

1. テストジョブ: pytest で unit / integration / e2e を実行
2. デプロイジョブ: Tailscale VPN に接続 → SSH で本番サーバーにデプロイ
   - `git fetch` + `git reset --hard` で最新コードを取得
   - `uv sync --all-packages` で依存を同期
   - `systemctl restart egograph-pipelines` でサービス再起動
   - `/v1/health` でヘルスチェック（最大20秒）

### GitHub Secrets

Backend で使用するものと同じ Secrets を使用する。追加の登録は不要。

| Secret | 用途 |
|--------|------|
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth Client ID |
| `TS_OAUTH_SECRET` | Tailscale OAuth Secret |
| `SSH_HOST` | egograph-prod の Tailscale FQDN |
| `SSH_USER` | SSH ユーザー（`root`） |
| `SSH_KEY` | デプロイ用秘密鍵 |

## 4. 変更フロー（手動）

CI を使わずに更新する場合:

```bash
cd /opt/egograph/repo
git fetch origin main
git reset --hard origin/main
uv sync --all-packages
sudo systemctl restart egograph-pipelines
```

**注意**: `git reset --hard` はローカルの変更を破棄します。本番環境での直接変更は推奨しません。

## 5. 削除できる GitHub Secrets

`.github/workflows/job-ingest-*.yml` を削除したため、以下の ingest 専用 secrets は
GitHub Actions から参照されなくなる。
他用途で使っていなければ GitHub Secrets から削除し、
`/opt/egograph/repo/egograph/pipelines/.env` へ集約する。

| 削除候補 Secret | 移行先 `.env` キー |
| --------------- | ------------------- |
| `SPOTIFY_CLIENT_ID` | `SPOTIFY_CLIENT_ID` |
| `SPOTIFY_CLIENT_SECRET` | `SPOTIFY_CLIENT_SECRET` |
| `SPOTIFY_REFRESH_TOKEN` | `SPOTIFY_REFRESH_TOKEN` |
| `EGOGRAPH_GITHUB_PAT` | `GITHUB_PAT` |
| `EGOGRAPH_GITHUB_LOGIN` | `GITHUB_LOGIN` |
| `YOUTUBE_API_KEY` | `YOUTUBE_API_KEY` |
| `GOOGLE_COOKIE_ACCOUNT1` | `GOOGLE_COOKIE_ACCOUNT1` |
| `GOOGLE_COOKIE_ACCOUNT2` | `GOOGLE_COOKIE_ACCOUNT2` |
| `R2_ENDPOINT_URL` | `R2_ENDPOINT_URL` |
| `R2_ACCESS_KEY_ID` | `R2_ACCESS_KEY_ID` |
| `R2_SECRET_ACCESS_KEY` | `R2_SECRET_ACCESS_KEY` |
| `R2_BUCKET_NAME` | `R2_BUCKET_NAME` |
