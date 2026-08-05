# Daily Timeline 仕様

> 最終更新: 2026-07-04

Daily Timeline は、複数データソースの観測イベントを1日単位で時刻順に統合する Backend read model である。REST API は完全形を返し、MCP Tool は同じ意味のデータを AI エージェント向けの compact 表現で返す。

## 目的

AI エージェントが日次レビューを行うとき、Spotify、YouTube、Browser History、GitHub、Google Health を個別に取得して手元で時刻順に並べると、タイムゾーン変換、粒度差、重複候補、観測 gap の扱いで誤判断が起きやすい。

Daily Timeline は Backend 側で以下を行い、AI エージェントには解釈前の整列済み観測事実を渡す。

- ローカル日付と timezone から UTC 範囲を一意に決める
- source ごとの時刻列を UTC で取得し、同じ response shape に正規化する
- `started_at_utc` 昇順で統合する
- YouTube watch event と Browser History page view などの関連候補を注釈する
- 一定時間以上の観測イベント欠落を `no_observed_events_gap` として返す
- Google Health の日次サマリはタイムライン item へ混ぜず、別枠で添付する

Backend は「事実の整列」と「判断材料の付与」までを責務とする。集中状態、感情、作業内容の意味づけなどの解釈は AI エージェント側で行う。

## 公開インターフェース

| 種別 | 名前 |
|---|---|
| REST API | `GET /v1/data/timeline/daily` |
| MCP Tool | `get_daily_timeline` |

REST API と MCP Tool は同じ入力制約、同じ canonical builder、同じ validation を使う。REST API は完全形、MCP Tool は表示上の重複と source 固有 metadata、event_id を省いた compact 表現を返す。

公開契約は1日単位に固定する。時間窓指定や週次レビューが必要になった場合でも、この endpoint / tool の意味を広げず、別契約として追加する。
ただし実装内部は UTC range を入力にした builder として構成し、将来の別契約でも正規化、ソート、correlation、gap 生成のロジックを再利用できるようにする。

## 入力

### パラメータ

| 名前 | 必須 | 型 | 既定値 | 説明 |
|---|---:|---|---|---|
| `date` | Yes | `YYYY-MM-DD` | なし | `timezone` 上のローカル日付 |
| `timezone` | No | IANA timezone | Backend の `TIMEZONE`。未設定時は `Asia/Tokyo` | 日付範囲と local timestamp の生成に使う |
| `sources` | No | `list[string]` | 全 source | 含めるデータソース |
| `gap_minutes` | No | `int \| null` | `120` | この分数以上、観測イベントがない区間を `gaps` に返す。`0` または `null` は gap 検出なし |
| `include_correlations` | No | `bool` | `true` | 関連候補を `correlations` に返す |
| `include_raw_refs` | No | `bool` | `false` | 元 dataset と record id を `raw_ref` に返す |
| `limit` | No | `int` | `500` | `items` の最大件数。最大 `2000` |

### `sources`

許可値:

- `spotify`
- `youtube`
- `browser_history`
- `github`
- `google_health`

`google_health` は `items` には入らず、`daily_summaries.google_health` と `coverage.google_health` に反映される。

### REST 例

```http
GET /v1/data/timeline/daily?date=2026-06-28&timezone=Asia%2FTokyo&gap_minutes=120&include_correlations=true&include_raw_refs=true
```

### MCP 例

```json
{
  "date": "2026-06-28",
  "timezone": "Asia/Tokyo",
  "sources": ["spotify", "youtube", "browser_history", "github", "google_health"],
  "gap_minutes": 120,
  "include_correlations": true,
  "include_raw_refs": true,
  "limit": 500
}
```

## 日付と timezone

`date` は `timezone` 上の civil date として扱う。

例:

```text
date=2026-06-28
timezone=Asia/Tokyo
```

は次の範囲を意味する。

```json
{
  "start_local": "2026-06-28T00:00:00+09:00",
  "end_local": "2026-06-29T00:00:00+09:00",
  "start_utc": "2026-06-27T15:00:00Z",
  "end_utc": "2026-06-28T15:00:00Z"
}
```

