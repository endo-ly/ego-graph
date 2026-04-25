# YouTube データソース

## データタイプ判定

- **タイプ**: 時系列・行動履歴
- **主用途**: DuckDB分析

---

## 1. 概要

### 1.1 データの性質

| 項目 | 値 |
|---|---|
| **タイプ** | 時系列・行動履歴 |
| **粒度** | Atomic (watch event単位) |
| **更新頻度** | Browser History に準ずる |
| **センシティビティ** | Medium (視聴履歴を含む) |
| **主な用途** | 分析（DuckDB） |

### 1.2 概要説明

YouTube は `browser_history` のフィルタ結果ではなく、独立した行動履歴データソースとして扱う。canonical な保存単位は watch event とし、通常動画と Shorts を同じ履歴ドメインに含める。

現時点の収集起点は Browser History だが、公開データソース名は常に `youtube` とする。将来 `Google Activity` を復活させる場合も別データソースを増やすのではなく、同じ `youtube` ドメインに統合する。

---

## 2. データフロー全体像

```text
[Browser History page views]
         ↓
 [Workflow: youtube_ingest_workflow]
         ↓
    [Collector: sync_id 単位で Browser History page views を読込]
         ↓
    [Transform: video_id / content_type 正規化]
         ↓
    [Enrichment: YouTube Data API で metadata 解決]
         ↓
    [Storage: R2へ保存]
         ├── Events Parquet (watch events)
         ├── Master Parquet (videos)
         ├── Master Parquet (channels)
         └── State JSON
         ↓
    [Backend/DuckDB: YouTube専用Toolで分析]
```

### 2.1 source 境界

| 層 | 扱い |
|---|---|
| **収集元** | `browser_history` |
| **論理データソース** | `youtube` |
| **公開インターフェース** | REST / MCP ともに `youtube` として公開 |
| **将来拡張** | `google_activity` を同一ドメインに統合可能 |

---

## 3. 入力データ構造

### 3.1 データ取得元

| 項目 | 説明 |
|---|---|
| **取得方法** | Browser History 由来 page view の二次変換 |
| **上流データ** | `events/browser_history/page_views/` |
| **認証方式** | なし（上流で取得済み） |
| **必要な情報** | `sync_id`, URL, title, started_at_utc, source_device, browser, profile |

### 3.2 入力スキーマ

#### 基本情報（必須フィールド）

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `sync_id` | string | Yes | Browser History 同期単位の識別子 | `"sync_123"` |
| `page_view_id` | string | Yes | 上流 page view の一意識別子 | `"pv_123"` |
| `started_at_utc` | datetime | Yes | 閲覧開始時刻 | `"2026-04-21T12:00:00Z"` |
| `url` | string | Yes | 閲覧URL | `"https://www.youtube.com/watch?v=abc123"` |
| `title` | string | Yes | ページタイトル | `"Some Video - YouTube"` |
| `browser` | string | Yes | ブラウザ種別 | `"edge"` |
| `profile` | string | Yes | ブラウザプロファイル | `"Default"` |
| `source_device` | string | Yes | 送信元デバイス | `"desktop-main"` |

### 3.3 watch event 判定対象

watch event として扱うのは、動画を一意に特定できる URL のみとする。

正式対象:

- `watch?v=...`
- `youtu.be/...`
- `shorts/...`

対象外:

- channel ページ
- playlist 一覧ページ
- feed / search / home
- 視聴対象動画を一意に決められない URL

### 3.4 metadata 解決

`video_id` は URL から抽出し、`title` は Browser History のページタイトルを一次情報として取得する。YouTube の動画ページでは通常、ブラウザ title が動画タイトルに相当するため、`video_title` の一次情報として利用できる。一方で、Browser History API の原事実としては `title` は optional であり、記録タイミングにも依存する。本パイプラインでは、YouTube 抽出の入力として受ける page view レコードでは `title` を必須入力として扱う。また、ページ title は将来変更される可能性があるため、正規値を保証する情報とはみなさない。そのため、YouTube Data API v3 を正式な metadata 解決手段として採用する。

`title` の扱い:

- Browser History で取得した `title` は視聴時点のページタイトルとして保存価値がある
- YouTube 上の動画タイトルは後から変更される可能性がある
- そのため、`title` は一次情報として保持しつつ、正式な metadata は YouTube Data API で解決する

役割分担:

- URL から `video_id` を抽出する
- Browser History の `title` を `video_title` の一次情報として扱う
- `video_id` をキーに動画 metadata を取得する
- `channel_id`, `channel_name` を確定し、必要に応じて `video_title` を補正する
- `channel_id` をキーにチャンネル metadata を取得する

---

## 4. Parquetスキーマ

