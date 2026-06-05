# Plan: YouTube Compaction 実装 & ログ・エラーメッセージからのインフラ情報漏洩防止

YouTube compact step 未実装による 404 エラーの解消と、DuckDB エラーメッセージ経由での R2 エンドポイント URL 漏洩の防止。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 背景

### 問題1: YouTube データ取得 404

MCP 経由で YouTube 視聴履歴を取得すると 404 になる。

```
HTTP Error: Unable to connect to URL "https://xxxxx.r2.cloudflarestorage.com/egograph/compacted/events/youtube/watch_events/year%3D2026/month%3D05/data.parquet": 404 (Not Found).
```

**根本原因**: `youtube_ingest_workflow` に compact step が存在しない。Pipeline は ingest で sync_id 単位の個別ファイル（`events/youtube/watch_events/year=.../month=.../sync_id=xxx.parquet`）を保存するが、Backend は compacted 版（`compacted/.../data.parquet`）を期待している。

Spotify / GitHub / Browser History はすべて ingest + compact の2ステップ構成だが、YouTube は ingest のみ。また `bootstrap_compact.py` にも YouTube は未登録。

### 問題2: R2 エンドポイント URL のログ・レスポンス漏洩

DuckDB が parquet ファイルのアクセスに失敗すると、生成するエラーメッセージに R2 エンドポイント URL（`https://xxxxx.r2.cloudflarestorage.com/...`）が含まれる。このメッセージが複数の経路で外部に露出している。

漏洩経路（MECE）:

| # | 経路 | ファイル | 箇所 | 深刻度 |
|---|---|---|---|---|
| A | MCP エラーレスポンス | `mcp_server.py` L65 | `raise RuntimeError(f"Tool execution failed: {exc}")` | **高** |
| B | MCP サーバーログ（トレースバック） | `mcp_server.py` L64 | `logger.exception(...)` — フルトレースバックにURL含有 | **高** |
| C | ToolRegistry エラーログ | `usecases/tools/registry.py` L92 | `logger.error(f"{type(e).__name__}: {e}")` | **高** |
| D | REST Health エラーレスポンス | `api/health.py` L81 | `{"status": "error", "error": str(e)}` | **中** |
| E | DuckDB 接続ログ | `infrastructure/database/connection.py` L126 | `logger.debug("... endpoint: %s", endpoint)` | **低** |
| F | Parquet 存在確認ログ（トレースバック） | `infrastructure/database/youtube_queries.py` L51 | `logger.warning("... existence: %s", path, exc_info=True)` — フルトレースバックにURL含有 | **低** |
| G | YouTube master 未検出ログ | `infrastructure/database/youtube_queries.py` L80,94 | `logger.debug("... not found: %s", path)` | **低** |
| H | Verify スクリプト | `scripts/verify_*.py` | 手動実行のみ | 対象外 |

**特記事項**: 経路 B・F は `logger.exception` / `exc_info=True` により **フルトレースバック** も出力される。トレースバック内の DuckDB エラーメッセージに R2 URL が含まれるため、メッセージ本文のサニタイズだけでは不十分。ログ出力レベルでのサニタイズが必要。

## 設計方針

- **既存パターン踏襲**: YouTube compact は **GitHub パターン**（`compact_month` は `data_domain` をハードコード、events のみ）に従う。YouTube は master データの compact が不要なため、Spotify パターン（events/master 切替）よりシンプルな GitHub パターンが適切
- **サニタイズは中央集権**: 二層防御で設計
  - **主防御（ログ）**: カスタム `logging.Filter` で全ロガー出力をフックし、トレースバック含むすべてのログメッセージをサニタイズ。経路 B・C・E・F・G を一括でカバー。新規エラーパスの追加漏れを防止
  - **副防御（HTTPレスポンス）**: MCP エラーレスポンス（経路 A）・Health エラーレスポンス（経路 D）の `str(e)` に対して `sanitize_infra_message` をコールサイトで適用。HTTP レスポンスボディは logging.Filter の管轄外のため個別対応が必要
- **サニタイズ先行**: ログ修正 → compact 実装の順。compact 追加に伴い新たなログ・エラー経路が増えるため先に基盤を固める
- **外部向けメッセージのみサニタイズ**: 開発者向け手動スクリプト（`scripts/verify_*.py`）は対象外

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 実装元 |
|---|---|
| インフラ情報サニタイズユーティリティ（正規表現） | **新規** |
| logging.Filter（ログ出力の一元サニタイズ） | **新規** |
| MCP server エラーレスポンス | 変更 |
| Health エンドポイントエラーレスポンス | 変更 |
| ToolRegistry エラーログ | Filter で自動カバー（コード変更なし） |
| DuckDB 接続ログ | Filter で自動カバー（コード変更なし） |
| YouTube queries ログ | Filter で自動カバー（コード変更なし） |
| Backend アプリケーション初期化（Filter 登録） | 変更 |
| YouTubeStorage（compacted_path 初期化 + compact_month） | 変更 |
| YouTube compact エントリポイント | **新規** |
| Workflow registry（YouTube compact step） | 変更 |
| Bootstrap compact（YouTube provider） | 変更 |
| YouTube __init__.py（export 追加） | 変更 |
| YouTube パイプラインドキュメント | 変更 |