全 source の query は UTC 範囲で実行する。返却時は絶対時刻を持つ項目すべてに `*_utc` と `*_local` を併記する。

## 出力

### MCP compact 表現

REST API の canonical response は完全形を返す。MCP Tool はこの response を構築したあと、呼び出し境界で次の compact 表現へ変換する。

- `items[*].event_id` は返さない
- `correlations[*].event_ids` は返さない
- `gaps[*].preceded_by_event_id` / `followed_by_event_id` は返さない
- `items[*].metadata` は返さない
- `started_at_utc` / `started_at_local` は、要求された timezone の `started_at` に統合する
- `ended_at_utc` / `ended_at_local` は、値がある場合だけ `ended_at` に統合する
- `range` と `gaps` の時刻は要求された timezone の local 値だけを返す
- `null`、空文字、空配列、空オブジェクトは省略する。`0` と `false` は保持する
- `include_raw_refs=true` の場合の `raw_ref` は保持する
- `meta.format` は `compact` になる

内部の canonical response と REST API の `event_id` は変更しない。

```json
{
  "date": "2026-06-28",
  "timezone": "Asia/Tokyo",
  "range": {
    "start": "2026-06-28T00:00:00+09:00",
    "end": "2026-06-29T00:00:00+09:00"
  },
  "items": [
    {
      "started_at": "2026-06-28T09:12:03+09:00",
      "source": "spotify",
      "kind": "music_play",
      "duration_seconds": 222,
      "title": "ヨルシカ - だから僕は僕を辞めた"
    }
  ],
  "meta": {
    "item_count": 183,
    "truncated": false,
    "generated_at": "2026-06-28T23:58:10Z",
    "format": "compact"
  }
}
```

### トップレベル

```json
{
  "date": "2026-06-28",
  "timezone": "Asia/Tokyo",
  "range": {
    "start_local": "2026-06-28T00:00:00+09:00",
    "end_local": "2026-06-29T00:00:00+09:00",
    "start_utc": "2026-06-27T15:00:00Z",
    "end_utc": "2026-06-28T15:00:00Z"
  },
  "items": [],
  "correlations": [],
  "gaps": [],
  "daily_summaries": {},
  "coverage": {},
  "meta": {
    "item_count": 183,
    "truncated": false,
    "generated_at": "2026-06-28T23:58:10Z"
  }
}
```

| フィールド | 説明 |
|---|---|
| `date` | 入力されたローカル日付 |
| `timezone` | 実際に使った timezone |
| `range` | local / UTC の対象範囲 |
| `items` | 時刻順に正規化した観測イベント |
| `correlations` | 重複または関連候補。イベント自体は削除しない |
| `gaps` | 観測イベントがない時間帯 |
| `daily_summaries` | Google Health など日次粒度のサマリ |
| `coverage` | source ごとの取得状況 |
| `meta` | 件数、truncate、生成時刻 |

## REST canonical Timeline Item

### 共通 shape

```json
{
  "event_id": "spotify:play:abc123",
  "source": "spotify",
  "kind": "music_play",
  "started_at_utc": "2026-06-28T00:12:03Z",
  "started_at_local": "2026-06-28T09:12:03+09:00",
  "ended_at_utc": "2026-06-28T00:15:45Z",
  "ended_at_local": "2026-06-28T09:15:45+09:00",
  "duration_seconds": 222,
  "title": "ヨルシカ - だから僕は僕を辞めた",
  "subtitle": "Spotify play",
  "url": null,
  "raw_ref": {
    "dataset_id": "spotify.plays",
    "record_id": "abc123",
    "timestamp_column": "played_at_utc"
  },
  "metadata": {}
}
```

