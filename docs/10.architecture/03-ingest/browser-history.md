# Browser History データソース

## データタイプ判定

- **タイプ**: 時系列・行動履歴
- **主用途**: DuckDB分析

---

## 1. 概要

### 1.1 データの性質

| 項目 | 値 |
|---|---|
| **タイプ** | 時系列・行動履歴 |
| **粒度** | Atomic (page view単位) |
| **更新頻度** | リアルタイム (拡張機能経由) |
| **センシティビティ** | Medium (閲覧履歴を含む) |
| **主な用途** | 分析（DuckDB） |

### 1.2 概要説明

Chromiumベースのブラウザから閲覧履歴を収集し、2秒窓で畳み込んだpage viewとして保存する。短時間の連続visit（リロードや画面内遷移）をノイズとして吸収し、分析しやすい主データを提供する。

---

## 2. データフロー全体像

```
[Chrome Extension]
         ↓
    [Collector: chrome.history API取得]
         ↓
    [POST /v1/ingest/browser-history]
         ↓
    [Pipelines Service: Transform + compact enqueue]
         ↓
    [Storage: R2へ保存]
         ├── Raw JSON (監査用)
         └── Parquet (分析用: page views)
         ↓
    [Backend/DuckDB: マウント・分析]
```

---

## 3. 入力データ構造

### 3.1 データ取得元

| 項目 | 説明 |
|---|---|
| **取得方法** | Browser Extension |
| **API** | `chrome.history.search()`, `chrome.history.getVisits()` |
| **認証方式** | なし (拡張機能権限) |
| **必要なスコープ** | `history` permission |

### 3.2 入力スキーマ (chrome.history API)

#### HistoryItem (URL単位)

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `id` | string | Yes | 一意識別子 | `"abc123"` |
| `url` | string | Yes | ページURL | `"https://github.com/owner/repo"` |
| `title` | string | No | ページタイトル | `"GitHub - repo"` |
| `lastVisitTime` | number | No | 最終訪問時刻 (epoch ms) | `1704067200000` |
| `visitCount` | number | No | 累積訪問回数 | `10` |

#### VisitItem (visit単位)

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `visitId` | string | Yes | visit一意識別子 | `"12345"` |
| `visitTime` | number | No | 訪問時刻 (epoch ms) | `1704067200000` |
| `referringVisitId` | string | No | 遷移元visit ID | `"12344"` |
| `transition` | string | Yes | 遷移タイプ | `"link"`, `"reload"`, `"typed"` |

---

## 4. Parquetスキーマ

### 4.1 Page View テーブル定義

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `page_view_id` | STRING | 一意識別子 | システム生成 (UUID) |
| `started_at_utc` | TIMESTAMP | 閲覧開始時刻 (UTC) | クラスタ内最小 `visitTime` |
| `ended_at_utc` | TIMESTAMP | 閲覧終了時刻 (UTC) | クラスタ内最大 `visitTime` |
| `url` | STRING | ページURL | `url` |
| `title` | STRING | ページタイトル | `title` |
| `browser` | STRING | ブラウザ名 | 拡張機能から取得 |
| `profile` | STRING | ブラウザプロファイル | 拡張機能から取得 |
| `source_device` | STRING | 送信元デバイス | 拡張機能から取得 |
| `transition` | STRING | 代表遷移タイプ | 優先順位で選択 |
| `visit_span_count` | INT | 畳み込み元visit数 | クラスタサイズ |
| `synced_at_utc` | TIMESTAMP | 同期時刻 (UTC) | 受信時刻 |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 (UTC) | システム生成 |

### 4.2 パーティション

- **パーティションキー**: `year`, `month`
- **理由**: 時系列データのクエリ効率向上

---

## 5. R2保存先

### 5.1 ディレクトリ構造

```text
s3://ego-graph/
  ├── events/browser_history/
  │   └── page_views/
  │       └── year=YYYY/
  │           └── month=MM/
  │               └── {uuid}.parquet
  ├── raw/browser_history/
  │   └── {timestamp}.json
  └── state/
      └── browser_history_ingest_state.json
```

### 5.2 保存パス例

- **Page Views**: `s3://ego-graph/events/browser_history/page_views/year=2024/month=01/abc123.parquet`
- **Raw**: `s3://ego-graph/raw/browser_history/2024-01-01T120000.json`
- **State**: `s3://ego-graph/state/browser_history_ingest_state.json`

---

## 6. 検索・活用シナリオ

- **事実列挙**: 特定期間に閲覧したサイト一覧
- **定量分析**: よく見るサイト、閲覧時間の集計
- **フィルタリング**: 特定ドメイン（GitHub、YouTube等）での活動履歴

