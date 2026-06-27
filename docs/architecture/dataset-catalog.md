# Dataset Catalog

> 最終更新: 2026-06-25

Dataset Catalog は、Pipelines が書き込む Parquet dataset と Backend が読み取る Parquet dataset の共有契約である。

## 目的

EgoGraph の中核境界は「Pipelines が R2 に Parquet を生成し、Backend が DuckDB で読む」ことである。この境界に必要な path、partition、dedupe key、time column、compaction strategy を `dataset_catalog` に集約する。

これにより、データソース追加時に write path と read path のどちらか片方だけを更新して壊れる状態を避ける。

## 配置

```text
egograph/dataset_catalog/
├── __init__.py
└── catalog.py
```

Python workspace では `backend` と `pipelines` の両方から `dataset_catalog` として import する。

## Catalog が持つもの

| 項目 | 役割 |
|---|---|
| `dataset_id` | 安定した論理ID。例: `spotify.plays` |
| `provider` | データソース単位。例: `spotify` |
| `domain` | R2 domain。`events` または `master` |
| `path` | domain 配下の canonical path |
| `partition_policy` | `monthly` / `snapshot` / `recursive` |
| `compaction_strategy` | `append_dedupe` / `range_replace` / `snapshot_upsert` / `none` |
| `time_column` | 期間抽出・partition 判定の基準列（events なら event time、master なら updated_at） |
| `dedupe_key` | append-dedupe compaction の一意キー |
| `sort_key` | 重複時に残す行を決める順序列。dedupe_key と従属関係にある値は決定性を失うため注意 |
| `snapshot_file_name` | snapshot dataset の固定ファイル名 |

## source と compacted の path 非対称性

`DatasetDefinition` の path 系メソッドは source / compacted で domain 扱いが異なる。

- `source_prefix(root)` / `source_partition_prefix(root, ...)` / `source_glob(root)`
  - source 側は events / master で root が分かれている（`events_path` / `master_path`）。
  - よって戻り値に domain は含まない。root の選択は `source_root(events_path, master_path)` で行う。
- `compacted_prefix(compacted_root)` / `compacted_partition_key(compacted_root, ...)`
  - compacted 側は単一 root 配下に domain ごとの階層を持つ。
  - よって戻り値に `{domain}/` を含む。

## 使用箇所

### Backend

- `backend.infrastructure.database.parquet_paths`
  - `DatasetDefinition` から compacted local path / R2 path / glob を組み立てる
- `backend.infrastructure.database.*_queries`
  - 読み取り対象 dataset を catalog 定義から参照する

### Pipelines

- `pipelines.sources.common.compaction`
  - `DatasetDefinition` から compacted key を組み立てる
- `pipelines.sources.*.pipeline`
  - provider ごとの monthly compaction 対象を `monthly_compaction_datasets()` から取得する
- `pipelines.sources.google_health.writer`
  - range replace 対象 dataset と date column を catalog から参照する

## 追加ルール

新しい Parquet dataset を追加する場合は、最初に catalog へ `DatasetDefinition` を追加する。

その後、以下を同じ PR で更新する。

1. Pipelines の保存・compaction 実装
2. Backend の read path / query 実装
3. `docs/data-sources/` の該当データソース文書
4. Catalog と path resolver の unit test

dataset path や dedupe key を各 source module に直接重複定義しない。source 固有の処理手順は source module に残してよいが、dataset の物理契約は catalog を正とする。