| フィールド | 必須 | 説明 |
|---|---:|---|
| `event_id` | Yes | source と record id から作る安定ID |
| `source` | Yes | `spotify` などの source 名 |
| `kind` | Yes | source 内のイベント種別 |
| `started_at_utc` | Yes | ソート基準となる UTC 時刻 |
| `started_at_local` | Yes | `timezone` へ変換した表示用時刻 |
| `ended_at_utc` | No | 終了時刻がある場合のみ |
| `ended_at_local` | No | 終了時刻がある場合のみ |
| `duration_seconds` | No | duration が根拠を持つ場合のみ |
| `title` | Yes | 人間と AI が読む主表示 |
| `subtitle` | No | repository 名、domain 名などの補助表示 |
| `url` | No | 関連 URL |
| `raw_ref` | No | `include_raw_refs=true` の場合のみ |
| `metadata` | Yes | source 固有フィールド |

### source ごとの item

| source | kind | dataset | 時刻列 | duration |
|---|---|---|---|---|
| `spotify` | `music_play` | `spotify.plays` | `played_at_utc` | `play_ms` から算出できる場合のみ |
| `browser_history` | `page_view` | `browser_history.page_views` | `started_at_utc` | `ended_at_utc` がある場合のみ |
| `youtube` | `youtube_watch` | `youtube.watch_events` | `watched_at_utc` | watch event の duration がある場合のみ |
| `github` | `github_commit` | `github.commits` | `committed_at_utc` | なし |
| `github` | `github_pull_request` | `github.pull_requests` | `updated_at_utc` | なし |

GitHub Pull Request の「レビュー中だった時間」など、現 dataset に直接根拠がない duration は作らない。

## Correlations

`correlations` は関連または重複候補の注釈であり、`items` の削除や統合は行わない。

```json
{
  "correlation_id": "corr_youtube_browser_001",
  "kind": "same_activity_candidate",
  "event_ids": [
    "browser_history:page_view:pv_123",
    "youtube:watch_event:yt_456"
  ],
  "confidence": 0.95,
  "reason": "same_youtube_video_url_within_120_seconds"
}
```

### 初期ルール

| 対象 | 条件 | `reason` | `confidence` |
|---|---|---|---:|
| Browser History + YouTube | 同じ YouTube video URL かつ開始時刻差が120秒以内 | `same_youtube_video_url_within_120_seconds` | `0.95` |
| Browser History + YouTube | URL が YouTube watch URL で、video id 不明、開始時刻差が120秒以内 | `youtube_url_near_watch_event` | `0.75` |

correlation threshold は固定値から始め、設定値として外に出さない。調整が必要になった場合は仕様を更新する。

## Gaps

`gaps` は `items` に混ぜず、別配列で返す。

```json
{
  "gap_id": "gap_20260628_1032_1248",
  "kind": "no_observed_events_gap",
  "start_utc": "2026-06-28T01:32:00Z",
  "end_utc": "2026-06-28T03:48:00Z",
  "start_local": "2026-06-28T10:32:00+09:00",
  "end_local": "2026-06-28T12:48:00+09:00",
  "duration_minutes": 136,
  "preceded_by_event_id": "spotify:play:abc123",
  "followed_by_event_id": "github:commit:def456"
}
```

`no_observed_events_gap` は「観測イベントがない」ことだけを意味する。「何もしていなかった」と断定しない。

gap 判定は `items` の `started_at_utc` を使う。`ended_at_utc` があるイベントでも、長時間占有していたと断定せず、終了時刻を gap 計算には使わない。duration を考慮する必要が出た場合は別仕様として更新する。

## Daily Summaries

Google Health は時刻解像度が異なるため、`items` へ混ぜず `daily_summaries.google_health` に置く。

```json
{
  "daily_summaries": {
    "google_health": {
      "date": "2026-06-28",
      "timezone": "Asia/Tokyo",
      "resting_heart_rate_bpm": 53,
      "sleep": {
        "asleep_minutes": 352,
        "in_bed_minutes": 435,
        "started_at_local": "2026-06-27T23:48:00+09:00",
        "ended_at_local": "2026-06-28T07:03:00+09:00"
      },
      "steps": 8120,
      "active_energy_kcal": 420
    }
  }
}
```

睡眠の開始・終了が取得できる場合でも、タイムライン item にはしない。日次健康状態として添付する。

## Coverage

`coverage` は、AI エージェントが「イベントが少ない日」と「データソースが取得できていない日」を区別するために返す。