---
## 7. 設計判断・技術選定

### 7.1 背景: History APIの性質

Chromium の `chrome.history` API は、同じ URL に対して短時間に複数の distinct visit を返すことがある。特に GitHub の PR 画面や YouTube など、画面内遷移や再読込が多いページでは `link` と `reload` が数十ms〜数秒の間隔で連続する。

**そのまま保存した場合の問題:**
- ページ一覧・時系列表示でノイズが多い
- 集計結果が人間の直感とずれやすい
- `reload` 由来の連続 visit がページ閲覧数を過大に見せる

### 7.2 検討した案

| 案 | 利点 | 欠点 | 採用 |
|---|---|---|---|
| **案1**: 拡張機能側で除外 | 通信量・保存量削減 | 収集時点で事実を捨てる、再評価困難 | No |
| **案2**: rawは原本、eventsはpage view | ストレージ構造が分かりやすい、UIデータがノイズ少ない、再生成可能 | eventsはvisitの完全な写像ではない | **Yes** |
| **案3**: eventsはvisitのまま、別datasetにpage view | 生のvisitと派生page viewを両方クエリ可能 | datasetが増え、利用者にとって分かりにくい | No |

### 7.3 採用理由

案2を採用。「生データの保全」と「日常的に使うデータの見やすさ」を両立するため。

### 7.4 畳み込みルール

#### グルーピングキー

以下が一致する visit を同じ系列として扱う:
- `source_device`
- `browser`
- `profile`
- `url`

#### 時間窓

- 直前 visit との差が **2秒以内** なら同一クラスタに含める
- **2秒超** なら新しい page view を開始する

**2秒を採用した理由:**
- 1秒だと GitHub などの短い連続遷移を取りこぼしやすい
- 2秒なら実観測された 49ms / 102ms / 217ms / 1.97s 付近を自然に吸収できる
- それ以上広げると、本当の再訪問を潰し始めるリスクが上がる

#### 代表 transition

クラスタ内で複数の transition が混在する場合の優先順位:

1. `typed`
2. `link`
3. `auto_bookmark`
4. `form_submit`
5. `reload`
6. `keyword`
7. `keyword_generated`
8. `manual_subframe`
9. `auto_subframe`

この優先順位により、`link` の直後に `reload` が来た場合でも、page view の代表 transition は `link` になる。

---

## 11. 実装時の考慮事項

### 11.1 副作用と既知の制約

- `events` は visit の 1:1 写像ではなく、page view へ正規化された主データになる
- 1000件チャンク境界をまたぐ極端なケースでは、本来1つにまとまるクラスタが分断される可能性がある
- 現時点ではシンプルさを優先し、payload単位のクラスタリングとする

### 11.2 将来の見直しポイント

- sync全体単位でのクラスタリングに移行し、チャンク境界問題を解消する
- page viewとは別に visit 派生 Parquet を持つかどうか再評価する
- UIや分析要件に応じて時間窓を設定化する

---

## 12. サンプルデータ

### 12.1 入力データ例 (Raw JSON)

```json
{
  "source_device": "desktop-linux",
  "browser": "chrome",
  "profile": "Profile 1",
  "items": [
    {
      "id": "abc123",
      "url": "https://github.com/owner/repo/pull/42",
      "title": "Add feature by user · Pull Request #42 · owner/repo",
      "visits": [
        { "visitId": "1", "visitTime": 1704067200000, "transition": "link" },
        { "visitId": "2", "visitTime": 1704067210000, "transition": "reload" }
      ]
    }
  ]
}
```

### 12.2 Parquet行例 (Page View)

```json
{
  "page_view_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_at_utc": "2024-01-01T00:00:00Z",
  "ended_at_utc": "2024-01-01T00:00:10Z",
  "url": "https://github.com/owner/repo/pull/42",
  "title": "Add feature by user · Pull Request #42 · owner/repo",
  "browser": "chrome",
  "profile": "Profile 1",
  "source_device": "desktop-linux",
  "transition": "link",
  "visit_span_count": 2,
  "synced_at_utc": "2024-01-01T00:01:00Z",
  "ingested_at_utc": "2024-01-01T00:02:00Z"
}
```

---

## 13. 次のステップ

### 実装状況

- [x] 拡張機能によるデータ収集
- [x] 受信 API実装
- [x] 畳み込み処理
- [x] Parquet保存
- [x] DuckDBマウント
- [x] テスト完了

### 未実装機能

- [ ] sync全体単位でのクラスタリング
- [ ] 時間窓の設定化
- [ ] visit派生Parquetの検討

---

## 参考

- [Browser History Collection 要件](../../00.requirements/browser_history_collection.md)
- [データ戦略](../01-overview/data-strategy.md)
