---
name: r2-parquet-duckdb
description: Cloudflare R2 上の Parquet を DuckDB で直接調査する。backend の R2 設定を使って `events/.../*.parquet` や `compacted/.../*.parquet` をその場で件数確認、スキーマ確認、最新行確認、集計SQL実行したいときに使う。R2 の実データを確認したい、保存先を検証したい、取り込み結果を spot check したい、という依頼で使う。
---

# R2 Parquet DuckDB

R2 上の Parquet を DuckDB で直接読むためのスキル。`backend/.env` の R2 設定を `BackendConfig.from_env()` 経由で読み、毎回 `httpfs` や `CREATE SECRET` を手で書かずに調査を進める。

## Quick Start

最初はこの順で確認する。

1. データセットのパスを決める
2. `--describe` でスキーマを見る
3. `--count` と `--limit` で件数と最新行を見る
4. 必要なら `--sql` で集計する

基本コマンド:

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet' \
  --count \
  --limit 5
```

## Workflow

### 1. データセットを指定する

`--dataset` には bucket 配下の相対パスを渡す。先頭に `s3://{bucket}/` は不要。

例:

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet'
```

よく使う例:

- `events/browser_history/page_views/**/*.parquet`
- `compacted/events/spotify/plays/**/*.parquet`
- `events/youtube/watch_history/**/*.parquet`

### 2. スキーマと件数を見る

まずは `--describe` と `--count` を使う。

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet' \
  --describe \
  --count
```

### 3. 最新行を spot check する

既定では `SELECT * FROM dataset LIMIT n` を実行する。並び順が必要なときは `--sql` を使う。

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet' \
  --sql 'SELECT started_at_utc, ended_at_utc, visit_span_count, transition, url FROM dataset ORDER BY started_at_utc DESC LIMIT 10'
```

### 4. 集計SQLを投げる

スクリプト内で `dataset` という DuckDB view を作るので、SQL ではそれを参照する。

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet' \
  --sql 'SELECT transition, COUNT(*) AS cnt FROM dataset GROUP BY 1 ORDER BY cnt DESC'
```

## Investigation Patterns

保存確認では次の順が安定する。

1. `--count` で空でないことを確認する
2. `--describe` で列名の想定ズレがないか確認する
3. 最新 5-10 行を見る
4. 月別件数や `COUNT(*)`, `MAX(...)`, `GROUP BY` を追加する

browser history の例:

```bash
uv run python .claude/skills/r2-parquet-duckdb/scripts/query_r2_parquet.py \
  --dataset 'events/browser_history/page_views/**/*.parquet' \
  --sql 'SELECT year(started_at_utc) AS yy, month(started_at_utc) AS mm, COUNT(*) AS page_views, SUM(visit_span_count) AS raw_visits FROM dataset GROUP BY 1, 2 ORDER BY 1, 2'
```

raw / events / compacted の見分け:

- `raw/` は Parquet ではなく JSON。このスキルの対象外
- `events/` は通常の分析用 Parquet
- `compacted/` は月次 compact 後の Parquet

## Notes

- このスキルは `.env` を直接読まず、リポジトリの `BackendConfig.from_env()` に委譲する
- 調査結果を返すときは、件数、見たパス、代表行を一緒に伝える
- `No files found` は dataset パス違いのことが多い。まず prefix を見直す
- 列名は provider ごとに違うので、最初に `--describe` を使う