---

## Step 0: Worktree 作成

`worktree-create` skill で WT を作成する。

---

## Step 1: インフラ情報サニタイズユーティリティ + logging.Filter (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_sanitize_masks_s3_url` | `s3://bucket-name/path` → `s3://***/path` |
| `test_sanitize_masks_r2_endpoint_url` | `https://xxx.r2.cloudflarestorage.com/path` → ホスト名マスク |
| `test_sanitize_preserves_non_infra_text` | インフラ情報を含まない文字列はそのまま |
| `test_sanitize_masks_multiple_occurrences` | 複数の s3:// URL がすべてマスクされる |
| `test_sanitize_exception_applies_message_sanitization` | Exception メッセージに対して sanitize が適用される |
| `test_sanitize_empty_string` | 空文字はそのまま返る |
| `test_infra_sanitizing_filter_masks_log_message` | LogRecord の message から s3:// URL がマスクされる |
| `test_infra_sanitizing_filter_masks_traceback` | LogRecord の traceback テキストから R2 URL がマスクされる |
| `test_infra_sanitizing_filter_preserves_clean_messages` | インフラ情報なしログメッセージはそのまま通過 |

### GREEN: 実装

新規ファイル `egograph/backend/infrastructure/logging/sanitizers.py` に以下を追加:

- `sanitize_infra_message(message: str) -> str`: s3:// URL、R2 エンドポイント URL を正規表現でマスク
- `sanitize_exception(exc: Exception) -> str`: 例外メッセージに `sanitize_infra_message` を適用
- `InfraSanitizingFilter(logging.Filter)`: カスタム logging.Filter。`filter()` メソッドで LogRecord の message（`record.getMessage()`）をサニタイズ。`record.msg` をサニタイズ済みテキストに差し替え、`record.args` をクリアして再フォーマットを防止。トレースバックは `record.exc_text` が設定されたタイミングでサニタイズ

### コミット

`feat(backend): add infra info sanitizer and logging filter`

---

## Step 2: Filter 登録 + HTTP レスポンスサニタイズ適用 (TDD)

前提: Step 1

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_mcp_error_response_excludes_r2_url` | DuckDB エラー発生時の MCP レスポンスに R2 URL が含まれない |
| `test_mcp_error_response_excludes_s3_path` | S3 パスが MCP レスポンスに含まれない |
| `test_health_error_response_excludes_infra_info` | Health エンドポイントのエラーレスポンスにインフラ情報が含まれない |
| `test_log_filter_registered_on_app_startup` | アプリケーション起動時に InfraSanitizingFilter がルートロガーに登録される |
| `test_log_output_sanitized_via_filter` | logger.error にインフラURLを渡しても実際の出力に含まれない |

### GREEN: 実装

**Filter 登録**:

- `egograph/backend/main.py`（または FastAPI アプリケーション初期化箇所）: ルートロガーに `InfraSanitizingFilter` を登録。これにより経路 B・C・E・F・G のログ出力がすべて自動サニタイズされる

**HTTP レスポンス（コールサイト対応）**:

- `mcp_server.py` L65: `raise RuntimeError(f"Tool execution failed: {sanitize_exception(exc)}")` — 経路 A
- `api/health.py` L81: `return {"status": "error", "error": sanitize_infra_message(str(e))}` — 経路 D

**変更不要なファイル（Filter で自動カバー）**:

- `usecases/tools/registry.py` — 経路 C は Filter で自動カバー。コールサイト変更なし
- `infrastructure/database/connection.py` — 経路 E は Filter で自動カバー。コールサイト変更なし
- `infrastructure/database/youtube_queries.py` — 経路 F・G は Filter で自動カバー。コールサイト変更なし

### コミット

`fix(backend): sanitize infra info from logs via filter and from HTTP error responses`

---

## Step 3: YouTubeStorage compact_month (TDD)

前提: Step 2

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_compact_month_reads_source_and_saves_compacted` | 対象月の parquet を読み compacted として保存する |
| `test_compact_month_returns_none_when_no_records` | レコードが存在しない場合は None を返す |
| `test_compact_month_deduplicates_by_watch_event_id` | watch_event_id で重複排除される |
| `test_compact_month_sorts_by_watched_at_utc` | watched_at_utc でソート後、keep=last で最新を残す |