```json
{
  "coverage": {
    "spotify": {
      "included": true,
      "event_count": 54,
      "status": "ok"
    },
    "youtube": {
      "included": true,
      "event_count": 12,
      "status": "ok"
    },
    "browser_history": {
      "included": true,
      "event_count": 89,
      "status": "ok"
    },
    "github": {
      "included": true,
      "event_count": 21,
      "status": "ok"
    },
    "google_health": {
      "included": true,
      "event_count": 0,
      "status": "ok",
      "summary_available": true
    }
  }
}
```

### status

| 値 | 説明 |
|---|---|
| `ok` | 正常に取得できた |
| `excluded` | `sources` で除外された |
| `not_available` | 対象 dataset または summary が存在しない |
| `error` | query 実行に失敗した |

source の query が失敗した場合、原則としてリクエスト全体を失敗させる。ただし将来 partial response を許容する場合は、`coverage.{source}.status=error` と `warnings` を追加する仕様に更新する。

## ソート規則

`items` はサーバー側で必ず次の順にソートする。

1. `started_at_utc` 昇順
2. 同時刻の場合は source priority
3. さらに同一の場合は `event_id` 昇順

source priority:

1. `browser_history`
2. `youtube`
3. `spotify`
4. `github`

Browser History と YouTube が同一秒にある場合、ページを開いてから watch event が生成される流れを読みやすくするため、Browser History を先に置く。

## Validation

| 対象 | ルール | エラー |
|---|---|---|
| `date` | `YYYY-MM-DD` 形式 | `invalid_date: expected YYYY-MM-DD` |
| `timezone` | IANA timezone として解決できる | `invalid_timezone: unknown timezone` |
| `sources` | 許可値のみ | `invalid_sources: unknown source` |
| `gap_minutes` | `0 <= value <= 1440` | `invalid_gap_minutes: expected 0..1440` |
| `limit` | `1 <= value <= 2000` | `invalid_limit: expected 1..2000` |

API エラー形式は Backend の既存規約に合わせる。

## 実装配置

```text
backend/
├── api/
│   ├── timeline.py
│   └── schemas/timeline.py
├── domain/tools/timeline/
│   └── daily.py
├── infrastructure/database/
│   └── timeline_queries.py
├── infrastructure/repositories/
│   └── timeline_repository.py
└── usecases/tools/factory.py
```

責務:

| 層 | 責務 |
|---|---|
| API | query parameter validation、HTTP response |
| MCP Tool | input schema、ToolRegistry 経由の実行 |
| Repository | source 別 query の呼び出し、正規化、ソート、correlation、gap、coverage 生成 |
| Database queries | DuckDB SQL と Parquet path 解決 |

API と MCP で別ロジックを持たない。両方とも同じ Repository / UseCase を呼ぶ。
ただし、MCP のみ呼び出し境界で compact projection を適用する。

## 非責務

Daily Timeline では以下を行わない。

- AI 的な認知分析
- 集中、疲労、感情、作業意図などの推論
- Browser History と YouTube のイベント自動統合または削除
- Google Health の日次サマリをタイムライン item に変換すること
- GitHub PR のレビュー時間など、現在の dataset から根拠を持てない duration の生成
- 既存 MCP Tool を内部で逐次呼び出して統合する実装

## テスト観点

| 種別 | 観点 |
|---|---|
| Unit | timezone から UTC range を生成できる |
| Unit | source item を共通 shape に正規化できる |
| Unit | `started_at_utc` と source priority で安定ソートできる |
| Unit | Browser History と YouTube の correlation を生成できる |
| Unit | `gap_minutes` 以上の `no_observed_events_gap` を生成できる |
| Unit | Google Health を `daily_summaries` に置き、`items` に混ぜない |
| Integration | REST API が完全形、MCP Tool が event_id を省いた compact 表現を返す |
| Integration | local parquet root 優先と R2 fallback が既存 path resolver と同じ規則で動く |
| Contract | `items[*].raw_ref.dataset_id` が Dataset Catalog の `dataset_id` と一致する |
