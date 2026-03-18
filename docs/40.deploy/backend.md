# Backend Deploy (LXC + Tailscale)

本番バックエンドを Proxmox LXC (Ubuntu) にデプロイする手順。
Tailscale HTTPS を使用し、リバースプロキシは省略する。
ローカルファースト運用のため、外部公開は前提にしない。

## 1. LXC 構成

軽量構成でも安定稼働できるよう、LLM推論は外部API前提でCPU/メモリを抑える。
この構成は個人運用の常駐APIを想定したバランス。

- Name: `egograph-prod`
- OS: Ubuntu 24.04 LTS
- vCPU: 2 cores
- Memory: 3072 MB
- Swap: 1024 MB
- Disk: 40GB

## 2. 初期セットアップ

Ubuntuの標準パッケージでGitとcurlを準備する。
以降の手順はすべてLXC内で実行する。

LXC 内で実行:

```bash
sudo apt update
sudo apt install -y git curl
```

### 2.1 Tailscale

Tailscaleを導入し、Tailnet内にのみサービスを公開する。
`tailscale serve` によりHTTPS終端を行うため、Nginx等は不要。

Proxmox LXC では `/dev/net/tun` が無効な場合がある。
`tailscaled` が起動しない場合はホスト側でTUNを有効化する。

ホスト側（Proxmox）で実行:

```bash
echo "lxc.cgroup2.devices.allow: c 10:200 rwm" >> /etc/pve/lxc/<CTID>.conf
echo "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file" >> /etc/pve/lxc/<CTID>.conf
```

必要なら `lxc.apparmor.profile: unconfined` も追記し、LXCを再起動。

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
sudo tailscale up --hostname=egograph-prod
```

HTTPS は `tailscale serve` を使用:

```bash
sudo tailscale serve --bg http://127.0.0.1:8000
```

接続URLは `https://<hostname>.<tailnet>.ts.net/`。
`tailscale status` でホスト名とIPを確認できる。
`tailscale serve status` で公開設定が反映されているか確認する。

### 2.2 uv

Pythonの依存管理は `uv` を使用する。
workspace構成のため、ルートで `uv sync` を実行する。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`uv` は `~/.local/bin` に入るため、PATHを通しておく。
ただし systemd は `~/.profile` を読まないため、サービス側にもPATHを明示する。

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> /root/.profile
source /root/.profile
```

## 3. デプロイ配置

パスを固定することでsystemdやCIのスクリプトがシンプルになる。
`.env` はLXC内に置き、SecretsはGitHubに載せない運用を想定。

推奨パス:

- Repo: `/opt/egograph/repo`
- `.env`: `/opt/egograph/repo/.env`

```bash
sudo mkdir -p /opt/egograph
sudo chown -R root:root /opt/egograph
cd /opt/egograph
git clone https://github.com/endo-ava/ego-graph repo
```

## 4. 依存同期

`uv.lock` に固定された依存を同期する。
更新時も同じコマンドでよい。

```bash
cd /opt/egograph/repo
uv sync --all-packages
```

### 4.1 DuckDB 拡張のインストール

**httpfs拡張とは？**

DuckDBは標準ではローカルファイルしか読み込めません。
`httpfs`（HTTP File System）拡張を入れると、以下が可能になります：

- HTTP/HTTPS経由でリモートのファイルを読み込む
- S3互換ストレージ（R2、AWS S3、MinIOなど）に直接アクセスする
- compacted mirror 未同期時に R2 compacted parquet へフォールバックできる

```bash
uv run python -c "import duckdb; conn = duckdb.connect(); conn.execute('INSTALL httpfs;'); conn.execute('LOAD httpfs;'); print('httpfs installed successfully')"
```

インストール済み拡張の確認:

```bash
uv run python -c "import duckdb; conn = duckdb.connect(); print(conn.execute(\"SELECT * FROM duckdb_extensions() WHERE extension_name = 'httpfs'\").fetchdf())"
```

## 5. systemd 常駐

systemdで常駐化し、障害時は自動復旧させる。
`WorkingDirectory` と `.env` のパスは固定で運用する。
backend は local mirror を優先して compacted parquet を読み込む。
起動前に compacted mirror を同期するため、`ExecStartPre` を追加する。
`/etc/systemd/system/egograph-backend.service`:

作成と編集:

```bash
sudo touch /etc/systemd/system/egograph-backend.service
sudo nano /etc/systemd/system/egograph-backend.service
```

```ini
[Unit]
Description=EgoGraph Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/egograph/repo
EnvironmentFile=/opt/egograph/repo/backend/.env
Environment=USE_ENV_FILE=false
Environment=LOCAL_PARQUET_ROOT=/opt/egograph/data/parquet
Environment=PARQUET_SOURCE_MODE=prefer_local
ExecStartPre=/root/.local/bin/uv run python backend/scripts/sync_compacted_parquet.py --root /opt/egograph/data/parquet
ExecStart=/root/.local/bin/uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
User=root
Group=root