### GREEN: 実装

`egograph/pipelines/sources/youtube/storage.py` の `YouTubeStorage` を変更:

**必須の初期化変更**:

- `__init__` に `self.compacted_path = COMPACTED_ROOT` を追加
- `from pipelines.sources.common.compaction import COMPACTED_ROOT, ...` の import を追加
- （参考: SpotifyStorage L62・GitHubWorklogStorage L64 でも同様に `self.compacted_path = COMPACTED_ROOT` を設定）

**compact_month メソッド追加**:

GitHub パターンに倣い、`data_domain` はハードコード（`"events"`）。YouTube は events データのみで master compact が不要なため:

- シグネチャ: `compact_month(self, year: int, month: int) -> str | None`
- 利用関数: `read_parquet_records_from_prefix`, `compact_records(dedupe_key="watch_event_id", sort_by="watched_at_utc")`, `build_compacted_key`, `dataframe_to_parquet_bytes`
- dataset_path: `"youtube/watch_events"`（YouTubeStorage にハードコード）

### コミット

`feat(pipelines): add compact_month to YouTubeStorage`

---

## Step 4: YouTube compact エントリポイント & Workflow step (TDD)

前提: Step 3

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_run_youtube_compact_compacts_target_months` | 対象月の compact が実行される |
| `test_run_youtube_compact_skips_when_no_data` | データなし月は skip される |
| `test_youtube_ingest_workflow_has_compact_step` | workflow 定義に compact step が含まれる |
| `test_youtube_ingest_workflow_step_order` | ingest → compact の順序である |

### GREEN: 実装

- `egograph/pipelines/sources/youtube/pipeline.py`: `run_youtube_compact(config=None, *, year=None, month=None)` 関数を追加。Spotify/GitHub の `run_*_compact` パターンに倣う
- `egograph/pipelines/sources/youtube/__init__.py`: `run_youtube_compact` を export に追加
- `egograph/pipelines/workflows/registry.py`: `youtube_ingest_workflow` に compact step を追加（ingest → compact の順）。callable_ref: `"pipelines.sources.youtube.pipeline:run_youtube_compact"`

### コミット

`feat(pipelines): add YouTube compact workflow step`

---

## Step 5: Bootstrap compact への YouTube 追加 (TDD)

前提: Step 4

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_bootstrap_compact_includes_youtube_provider` | `--provider youtube` が受け付けられる |
| `test_bootstrap_compact_youtube_discovers_months` | YouTube の月パーティションが正しく検出される |

### GREEN: 実装

- `egograph/pipelines/sources/common/bootstrap_compact.py`:
  - `_compact_youtube()` を追加。DatasetSpec は `DatasetSpec("events", "youtube/watch_events", "watch_event_id", "watched_at_utc")`
  - `--provider` の `choices` に `"youtube"` を追加
  - `main()` に YouTube セクションを追加

### コミット

`feat(pipelines): add YouTube to bootstrap compact`

---

## Step 6: 動作確認

- `uv run pytest egograph/backend/tests --cov=backend`
- `uv run pytest egograph/pipelines/tests --cov=pipelines`
- `uv run ruff check . && uv run ruff format .`

---

## Step 7: ドキュメント更新 & PR 作成

- `docs/30.pipelines/youtube.md`: 実装状況チェックボックス更新、compacted パスの説明追加
- PR 作成（description 日本語）

### コミット

