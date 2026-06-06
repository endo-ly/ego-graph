# Plan: Browser History 起点の YouTube データソース実装

Browser History の page view から YouTube watch event を抽出し、`events/youtube/watch_events` と `master/youtube/{videos,channels}` を生成する。あわせて backend に YouTube 専用 REST / MCP Tool を再導入し、視聴履歴・統計・ランキングを利用可能にする。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- 既存の `browser_history` ingest パイプラインは原本保存を維持し、YouTube はその派生データセットとして追加する。
- YouTube metadata 解決は `google_activity` source に残っている `YouTubeAPIClient` と transform 資産を可能な限り再利用し、二重実装を避ける。
- `watch_events` は backend / Tool 利用時に join を最小化できる完成済みレコードとして保存し、`videos` / `channels` は正規辞書として別保持する。
- backend の公開仕様は [youtube.md](/root/workspace/ego-graph/docs/20.egograph/pipelines/youtube.md) を source of truth とし、過去の `watch_history` / `watching_stats(total_seconds)` 前提から watch-event 中心仕様へ置き換える。
- テストは各 Step で RED → GREEN を完結させ、pipelines と backend の両方で正常系・空状態・境界値・異常系・エッジケース・統合を意識して追加する。

## Plan スコープ

WT作成 → 実装(TDD) → コミット(意味ごとに分離) → PR作成

## 対象一覧

| 対象 | 実装元 |
|---|---|
| Browser History から YouTube watch URL を抽出する派生 pipeline | `egograph/pipelines/sources/browser_history/` |
| YouTube metadata 解決と `videos` / `channels` master 保存 | `egograph/pipelines/sources/google_activity/`, `egograph/pipelines/sources/common/` |
| YouTube watch_events / master の storage・state・workflow 接続 | `egograph/pipelines/` |
| YouTube query / repository / domain tool / REST / MCP 公開 | `egograph/backend/` |
| パイプライン・backend ドキュメント更新 | `docs/20.egograph/` |

---

## Step 0: Worktree 作成

- `feature/youtube-watch-events` などの GitHub Flow 準拠ブランチ名で worktree を作成する。
- `youtube.md` を仕様の基準文書として参照できる状態にする。
- 既存の `google_activity` YouTube 実装を読み、流用対象を棚卸しする。

---

## Step 1: Browser History → YouTube watch event 抽出基盤 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_extract_watch_event_from_watch_url` | `watch?v=` URL から `video_id` と `content_type=video` を抽出できる |
| `test_extract_watch_event_from_shorts_url` | `shorts/` URL から `video_id` と `content_type=short` を抽出できる |
| `test_extract_watch_event_from_youtu_be_url` | `youtu.be/` 短縮 URL を正規 URL に変換できる |
| `test_skip_non_watch_youtube_urls` | channel / playlist / feed / search は watch event として除外される |
| `test_require_title_in_browser_history_input` | `title` 欠落 payload は変換対象外または validation error になる |
| `test_group_events_by_month_for_youtube_storage` | 抽出済み watch event が月単位で保存対象に分配される |

### GREEN: 実装

- `browser_history` source 配下に YouTube 抽出ロジックを追加し、page view 行から watch event 候補を生成する。
- URL 正規化、`video_id` 抽出、`content_type` 判定を共通関数として切り出す。
- `watch_events` 保存用の schema / row builder の最小版を導入するが、この段階では metadata 解決結果がなくても一時レコード生成までに留める。
- Browser History ingest の成功パスから YouTube 派生保存処理へつなぐ入口を用意する。

### コミット

`feat: add youtube watch event extraction from browser history`

---

## Step 2: YouTube Data API 連携と master 更新 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_reuse_youtube_api_client_for_video_metadata` | `video_id` 群から動画 metadata を取得できる |
| `test_build_video_master_rows_from_api_response` | API レスポンスから `videos` master 行を生成できる |
| `test_build_channel_master_rows_from_api_response` | API レスポンスから `channels` master 行を生成できる |
| `test_fill_watch_event_metadata_from_video_master` | `watch_event` に `video_title`, `channel_id`, `channel_name` を埋められる |
| `test_fail_pipeline_when_metadata_resolution_is_unavailable` | metadata 解決失敗時に中途半端な completed event を保存しない |
| `test_save_video_and_channel_master_parquet` | `master/youtube/videos` と `master/youtube/channels` が保存される |
| `test_update_youtube_ingest_state_only_after_all_outputs_saved` | events/master すべて成功時のみ state 更新する |

### GREEN: 実装

- `google_activity` にある `YouTubeAPIClient`, `transform_video_info`, `transform_channel_info` を共通利用しやすい場所へ整理するか、依存を逆流させずに流用する。
- `videos master` と `channels master` の保存ヘルパーを YouTube pipeline に追加する。
- 抽出済み watch event に対し、動画 metadata を解決して完成済みレコードへ昇格させる。
- `youtube_ingest_state.json` を定義し、再実行時の進捗管理と idempotency を保ちやすくする。

### コミット

`feat: resolve youtube metadata and persist masters`

---

