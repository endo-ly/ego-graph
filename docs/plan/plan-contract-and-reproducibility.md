# 実装計画: データ契約の明確化とSQLite migration基盤

Howはあくまで参考であり、よりよい設計方針があれば各自で判断し採用する

## 目的

Pipelinesが生成するParquetとBackendが読むParquetのschema契約を既存Dataset Catalog上で明確にする。また、SQLiteのschema変更を安全に適用できるmigration基盤を整える。

この計画では、次の2つを扱う。

1. Dataset Catalogへのschema契約追加
2. SQLite migrationの一元管理

データ整合性のcursor更新方針を前提とし、schema検証の失敗が保存失敗としてcursor更新へ反映される状態を維持する。

workflow runへの実行時version記録、過去のworkflow定義を完全に保存して任意の古いコードで再実行する機能、データ品質ルールの汎用エンジン、Backend APIの自動生成は対象外とする。

## 現状と課題

### Dataset Catalog

現在の`DatasetDefinition`はdataset id、domain、path、partition policy、compaction strategy、time column、dedupe key、sort keyを持つ。一方で、Parquetに必要なカラム、型、nullable、schema versionはsource別transform、storage、Backend SQL、テストfixtureに分散している。

主な対象:

- `egograph/dataset_catalog/catalog.py`
- `egograph/backend/tests/unit/test_dataset_catalog.py`
- `egograph/pipelines/sources/*/transform.py`
- `egograph/pipelines/sources/spotify/storage.py`
- `egograph/pipelines/sources/github/storage.py`
- `egograph/pipelines/sources/browser_history/storage.py`
- `egograph/pipelines/sources/youtube/storage.py`
- `egograph/pipelines/sources/google_health/writer.py`
- `egograph/backend/infrastructure/database/*_queries.py`
- `egograph/backend/tests/conftest.py`
- `docs/architecture/dataset-catalog.md`
- `docs/architecture/data-strategy.md`

### SQLite schema管理

SQLite schemaは`CREATE TABLE IF NOT EXISTS`によるテーブル作成と、`google_health_sync_cursors`への列追加が`PRAGMA table_info`の列存在チェックで個別に管理されている。schema全体のversion履歴を追跡する仕組みがなく、将来の列追加・変更で既存DBと新規DBの初期化が二重管理になる。

既存のデプロイ済みDBには`google_health_sync_cursors`のPhase 2列が適用済みの状態があり、初期化処理はこの状態を壊さずに動作する必要がある。

主な対象:

- `egograph/pipelines/infrastructure/db/schema.py`
- `egograph/pipelines/tests/unit/test_schema.py`
- `egograph/pipelines/tests/unit/test_service.py`
- `docs/architecture/pipelines.md`

## 他の計画との関係

- Dataset Catalogのschema定義とSQLite migrationは、互いにコード依存がないため並行できる。
- Dataset Catalogのschema定義は、データ整合性・本番安全性の計画と並行できる。
- schema検証をPipelinesの保存処理へ接続する部分だけは、validatorの`ValueError`（`invalid_schema: ...`）を各storageの既存失敗契約（`None`、`failed > 0`、または既存の例外）へ変換する。GitHub cursorへ接続する場合だけ、state保存後に`RuntimeError`へ集約する契約を確認してから統合する。
- SQLite migrationは、他の2計画から独立して実装できる。
- `docs/architecture/data-strategy.md`や共通READMEを複数worktreeで編集しないよう、docs更新の担当を決める。

## 実装方針

### 1. Catalogは既存のPython定義を拡張する

新しい外部定義ファイルは追加せず、`DatasetDefinition`にschema情報を追加する。

最初に持つ情報は以下に限定する。

- `schema_version: int`
- `required_columns: tuple[str, ...]`
- `column_types: dict[str, str]`

nullable、説明文、機密度は全datasetで必要性を確認したうえで追加する。schema情報は保存形式を検証するための最小契約として扱い、変換処理やcompaction処理をCatalogへ移さない。

validation規則:

- `required_columns`が空または重複している場合は`ValueError`（`invalid_schema: ...`）
- `column_types`のkeyが`required_columns`に含まれない場合は`ValueError`（`invalid_schema: ...`）。keyのtypoによる契約のドリフトを構造的に防ぐ
- `column_types`が`required_columns`を網羅しない場合も`ValueError`（`invalid_schema: required_column_type_missing: ...`）。型未定義の必須カラムを許さない（`set(column_types) == set(required_columns)`）
- `time_column` / `dedupe_key` / `sort_key`が`required_columns`に含まれない場合は`ValueError`（`invalid_schema: <role>_not_required: ...`）。compactionの操作キーが物理カラムとして存在することを保証する
- `schema_version`は`required_columns` / `column_types`を変更するたびにインクリメントする。変更のない再デプロイでは据え置く

### 2. 保存側で最低限のschema検証を行う