`docs: update YouTube pipeline docs for compaction`

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egograph/backend/infrastructure/logging/__init__.py` | **新規** | パッケージ初期化 |
| `egograph/backend/infrastructure/logging/sanitizers.py` | **新規** | サニタイズ関数 + InfraSanitizingFilter |
| `egograph/backend/tests/unit/logging/__init__.py` | **新規** | テストパッケージ初期化 |
| `egograph/backend/tests/unit/logging/test_sanitizers.py` | **新規** | サニタイズユーティリティ + Filter UT（9件） |
| `egograph/backend/tests/test_mcp_server.py` | 変更 | 既存ファイルに sanitization テストを追加 |
| `egograph/backend/tests/integration/test_api_health.py` | 変更 | 既存ファイルに sanitization テストを追加 |
| `egograph/backend/mcp_server.py` | 変更 | エラーレスポンスに sanitize_exception 適用（経路 A） |
| `egograph/backend/api/health.py` | 変更 | エラーレスポンスに sanitize_infra_message 適用（経路 D） |
| `egograph/backend/main.py`（またはアプリ初期化箇所） | 変更 | ルートロガーに InfraSanitizingFilter 登録 |
| `egograph/pipelines/sources/youtube/storage.py` | 変更 | compacted_path 初期化 + compact_month 追加 |
| `egograph/pipelines/sources/youtube/pipeline.py` | 変更 | run_youtube_compact 追加 |
| `egograph/pipelines/sources/youtube/__init__.py` | 変更 | run_youtube_compact export 追加 |
| `egograph/pipelines/workflows/registry.py` | 変更 | YouTube compact step 追加 |
| `egograph/pipelines/sources/common/bootstrap_compact.py` | 変更 | YouTube provider 追加 |
| `egograph/pipelines/tests/unit/youtube/test_storage_compact.py` | **新規** | YouTubeStorage compact_month UT |
| `egograph/pipelines/tests/unit/youtube/test_pipeline_compact.py` | **新規** | YouTube compact pipeline UT |
| `egograph/pipelines/tests/unit/test_bootstrap_compact.py` | 変更 | 既存ファイルに YouTube テストを追加 |
| `docs/30.pipelines/youtube.md` | 変更 | 実装状況・compacted パス記載更新 |

---

## コミット分割

1. `feat(backend): add infra info sanitizer and logging filter` — Step 1
2. `fix(backend): sanitize infra info from logs via filter and from HTTP error responses` — Step 2
3. `feat(pipelines): add compact_month to YouTubeStorage` — Step 3
4. `feat(pipelines): add YouTube compact workflow step` — Step 4
5. `feat(pipelines): add YouTube to bootstrap compact` — Step 5
6. `docs: update YouTube pipeline docs for compaction` — Step 7

---

## テストケース一覧（全 21 件）

### sanitizers + Filter (9)
1. `test_sanitize_masks_s3_url` — s3:// URL がマスクされる
2. `test_sanitize_masks_r2_endpoint_url` — R2 エンドポイント URL がマスクされる
3. `test_sanitize_preserves_non_infra_text` — インフラ情報なし文字列はそのまま
4. `test_sanitize_masks_multiple_occurrences` — 複数 URL がすべてマスクされる
5. `test_sanitize_exception_applies_message_sanitization` — Exception に対して sanitize 適用
6. `test_sanitize_empty_string` — 空文字はそのまま返る
7. `test_infra_sanitizing_filter_masks_log_message` — LogRecord の message から s3:// URL がマスク
8. `test_infra_sanitizing_filter_masks_traceback` — LogRecord の traceback から R2 URL がマスク
9. `test_infra_sanitizing_filter_preserves_clean_messages` — クリーンなメッセージはそのまま通過

### sanitization 適用 (5)
10. `test_mcp_error_response_excludes_r2_url` — MCP レスポンスに R2 URL 含まれない
11. `test_mcp_error_response_excludes_s3_path` — MCP レスポンスに S3 パス含まれない
12. `test_health_error_response_excludes_infra_info` — Health レスポンスにインフラ情報含まれない
13. `test_log_filter_registered_on_app_startup` — Filter がルートロガーに登録される
14. `test_log_output_sanitized_via_filter` — logger.error 出力にインフラURLが含まれない

### YouTubeStorage compact_month (4)
15. `test_compact_month_reads_source_and_saves_compacted` — 対象月の compact が保存される
16. `test_compact_month_returns_none_when_no_records` — レコードなし時は None
17. `test_compact_month_deduplicates_by_watch_event_id` — watch_event_id で重複排除
18. `test_compact_month_sorts_by_watched_at_utc` — watched_at_utc でソート・keep=last

### YouTube compact pipeline & workflow (4)
19. `test_run_youtube_compact_compacts_target_months` — 対象月 compact 実行
20. `test_run_youtube_compact_skips_when_no_data` — データなし月 skip
21. `test_youtube_ingest_workflow_has_compact_step` — compact step が含まれる
22. `test_youtube_ingest_workflow_step_order` — ingest → compact の順序

### Bootstrap compact YouTube (2)
23. `test_bootstrap_compact_includes_youtube_provider` — --provider youtube が受け付けられる
24. `test_bootstrap_compact_youtube_discovers_months` — YouTube 月パーティションが検出される

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 1 | サニタイズユーティリティ + Filter + UT（9件） | ~100 行 |
| Step 2 | Filter 登録 + HTTP レスポンス適用 + UT（5件） | ~80 行 |
| Step 3 | YouTubeStorage（compacted_path + compact_month）+ UT | ~70 行 |
| Step 4 | compact エントリポイント + workflow + export + UT | ~80 行 |
| Step 5 | bootstrap compact YouTube + UT | ~40 行 |
| Step 7 | ドキュメント更新 | ~20 行 |
| **合計** | | **~390 行** |
