# Plan: タイムゾーン対応クエリ（保存UTC・取得時環境TZ変換）

## 方針

保存はUTCのまま変更しない。取得時に「入力日付を環境TZと解釈→UTCに変換→UTC同士で比較」を行い、日付境界のズレを解消する。

## 変更範囲

### 1. 環境TZ設定の追加

- `egograph/pipelines/.env.example` に `TIMEZONE=Asia/Tokyo` を追加
- `egograph/backend/config.py` の `BackendConfig` に `timezone` フィールドを追加（デフォルト `UTC`）
  - `from zoneinfo import ZoneInfo` で `ZoneInfo` オブジェクトとして保持

### 2. バリデータの拡張（入力TZ→UTC変換）

- `backend/validators.py` に `to_utc_range(start_date, end_date, tz) -> tuple[datetime, datetime]` を追加
  - `date` を `datetime(yyyy, mm, dd, tzinfo=tz)` と解釈し、UTC の `datetime` に変換
  - end_date は翌日の 00:00:00（`<` で比較するため）

### 3. QueryParams に utc_start / utc_end を追加

4つの QueryParams dataclass を変更:
- `backend/infrastructure/database/queries.py` → `QueryParams`
- `backend/infrastructure/database/github_queries.py` → `GitHubQueryParams`
- `backend/infrastructure/database/browser_history_queries.py` → `BrowserHistoryQueryParams`
- `backend/infrastructure/database/youtube_queries.py` → `YouTubeQueryParams`

変更内容:
- `start_date: date` / `end_date: date` を残す（パーティションパス生成で使用）
- `utc_start: datetime` / `utc_end: datetime` を追加（WHERE句で使用）

### 4. SQLクエリの変更（WHERE句を `>=` / `<` に変更）

全 `_utc::DATE BETWEEN ? AND ?` パターンを `_utc >= ? AND _utc < ?` に変更:

| ファイル | 変更対象カラム |
|---|---|
| `queries.py` | `played_at_utc::DATE BETWEEN` → `played_at_utc >= ? AND played_at_utc < ?` |
| `github_queries.py` | `updated_at_utc::DATE BETWEEN`, `committed_at_utc::DATE BETWEEN` |
| `browser_history_queries.py` | `started_at_utc::DATE BETWEEN` |
| `youtube_queries.py` | `watched_at_utc::DATE BETWEEN` |

`strftime(...::DATE, ...)` の GROUP BY も `strftime(... AT TIME ZONE ?, ...)` に変更し、環境TZ で期間バケットを生成する。

### 5. Repository層の変更（utc_start/utc_end の受け渡し）

- `backend/infrastructure/repositories/spotify_repository.py`
- `backend/infrastructure/repositories/github_repository.py`
- `backend/infrastructure/repositories/browser_history_repository.py`
- `backend/infrastructure/repositories/youtube_repository.py`

Repository の各メソッドで `to_utc_range()` を呼び出し、`utc_start`/`utc_end` を QueryParams に渡す。
Repository が timezone を知る必要があるため、コンストラクタで `ZoneInfo` を受け取るように変更。

### 6. Tool層の変更（timezone の注入）

各Tool の `execute()` から Repository を呼ぶ際、Repository に既に timezone が設定済みなので Tool 側の変更は最小限。

### 7. 依存注入の更新

- Repository インスタンス生成時に `ZoneInfo` を渡す箇所（DI container / dependencies）を更新

### 8. テストの更新

- `validators.py` の `to_utc_range` の単体テストを追加
- 各 query テストで `utc_start`/`utc_end` を渡すように更新
- TZ=Asia/Tokyo での日付境界テストを追加（JST 23:59 のデータが正しく含まれることを確認）

## 変更しないもの

- Parquet のスキーマ・保存ロジック（UTCのまま）
- Pipelines側のロジック（UTCのまま）
- `_utc` カラム名（保存フォーマットの仕様）

## 作業順序

1. `.env.example` + `config.py`（TZ設定）
2. `validators.py`（`to_utc_range`）
3. 4つの QueryParams dataclass に `utc_start`/`utc_end` を追加
4. 4つの queries.py の SQL を変更
5. 4つの Repository を変更
6. 依存注入を更新
7. テストを更新・追加
8. `uv run pytest` で全テスト通過確認