[Install]
WantedBy=multi-user.target
```

起動前に `backend/.env` を作成

```bash
sudo nano /opt/egograph/repo/backend/.env
```

起動:

```bash
sudo systemctl daemon-reload
sudo systemctl enable egograph-backend
sudo systemctl start egograph-backend
sudo systemctl status egograph-backend
```

### 5.1 定期 sync

local mirror を追従させるため、cron か systemd timer で定期 sync を実行する。

```bash
*/30 * * * * cd /opt/egograph/repo && /root/.local/bin/uv run python backend/scripts/sync_compacted_parquet.py --root /opt/egograph/data/parquet
```

## 6. GitHub Actions で main をデプロイ

main への push をトリガーに本番へデプロイする。
ワークフローは `.github/workflows/deploy-backend.yml` を使用。

### 6.1 事前準備

- LXC に SSH 鍵を配置
- GitHub Secrets に以下を登録:
  - `TS_AUTHKEY` (Tailscale Auth Key)
  - `SSH_HOST` (egograph-prod の Tailscale FQDN)
  - `SSH_USER` (`root`)
  - `SSH_KEY` (deploy 用の秘密鍵)

### 6.2 GitHub Secrets の取得と登録

#### TS_AUTHKEY (Tailscale)

1. Tailscale 管理画面 (Admin Console) を開く
2. `Settings` → `Keys` で Auth Key を作成
3. 期限と再利用可否を設定し、生成されたキーをコピー

#### SSH_KEY (Deploy 用秘密鍵)

ローカルでデプロイ用の鍵を作成:

```bash
ssh-keygen -t ed25519 -C "egograph-deploy" -f ./egograph_deploy_key
```

LXC 側に公開鍵を配置:

```bash
ssh-copy-id -i ./egograph_deploy_key.pub root@<egograph-prod-tailnet-hostname>
```

#### Windows で既存鍵を使う場合

既に `~/.ssh/id_ed25519` があるなら再利用できる。
PowerShell でパスを確認:

```powershell
dir $env:USERPROFILE\.ssh
```

秘密鍵と公開鍵の中身を確認:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

公開鍵はLXCの `~/.ssh/authorized_keys` に追記する。

LXC側で追記:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "<公開鍵の1行>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

GitHub Secrets に登録するのは **秘密鍵の中身**。
公開鍵は **LXC側にだけ配置**する。

#### GitHub Secrets への登録

GitHub リポジトリの `Settings` → `Secrets and variables` → `Actions` で以下を追加:

- `TS_AUTHKEY`: Tailscale Auth Key
- `SSH_HOST`: 例 `egograph-prod.<tailnet>.ts.net`
- `SSH_USER`: `root`
- `SSH_KEY`: `egograph_deploy_key` の内容 (秘密鍵)

## 7. 変更フロー（手動）

CI を使わずに更新する場合:

```bash
cd /opt/egograph/repo
git fetch origin main
git reset --hard origin/main
uv sync
sudo systemctl restart egograph-backend
```

**注意**: `git reset --hard` はローカルの変更を破棄します。本番環境での直接変更は推奨しません。

## 8. VM + Docker でのデプロイ（補足）

将来的にVM上でDocker運用に切り替える場合の参考。
リポジトリ直下の `Dockerfile` を使用する。
各Pythonパッケージはuv workspaceで管理されているため、build contextはリポジトリ全体を指定する。

### 8.1 ビルド

```bash
docker build -t egograph-backend:latest .
```

### 8.2 起動

`.env` を同じディレクトリに置いて起動する。

```bash
docker run --env-file .env -p 8000:8000 egograph-backend:latest
```

### 8.3 HTTPS

Docker運用でもTailscaleを使う場合は、ホスト側で `tailscale serve` を使う。
コンテナ内でHTTPS終端は行わない。

## 9. Tailscale Serve 補足

### 9.1 概要

`tailscale serve` は Tailscale が提供するローカルサービス公開機能。
Tailnet 内のクライアントから安全にアクセスでき、TLS終端も自動で行われる。
リバースプロキシを置かずにHTTPS化できる点が大きな利点。

### 9.2 使い方の基本

- 背景実行（推奨）
  ```bash
  sudo tailscale serve --bg http://127.0.0.1:8000
  ```
- 状態確認
  ```bash
  sudo tailscale serve status
  ```
- 設定のリセット
  ```bash
  sudo tailscale serve reset
  ```

### 9.3 接続URL

アクセスURLは `https://<hostname>.<tailnet>.ts.net/`。
`tailscale status` でホスト名とTailnetドメインを確認できる。

### 9.4 使い分けの考え方

- **Tailscaleのみで閉じる運用**: `tailscale serve` だけで十分
- **公開Web化（インターネット公開）**: `tailscale funnel` を検討
- **既存のリバースプロキシと併用**: まずは `serve` で簡易確認 → 必要ならNginxに移行

### 9.5 よくある注意点

- `No serve config` が出る場合は、`serve` の設定が保存されていない
- `tailscaled` が起動していないと `serve` は機能しない