保存前に`DatasetDefinition`の必須カラムが存在することを検証する。型検証はpandasの内部dtypeに依存せず、Parquetバイト列を生成した後・アップロード前にバイト列からschemaを取得して行う。アップロード後の読み直しは行わない（無駄なアップロードと部分書き込みを防ぐ）。

検証の流れは「必須カラム確認 → Parquetバイト列生成 → バイト列から型検証 → アップロード」の順とする。

空データ（保存対象なし）は検証をスキップし、既存の`None` / `failed=0`契約を維持する。

検証失敗時は`ValueError`（`invalid_schema: ...`）をstorageの既存の保存失敗契約へ変換し、データ整合性のcursor更新方針と矛盾しないようにする。GitHub ingestではorchestratorがstateを安全に保存した後に`RuntimeError`を送出し、in-process runを失敗扱いにする。

### 3. canonical typeは正規化関数を共有する

`column_types`の値は、DuckDB/Parquetで確認可能なcanonical type文字列として定義する。DuckDBの型名（`TIMESTAMP WITH TIME ZONE`、`VARCHAR`、`BIGINT`など）とArrow/Parquetの型名（`timestamp[us, tz=UTC]`、`string`、`int64`など）は表記が異なるため、比較は必ずcanonicalへ正規化して行う。

canonical typeの定義と、pyarrow schemaからcanonicalへの変換関数は`dataset_catalog`に置き、Pipelinesの保存時検証とBackendの契約テストが同一の変換を使う。これにより両者の型比較が同じ基準になる。

### 4. Backend側はcatalog schemaを契約テストで利用する

Backend SQLを全て自動生成する設計には変更しない。代わりに、各datasetの代表Parquet fixtureに対して、以下をCIで確認する。

- required columnsが存在する
- expected typeと実Parquet schemaが一致する（canonical正規化経由）
- 主要Repository queryが実行できる

fixtureは既存の手書きfixtureを維持し、カタログからfixture列を生成するヘルパーは追加しない。カタログとfixtureが同時にドリフトするとテストが通る循環検証を避けるため。カタログと実出力の照合は、Pipelines保存時の検証（同一のcanonical変換）が担う。

既存SQLはそのまま利用し、schemaの破壊的変更を早期検知する。

### 5. SQLite migrationを一元管理する

SQLiteの`PRAGMA user_version`を使い、migration関数を番号順に実行する。

```text
schema version 1 -> 現行のデプロイ済みschemaを基準状態として登録
```

現在の`google_health_sync_cursors`列存在チェックによるmigrationは、version 1のbootstrapへ統合する。

- 空DB: 基準schemaを作成してversion 1を記録してから後続migrationを適用する
- `user_version=0`の既存DB: version 1を適用する。基準schemaのテーブルは`CREATE TABLE IF NOT EXISTS`で欠落分だけ作成し、`google_health_sync_cursors`へは`PRAGMA table_info`で不足するPhase 2列だけ`ALTER TABLE`する。既に存在する列へ同じ`ALTER TABLE`を再実行しない
- 通常のschema初期化から個別列チェックを削除し、以後の変更は番号付きmigrationに限定する

migration runnerは各migrationを1トランザクションで実行し、途中失敗時はrollbackする。`user_version`の更新も同一トランザクション内で行う。

## 実装計画

### 1. Worktree作成

- `origin/main`を起点に`feat/dataset-contract-migration`のGit worktreeを作成する
- 既存worktreeの未コミット変更は取り込まない
- Dataset CatalogとSQLite migrationは依存関係を整理し、意味ごとにコミットを分ける

### 2. TDD: Dataset Catalog schema

1. `DatasetDefinition`がschema versionを保持できるテストを追加する
2. required columnsが空または重複の場合に失敗するvalidationを追加する
3. `column_types`のkeyがrequired columnsに含まれない場合に失敗するvalidationを追加する
4. 全`ALL_DATASETS`にschema versionが設定されるテストを追加する
5. 各datasetのrequired columnsが既存transform出力と一致するfixtureテストを追加する

既存R2上のParquetを直ちに全て書き換えることは行わない。まず現行writerとfixtureの実態を調査し、schema version 1の契約を現行出力に合わせて定義する。既存データとの差分があるdatasetは、別途データ修復・再生成の課題として記録する。

初期登録対象は、カタログに定義済みの`ALL_DATASETS`全14件とする。

- Spotify plays / tracks / artists
- GitHub pull requests / commits / repositories
- Browser History page views
- YouTube watch events / videos / channels
- Google Health daily metrics / samples / intervals / sessions

### 3. Catalog schema実装

1. `DatasetDefinition`にschema version、required columns、column typesを直接追加する
2. canonical type文字列の定義とpyarrow schema→canonical変換関数を`dataset_catalog`に追加する
3. 各datasetの実際のParquet出力・Backend query・fixtureから必須カラムと実際の型を確認する
4. 既存datasetのpath、partition、dedupe、sort、time columnは変更しない
5. Catalogの一覧・lookupテストを更新する