### 4.1 Watch Events (Events)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `watch_event_id` | STRING | watch event の一意識別子 | システム生成 |
| `watched_at_utc` | TIMESTAMP | 視聴時刻 (UTC) | `started_at_utc` |
| `video_id` | STRING | YouTube 動画ID | URL正規化 |
| `video_url` | STRING | 正規化済み動画URL | URL正規化 |
| `video_title` | STRING | 動画タイトル | `title` または YouTube Data API |
| `channel_id` | STRING | チャンネルID | YouTube Data API |
| `channel_name` | STRING | チャンネル名 | YouTube Data API |
| `content_type` | STRING | `video` / `short` | URL正規化 |
| `source` | STRING | 収集 source | 固定値: `browser_history` |
| `source_event_id` | STRING | 上流イベント識別子 | `page_view_id` |
| `source_device` | STRING | 送信元デバイス | `source_device` |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 | システム生成 |
| `browser_history_sync_id` | STRING | 上流同期識別子 | `sync_id` |

### 4.2 Videos (Master)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `video_id` | STRING | 動画ID | URL正規化 |
| `title` | STRING | 動画タイトル | YouTube Data API |
| `channel_id` | STRING | チャンネルID | YouTube Data API |
| `channel_name` | STRING | チャンネル名 | YouTube Data API |
| `content_type` | STRING | `video` / `short` | URL正規化 |
| `duration_seconds` | INT | 動画長（秒） | YouTube Data API |
| `view_count` | INT | 再生数 | YouTube Data API |
| `like_count` | INT | 高評価数 | YouTube Data API |
| `comment_count` | INT | コメント数 | YouTube Data API |
| `published_at` | TIMESTAMP | 公開日時 | YouTube Data API |
| `thumbnail_url` | STRING | サムネイルURL | YouTube Data API |
| `description` | STRING | 説明文 | YouTube Data API |
| `category_id` | STRING | カテゴリID | YouTube Data API |
| `tags` | ARRAY<STRING> | タグ | YouTube Data API |
| `updated_at` | TIMESTAMP | 更新時刻 | システム生成 |

### 4.3 Channels (Master)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `channel_id` | STRING | チャンネルID | YouTube Data API |
| `channel_name` | STRING | チャンネル名 | YouTube Data API |
| `subscriber_count` | INT | 登録者数 | YouTube Data API |
| `video_count` | INT | 動画数 | YouTube Data API |
| `view_count` | INT | 総再生数 | YouTube Data API |
| `published_at` | TIMESTAMP | 開設日時 | YouTube Data API |
| `thumbnail_url` | STRING | サムネイルURL | YouTube Data API |
| `description` | STRING | 説明文 | YouTube Data API |
| `country` | STRING | 国コード | YouTube Data API |
| `updated_at` | TIMESTAMP | 更新時刻 | システム生成 |

### 4.4 パーティション

- **Events パーティションキー**: `year`, `month`
- **理由**: watch event は時系列で参照されるため
- **Master 保存方式**: `video_id` / `channel_id` 単位で upsert した単一 snapshot

---

## 5. R2保存先

### 5.1 ディレクトリ構造

```text
s3://egograph/
  ├── events/youtube/
  │   └── watch_events/
  │       └── year=YYYY/
  │           └── month=MM/
  │               └── sync_id={sync_id}.parquet
  ├── master/youtube/
  │   ├── videos/
  │   │   └── data.parquet
  │   └── channels/
  │       └── data.parquet
  └── state/
      └── youtube/
          └── browser_history_syncs/
              └── {sync_id}.json
```

### 5.2 保存パス例

- **Watch Events**: `s3://egograph/events/youtube/watch_events/year=2026/month=04/sync_id=abc123.parquet`
- **Videos Master**: `s3://egograph/master/youtube/videos/data.parquet`
- **Channels Master**: `s3://egograph/master/youtube/channels/data.parquet`
- **Raw**: `s3://egograph/raw/browser_history/2026-04-21T120000.json` を原本として参照
- **State**: `s3://egograph/state/youtube/browser_history_syncs/abc123.json`

---

## 6. 検索・活用シナリオ

| ユーザーの質問 | 意図 | SQLクエリ例 |
|---|---|---|
| 最近何の動画を見ていた？ | 事実列挙 | `SELECT watched_at_utc, video_title, channel_name FROM youtube_watch_events WHERE watched_at_utc::DATE BETWEEN DATE '2026-04-01' AND DATE '2026-04-30' ORDER BY watched_at_utc DESC LIMIT 20;` |
| 今月はどれくらい YouTube を見ている？ | 定量分析 | `SELECT DATE_TRUNC('day', watched_at_utc) AS period_start, COUNT(*) AS watch_event_count, COUNT(DISTINCT video_id) AS unique_video_count, COUNT(DISTINCT channel_id) AS unique_channel_count FROM youtube_watch_events WHERE watched_at_utc::DATE BETWEEN DATE '2026-04-01' AND DATE '2026-04-30' GROUP BY 1 ORDER BY 1;` |
| 最近よく見ている動画は？ | パターン発見 | `SELECT video_id, video_title, channel_name, COUNT(*) AS watch_event_count FROM youtube_watch_events WHERE watched_at_utc::DATE BETWEEN DATE '2026-04-01' AND DATE '2026-04-30' GROUP BY 1, 2, 3 ORDER BY watch_event_count DESC LIMIT 10;` |
| 最近よく見ているチャンネルは？ | パターン発見 | `SELECT channel_id, channel_name, COUNT(*) AS watch_event_count, COUNT(DISTINCT video_id) AS unique_video_count FROM youtube_watch_events WHERE watched_at_utc::DATE BETWEEN DATE '2026-04-01' AND DATE '2026-04-30' GROUP BY 1, 2 ORDER BY watch_event_count DESC LIMIT 10;` |

