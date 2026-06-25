# Dataset Catalog 導入計画

Howはあくまで参考であり、よりよい設計方針があれば各自で判断し採用する

## 目的

Pipelines の write path と Backend の read path に分散している Parquet dataset の契約を、共有 catalog として明文化する。保存先 path、partition、compaction key、event time column を一箇所に寄せ、今後のデータソース追加・schema evolution・compaction 変更で崩れにくい土台を作る。

## スコープ

- 対象は既存の Parquet dataset 契約に限定する。
- REST / MCP capability 抽象化は行わない。
- 既存の保存形式・公開 API・R2 layout は変更しない。
- `docs/data-sources/google-health.md` など既存の未コミット変更は触らない。

## 設計方針

1. 共有 package として `dataset_catalog` を追加する。
   - Backend / Pipelines の両方から import できる `egograph/dataset_catalog` 配下に置く。
   - Docker build でも含まれるよう `Dockerfile` の COPY 対象に追加する。

2. catalog は「契約」を表現し、処理 orchestration は持たせない。
   - dataset id
   - storage domain
   - canonical path
   - partition policy
   - compaction strategy
   - dedupe key
   - sort key
   - event time column
   - snapshot file name

3. Backend と Pipelines の既存実装へ段階的に接続する。
   - Backend の compacted path 解決は `DatasetDefinition` を受け取る API を追加する。
   - 各 query module の dataset path 直書きを catalog 参照へ置き換える。
   - Pipelines の monthly compaction 対象リストを catalog 参照へ置き換える。
   - Google Health の range replace は date column mapping を catalog から参照する。

4. 旧 API は残さず catalog-aware API へ置き換える。
   - `build_partition_paths(data_domain, dataset_path, ...)` のような文字列指定 API は削除する。
   - Backend / Pipelines / tests は `DatasetDefinition` を受け取る新 API に揃える。

## 実装タスク

1. WT作成
   - `origin/main` から `feat/dataset-catalog` の git worktree を作成する。
   - 既存 worktree の未コミット変更は取り込まない。
2. 実装(TDD)
   - Catalog / path resolver の unit test を先に追加する。
   - `dataset_catalog` package を追加する。
   - Backend path resolver と query modules を catalog-aware に置き換える。
   - Pipelines compaction / writer の dataset metadata を catalog 参照に置き換える。
   - 関連 docs を更新する。
3. 検証
   - `ruff`, backend/pipelines の関連 pytest、必要に応じて全体 pytest を実行する。
4. 自己レビュー
   - 不要な抽象、残った文字列重複、旧 API の残存、docs の不足を確認する。
5. コミット(意味ごとに分離)
   - 原則 `feat: add shared dataset catalog` にまとめる。
   - docs だけ独立させる意味が出た場合は `docs: document dataset catalog` を分ける。
6. PR作成
   - push 後、draft PR を作成する。

## 検証計画

- `uv run ruff check .`
- `uv run pytest egograph/backend/tests/unit/database/test_parquet_paths.py`
- `uv run pytest egograph/backend/tests/unit/database/test_queries.py egograph/backend/tests/unit/database/test_browser_history_queries.py egograph/backend/tests/unit/repositories/test_google_health_queries.py egograph/backend/tests/unit/repositories/test_youtube_queries.py`
- `uv run pytest egograph/pipelines/tests/unit/test_compaction.py egograph/pipelines/tests/unit/test_bootstrap_compact.py egograph/pipelines/tests/unit/spotify/test_storage.py egograph/pipelines/tests/unit/github/test_storage.py egograph/pipelines/tests/unit/browser_history/test_storage.py egograph/pipelines/tests/unit/youtube/test_storage_compact.py egograph/pipelines/tests/unit/google_health/test_writer.py`
- 変更範囲が広がる場合は `uv run pytest egograph/backend/tests egograph/pipelines/tests/unit`

## PR 方針

- ブランチ: `feat/dataset-catalog`
- コミット: `feat: add shared dataset catalog`
- PR description は日本語で、設計意図・変更範囲・検証結果・自己レビュー結果を記載する。
