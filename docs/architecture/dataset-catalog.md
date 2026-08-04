# Dataset Catalog

> 最終更新: 2026-08-04

Dataset Catalog は、Pipelines が書き込む Parquet dataset と Backend が読み取る Parquet dataset の共有契約である。

## 目的

EgoGraph の中核境界は「Pipelines が R2 に Parquet を生成し、Backend が DuckDB で読む」ことである。この境界に必要な path、partition、dedupe key、time column、compaction strategy を `dataset_catalog` に集約する。

これにより、データソース追加時に write path と read path のどちらか片方だけを更新して壊れる状態を避ける。

## 配置

```text
egograph/dataset_catalog/
├── __init__.py
├── catalog.py          # DatasetDefinition / 定義レジストリ
├── canonical.py        # canonical type 変換・型差分判定
└── validation.py       # 保存前の schema 検証
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
| `schema_version` | Parquet schema 契約の version。`required_columns` / `column_types` を変更するたびにインクリメント |
| `required_columns` | Parquet に必ず存在する必須カラム名 |
| `column_types` | 必須カラムごとの canonical type（key 集合は `required_columns` と完全一致。定義は `__post_init__` で検証） |

## Schema 契約（Parquet）

### canonical type

`column_types` の値は、DuckDB / Parquet の型名表記（`TIMESTAMP WITH TIME ZONE`、`VARCHAR`、`timestamp[us, tz=UTC]` など）に依存しない canonical type 文字列で定義する。

| canonical | 該当 Arrow 型の例 | 該当 DuckDB 型の例 |
|---|---|---|
| `string` | `string` | `VARCHAR` |
| `integer` | `int64` | `BIGINT` |
| `float` | `double` | `DOUBLE` |
| `boolean` | `bool` | `BOOLEAN` |
| `timestamp` | `timestamp[us, tz=UTC]` | `TIMESTAMP WITH TIME ZONE` |
| `date` | `date32` | `DATE` |
| `list<string>` | `list<item: string>` | `VARCHAR[]` |
| `null` | `null` | （全カラムが null の場合） |

`egograph/dataset_catalog/canonical.py` の `arrow_type_to_canonical()` / `duckdb_type_to_canonical()` で各エンジンの型名を canonical に正規化する。比較時に許容される差分は `type_mismatch()` に集約する:

- 実型が `null`（未投入カラム）はどの期待型にも許容
- 整数カラムの null は `int64`（arrow の nullable）で表現する。pandas の float 拡張（int + None → float64）は **integer 契約として拒否**する。保存前に `astype("Int64")` 等で nullable 整数へ変換しておくこと

### validation 規則

- `required_columns` が空または重複 → `ValueError`（`invalid_schema: ...`）
- `column_types` の key が `required_columns` に含まれない → `ValueError`（`invalid_schema: ...`）。key の typo による契約ドリフトを構造的に防ぐ
- `column_types` が `required_columns` を網羅しない（型未定義の必須カラム）→ `ValueError`（`invalid_schema: required_column_type_missing: ...`）
- 保存時（アップロード前）の検証は `egograph/dataset_catalog/validation.py` が担う
  - `validate_required_columns(definition, columns)`: 必須カラムの存在確認
  - `validate_parquet_bytes(definition, data)`: バイト列から schema を取得し、必須カラムの存在確認と型検証を一括実施

### 保存時の検証フロー

各 source storage は「必須カラム確認 → Parquet バイト列生成 → バイト列から型検証 → アップロード」の順で保存する。アップロード後の読み直しは行わない。compaction 出力（`compacted/` 配下）も同様に、アップロード前に `validate_required_columns` + `validate_parquet_bytes` を適用する。

compaction は source Parquet の読み込み時に、catalog で `timestamp` と定義された
カラムを UTC aware datetime へ正規化する。過去世代で日時が文字列として保存されて
いても、compacted Parquet は canonical schema で生成される。不正な日時は保存前に
エラーとして扱う。

- 空データ（保存対象なし）は検証をスキップし、既存の `None` / `failed=0` 契約を維持する
- 検証失敗は `ValueError`（`invalid_schema: ...`）として各 storage の既存の保存失敗契約へ変換する
  - spotify / browser_history / youtube: 保存関数が `None` を返し、pipeline 側で run 失敗扱い
  - github: `failed` 件数へ計上（`save_*_with_stats`）または保存失敗として repo 単位で失敗扱い
  - google_health: `save_events` / `compact_range` が `ValueError` を伝播し、workflow 側で data type を FAILED にする

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
  - source Parquet の timestamp カラムを catalog 契約へ正規化する
- `pipelines.sources.*.pipeline`
  - provider ごとの monthly compaction 対象を `monthly_compaction_datasets()` から取得する
- `pipelines.sources.google_health.writer`
  - range replace 対象 dataset と date column を catalog から参照する
- `pipelines.sources.*.storage` / `writer`
  - 保存前に `validate_required_columns` / `validate_parquet_bytes` で契約検証を実行する

### テスト

- `egograph/backend/tests/unit/test_dataset_catalog.py`
  - カタログ定義自体の validation 規則を検証する
- `egograph/backend/tests/unit/test_dataset_contracts.py`
  - 既存の手書き fixture Parquet が required columns / canonical type 契約を満たすことを検証する
  - fixture はカタログから自動生成しない（カタログと fixture が同時にドリフトして循環検証になるのを避けるため）
- `egograph/pipelines/tests/unit/test_schema_validation.py`
  - 保存前検証の必須カラム・型判定を検証する

## 追加ルール

新しい Parquet dataset を追加する場合は、最初に catalog へ `DatasetDefinition` を追加する。

その後、以下を同じ PR で更新する。

1. Pipelines の保存・compaction 実装
2. Backend の read path / query 実装
3. `docs/data-sources/` の該当データソース文書
4. Catalog と path resolver の unit test

dataset path や dedupe key を各 source module に直接重複定義しない。source 固有の処理手順は source module に残してよいが、dataset の物理契約は catalog を正とする。

`required_columns` / `column_types` を変更する場合は `schema_version` をインクリメントし、保存時の検証が新契約を満たすよう Pipelines の transform / storage を同じ PR で更新する。