schema列の説明文やnullableは、今回の必須契約には含めず、必要なdatasetから段階的に追加する。

### 4. TDD: 保存前schema検証

1. required columnが存在する正常系テストを追加する
2. required column欠落時に統一エラーを返すテストを追加する
3. 空レコードの扱いをdatasetごとに確認する（検証スキップ）
4. 型不一致をバイト列生成後・アップロード前に検知するテストを追加する
5. validation失敗時にParquet保存（アップロード）が実行されないテストを追加する
6. validation失敗がpipeline結果とcursor更新へ反映されることを確認する

### 5. Pipelines保存側への接続

共通のParquet byte変換処理にdataset固有の責務を持たせず、datasetが確定している各storageの保存入口で共通validatorを呼び出す。

優先順位は以下とする。

1. Spotify / GitHubのmonthly event・master保存
2. Browser Historyのevent保存
3. YouTubeのevent・snapshot保存
4. Google Healthのevent・range replace保存

sourceごとに別validatorを作らず、DatasetDefinitionを受け取る共通関数を利用する。各sourceの既存の戻り値・例外契約は維持し、GitHub ingestだけはデータ整合性の計画に従って失敗を`RuntimeError`へ集約する。

### 6. Backend契約テスト

1. 既存の手書きfixtureのschemaをDuckDBまたはPyArrowで取得する
2. Catalogとのrequired columns/type差分をcanonical正規化経由で検証する
3. 既存Repositoryの代表queryを実行する
4. type変更・column欠落時にテストが失敗することを確認する

fixture生成をカタログから導出しない（手書きfixtureを維持する）。

既存のBackend integration test fixtureを全て作り直さず、まずはdatasetごとのschema契約テストを追加する。

### 7. SQLite migration実装

1. 現行のデプロイ済みschemaを基準version 1として定義する（`google_health_sync_cursors`の列チェックmigrationを統合）
2. migration runnerとschema version取得処理を追加する（1トランザクション・失敗時rollback）
3. `user_version=0`の既存DBを基準version 1へbootstrapする処理を追加する
4. migrationを複数回実行しても結果が変わらないテストを追加する
5. 空DB、現行schemaの既存DB、基準列が不足する既存DBのそれぞれで`PipelineService.create()`が起動することを確認する
6. migration途中失敗時にrollbackされることを確認するテストを追加する

### 8. ドキュメント更新

- `docs/architecture/dataset-catalog.md`へschema契約の項目を追加する
- `docs/architecture/data-strategy.md`へwrite/read contractの説明を追加する
- `docs/architecture/pipelines.md`へSQLite migration管理（`user_version`）の説明を追加する

### 9. 検証

```bash
USE_ENV_FILE=false uv run pytest \
  egograph/backend/tests/unit/test_dataset_catalog.py \
  egograph/pipelines/tests/unit/test_compaction.py \
  egograph/pipelines/tests/unit/test_schema.py \
  egograph/pipelines/tests/unit/test_service.py

USE_ENV_FILE=false uv run pytest \
  egograph/backend/tests/unit/test_dataset_catalog.py \
  egograph/backend/tests/unit/database \
  egograph/backend/tests/integration/test_compacted_parquet_reads.py

USE_ENV_FILE=false \
R2_ENDPOINT_URL=https://test.r2.cloudflarestorage.com \
R2_ACCESS_KEY_ID=test-access-key \
R2_SECRET_ACCESS_KEY=test-secret-key \
R2_BUCKET_NAME=test-bucket \
uv run pytest egograph/backend/tests egograph/pipelines/tests
```

### 10. コミットとPR

- `feat: add parquet schema contracts to dataset catalog`
- `feat: add sqlite schema migrations`
- `docs: document dataset and sqlite migration contracts`

Dataset Catalogのschema契約とSQLite migrationは独立しているため、別PRでも並行して進められる。PR descriptionには既存DBへのmigration手順、canonical typeの正規化方針、schema契約の対象dataset、検証結果を記載する。

## 完了条件

- 全datasetがschema version、required columns、column typesを持つ
- 保存時（アップロード前）にrequired columns不足・型不一致を検知できる
- 空データ保存時に検証をスキップし既存契約を維持する
- Backendの代表Parquet fixtureとCatalogの契約テストがある
- 空DB・既存DBの両方でmigrationが成功する
- migrationを繰り返してもschemaが壊れない
- migration途中失敗時にrollbackされる
- 関連docsが実装と一致する

## 今回の対象外

- workflow runへの実行時version記録（definition_version / application_version）
- 過去workflow定義の完全なsnapshot保存と再実行
- 任意のschema evolution自動変換
- 汎用データ品質ルールエンジン
- 外部schema registryの導入
- REST/MCP response schemaの自動生成
- 全SQLのCatalogからの自動生成