---

## 7. 設計判断・技術選定

### 7.1 検討した案

| 案 | 利点 | 欠点 | 採用 |
|---|---|---|---|
| `browser_history` に domain filter を追加する | 実装差分が小さい | YouTube の分析価値が Tool と schema に表現されない | No |
| `youtube` を独立データソース化し watch event を持つ | 公開仕様が明快、将来 source 統合しやすい | ingestion に正規化責務が増える | **Yes** |
| 集計結果だけ別 dataset に持つ | 軽量 | 後から分析軸を増やしにくい | No |

### 7.2 採用理由

YouTube は単なるドメインフィルタではなく、動画・チャンネル・Shorts を軸にした独立分析対象として扱う価値が高い。したがって、公開契約を `youtube` に寄せ、watch event を canonical に置く方が長期的な保守性と分析価値の両方に優れる。

### 7.3 source 統合方針

- 公開上のデータソース名は常に `youtube`
- 収集 source は内部列 `source` で保持
- 将来 `google_activity` を復活させても、同じ `youtube` ドメインに統合する
- source 差分は ingestion で吸収し、公開 Tool には露出しない

### 7.4 Tool 仕様方針

公開 Tool は以下の 4 本とする:

1. `get_youtube_watch_events`
2. `get_youtube_watching_stats`
3. `get_youtube_top_videos`
4. `get_youtube_top_channels`

共通方針:

- ranking の基準は `watch_event_count`
- `get_youtube_watching_stats` の指標は `watch_event_count`, `unique_video_count`, `unique_channel_count`
- `active_days` と視聴時間ベース指標は採用しない
- `content_type` はレスポンスに含めるが、入力 filter には含めない
- `source`, `source_event_id`, `browser`, `profile` は公開しない

---

## 11. 実装時の考慮事項

### 11.1 エッジケース

- URL から `video_id` を一意に抽出できない page view は除外する
- Shorts と通常動画は同一 dataset に保存するが、`content_type` で区別する
- metadata 解決結果と page title が不一致でも、正式値は YouTube Data API を優先する

### 11.2 制約・制限

- Browser History 由来の source では、視聴時間の正確な推定は保証しない
- source が増えた場合は dedupe ルールが必要になる

### 11.3 将来拡張

- `google_activity` の source 追加
- source 間重複排除ロジックの正式化
- YouTube metadata の追加項目拡張

---

## 12. サンプルデータ

### 12.1 入力データ例 (Browser History Page View)

```json
{
  "sync_id": "browser_sync_20260421T120000Z",
  "page_view_id": "pv_123",
  "started_at_utc": "2026-04-21T12:00:00Z",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up - YouTube",
  "browser": "edge",
  "profile": "Default",
  "source_device": "desktop-main"
}
```

### 12.2 Parquet行例 (Watch Event)

```json
{
  "watch_event_id": "550e8400-e29b-41d4-a716-446655440000",
  "watched_at_utc": "2026-04-21T12:00:00Z",
  "video_id": "dQw4w9WgXcQ",
  "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "video_title": "Rick Astley - Never Gonna Give You Up",
  "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
  "channel_name": "Rick Astley",
  "content_type": "video",
  "source": "browser_history",
  "source_event_id": "pv_123",
  "source_device": "desktop-main",
  "browser_history_sync_id": "browser_sync_20260421T120000Z",
  "ingested_at_utc": "2026-04-21T12:10:00Z"
}
```

---

## 13. 次のステップ

### 実装状況

- [x] データソース境界の設計
- [x] Tool 仕様の設計
- [x] URL 抽出・正規化実装
- [x] YouTube Data API 連携実装
- [x] Parquet保存実装
- [x] Backend Tool 実装
- [x] テスト完了

### 未実装機能

- [ ] `google_activity` source の統合
- [ ] source 間 dedupe ルール

---

## 参考

- [Browser History データソース](./browser-history.md)
- [Pipelines Service Architecture](./architecture.md)
- [YouTube 視聴履歴収集セットアップガイド](../../70.knowledge/youtube_watch_history_setup.md)