## Step 3: Backend query / repository / schema 再設計 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_get_youtube_watch_events_returns_completed_rows` | `watch_events` が仕様どおりの列を返す |
| `test_get_youtube_watching_stats_counts_watch_events_and_uniques` | `watch_event_count`, `unique_video_count`, `unique_channel_count` を返す |
| `test_get_youtube_top_videos_orders_by_watch_event_count` | 動画ランキングが `watch_event_count` 降順になる |
| `test_get_youtube_top_channels_orders_by_watch_event_count` | チャンネルランキングが `watch_event_count` 降順になる |
| `test_watch_event_queries_read_new_watch_events_path` | `youtube/watch_events` パスを読む |
| `test_repository_methods_match_new_tool_contract` | repository が新しい query 返却形に一致する |
| `test_queries_handle_empty_master_data_gracefully` | master が空でも安全に失敗または空結果を返す |

### GREEN: 実装

- `backend/infrastructure/database/youtube_queries.py` を `watch_history` / `total_seconds` 前提から `watch_events` / unique counts 前提へ置き換える。
- repository を `get_youtube_watch_events`, `get_youtube_watching_stats`, `get_youtube_top_videos`, `get_youtube_top_channels` の契約に合わせて更新する。
- response schema と internal query result を新しい列名・意味へ揃える。
- 既存 YouTube path / schema 名との不整合を解消する。

### コミット

`refactor: align backend youtube queries with watch events`

---

## Step 4: REST / MCP Tool 公開と registry 接続 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_youtube_watch_events_api_returns_expected_fields` | REST API が `watch_events` 仕様のレスポンスを返す |
| `test_youtube_watching_stats_api_returns_unique_counts` | REST API が統計指標 3 つを返す |
| `test_youtube_top_videos_api_returns_video_ranking` | REST API が動画ランキングを返す |
| `test_youtube_top_channels_api_returns_channel_ranking` | REST API がチャンネルランキングを返す |
| `test_mcp_registry_includes_youtube_tools` | MCP list_tools に YouTube 4 Tool が載る |
| `test_mcp_call_youtube_tool_returns_json_payload` | MCP call_tool で JSON テキストが返る |
| `test_tool_input_schema_matches_documented_contract` | domain tools の input schema が合意仕様と一致する |

### GREEN: 実装

- `domain/tools/youtube/stats.py` と `api/youtube.py` を合意済み Tool 仕様へ更新する。
- `usecases/tools/factory.py` で YouTube Tool を registry に正式復帰させる。
- `main.py` / API router へ YouTube endpoint を必要に応じて再接続する。
- response schema を API / MCP 双方で一貫させる。

### コミット

`feat: expose youtube watch event tools via api and mcp`

---

## Step 5: ドキュメント・設定・回帰整備 (TDD)

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_settings_load_youtube_api_key_for_browser_history_pipeline` | `YOUTUBE_API_KEY` が共通設定から読める |
| `test_compacted_parquet_reads_youtube_watch_events` | compact / local parquet 読みが新パスで動く |
| `test_pipeline_docs_and_backend_docs_are_consistent` | 仕様上重要な path / tool 名の不整合を防ぐチェックを追加できるなら追加する |

### GREEN: 実装

- `docs/20.egograph/backend` 側の YouTube 関連記述を新仕様へ更新する。
- 必要なら `pipelines` workflow / storage / compact bootstrap の provider 一覧へ YouTube を追加する。
- 設定ファイル・README・サンプルコマンドを実装に合わせて更新する。

### コミット

`docs: align youtube implementation docs and config`

---

## Step 6: 動作確認

- `uv run pytest egograph/pipelines/tests`
- `uv run pytest egograph/backend/tests`
- `uv run ruff check .`
- `uv run ruff format --check .`
- 必要に応じて対象テストを絞った再実行

---

## Step 7: PR 作成

- worktree ブランチを push する
- PR description は日本語で作成する
- 仕様文書 `docs/20.egograph/pipelines/youtube.md` と Plan を参照できるようにする
- 必要なら `Close #XX` を記載する

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egograph/pipelines/sources/browser_history/transform.py` | 変更 | YouTube watch URL 抽出・正規化 |
| `egograph/pipelines/sources/browser_history/ingest_pipeline.py` | 変更 | YouTube 派生保存の接続 |
| `egograph/pipelines/sources/browser_history/pipeline.py` | 変更 | ingest result / workflow 接続 |
| `egograph/pipelines/sources/browser_history/storage.py` | 変更 | YouTube events 保存補助 |
| `egograph/pipelines/sources/google_activity/youtube_api.py` | 変更 | 共通化または流用調整 |
| `egograph/pipelines/sources/google_activity/transform.py` | 変更 | `videos` / `channels` master 変換再利用 |
| `egograph/pipelines/sources/common/config.py` | 変更 | YouTube 設定の利用整理 |
| `egograph/pipelines/sources/common/settings.py` | 変更 | `YOUTUBE_API_KEY` 読み込み整理 |
| `egograph/backend/infrastructure/database/youtube_queries.py` | 変更 | watch_events 前提 query へ置換 |
| `egograph/backend/infrastructure/repositories/youtube_repository.py` | 変更 | 新しい query 契約へ追従 |
| `egograph/backend/domain/tools/youtube/stats.py` | 変更 | 4 Tool の仕様更新 |
| `egograph/backend/api/youtube.py` | 変更 | REST API 契約更新 |
| `egograph/backend/usecases/tools/factory.py` | 変更 | YouTube Tool registry 復帰 |
| `egograph/backend/api/schemas/data.py` | 変更 | YouTube response schema 更新 |
| `egograph/backend/tests/unit/repositories/test_youtube_queries.py` | 変更 | query 単体テスト更新 |
| `egograph/backend/tests/unit/repositories/test_youtube_repository.py` | 変更 | repository テスト更新 |
| `egograph/backend/tests/integration/*youtube*` | **新規/変更** | API / MCP / compact 統合テスト |
| `egograph/pipelines/tests/**/youtube*` | **新規** | pipeline・storage・transform テスト |
| `docs/20.egograph/backend/architecture.md` | 変更 | backend 側 YouTube 仕様更新 |
| `docs/20.egograph/pipelines/youtube.md` | 変更 | 実装確定後の微修正 |

---

## コミット分割

1. `feat: add youtube watch event extraction from browser history`
対象: browser_history source / pipeline tests

2. `feat: resolve youtube metadata and persist masters`
対象: YouTube API client reuse, videos/channels master, pipeline state

3. `refactor: align backend youtube queries with watch events`
対象: backend queries, repositories, schemas, unit tests

4. `feat: expose youtube watch event tools via api and mcp`
対象: domain tools, API, MCP registry, integration tests

5. `docs: align youtube implementation docs and config`
対象: docs, settings, remaining consistency fixes

---

## テストケース一覧（全 24 件）

### Browser History → YouTube 抽出 (6)
1. `test_extract_watch_event_from_watch_url` — `watch?v=` URL から動画IDと `content_type=video` を抽出できる
2. `test_extract_watch_event_from_shorts_url` — `shorts/` URL から動画IDと `content_type=short` を抽出できる
3. `test_extract_watch_event_from_youtu_be_url` — 短縮 URL を正規 URL に変換できる
4. `test_skip_non_watch_youtube_urls` — 非 watch ページを除外できる
5. `test_require_title_in_browser_history_input` — `title` 欠落時の扱いを固定できる
6. `test_group_events_by_month_for_youtube_storage` — 月単位保存対象を計算できる

### Metadata / Master 保存 (7)
7. `test_reuse_youtube_api_client_for_video_metadata` — 動画 metadata を取得できる
8. `test_build_video_master_rows_from_api_response` — `videos` master 行を生成できる
9. `test_build_channel_master_rows_from_api_response` — `channels` master 行を生成できる
10. `test_fill_watch_event_metadata_from_video_master` — watch event に metadata を反映できる
11. `test_fail_pipeline_when_metadata_resolution_is_unavailable` — metadata 解決失敗時に completed event を保存しない
12. `test_save_video_and_channel_master_parquet` — `videos/channels` master を保存できる
13. `test_update_youtube_ingest_state_only_after_all_outputs_saved` — 全保存成功時のみ state 更新する

### Backend Query / Repository (7)
14. `test_get_youtube_watch_events_returns_completed_rows` — watch event query が完成済み列を返す
15. `test_get_youtube_watching_stats_counts_watch_events_and_uniques` — 3 指標を集計できる
16. `test_get_youtube_top_videos_orders_by_watch_event_count` — 動画ランキング順が正しい
17. `test_get_youtube_top_channels_orders_by_watch_event_count` — チャンネルランキング順が正しい
18. `test_watch_event_queries_read_new_watch_events_path` — 新パスから読み込む
19. `test_repository_methods_match_new_tool_contract` — repository 契約が Tool 仕様と一致する
20. `test_queries_handle_empty_master_data_gracefully` — master が空でも破綻しない

### API / MCP / 設定統合 (4)
21. `test_youtube_watch_events_api_returns_expected_fields` — REST API が仕様どおり返す
22. `test_youtube_watching_stats_api_returns_unique_counts` — REST API が 3 指標を返す
23. `test_mcp_registry_includes_youtube_tools` — MCP list_tools に 4 Tool が載る
24. `test_settings_load_youtube_api_key_for_browser_history_pipeline` — YouTube API キー設定が正しく読める

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 0 | Worktree 作成と事前調査 | ~30 行 |
| Step 1 | Browser History 抽出基盤 + テスト | ~220 行 |
| Step 2 | metadata 解決 + master 保存 + テスト | ~260 行 |
| Step 3 | backend query / repository / schema 更新 + テスト | ~260 行 |
| Step 4 | REST / MCP Tool 公開 + テスト | ~220 行 |
| Step 5 | docs / 設定 / 整合更新 + テスト | ~120 行 |
| Step 6 | 動作確認 | ~20 行 |
| Step 7 | PR 作成 | ~20 行 |
| **合計** |  | **~1,150 行** |
