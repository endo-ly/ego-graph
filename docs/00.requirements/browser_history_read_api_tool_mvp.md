# 要件定義: Browser History Read API / Tool MVP

## 1. Summary

- やりたいこと: Browser History の page view データを、Spotify と同様に Tool と Data API から参照できるようにする
- 理由: 「最近何を見たか」の具体確認と、「どのサイトをよく見ていたか」の傾向把握を、LLM と直接 API の両方から行えるようにするため
- 対象: `events/browser_history/page_views` を参照する backend の Tool / Data API
- 優先: 高。browser history ingest の次の利用価値を作るための MVP とする

## 2. Purpose (WHY)

- いま困っていること：
  - browser history は収集・保存できても、参照手段がなく実際の活用につながっていない
  - 「最近見たページ」と「よく見たサイト」の両方を確認したいが、現状は R2 / Parquet を直接読む必要がある
  - LLM から browser history を扱えず、Spotify や GitHub と同列に分析できない
- できるようになったら嬉しいこと：
  - 指定期間に見たページを page view 単位でそのまま確認できる
  - 指定期間で閲覧の多い domain をランキングで確認できる
  - chat tool と REST API の両方から同じデータにアクセスできる
- 成功すると何が変わるか：
  - browser history が「保存されているだけのデータ」ではなく、日常的に参照できるデータソースになる
  - 「最近何を見たか」と「どのサイトに偏っていたか」を軽く振り返れる
  - 後続の検索・統計拡張や MCP 化に進みやすくなる

## 3. Requirements (WHAT)

### 機能要件

- browser history の read 機能として、以下 2 つを提供する
  - `page-views`: 指定期間の page view 一覧を返す
  - `top-domains`: 指定期間の domain 別 page view ランキングを返す
- read 対象は `events/browser_history/page_views` とする
- 生の visit ではなく、2 秒クラスタ済みの page view を主データとして扱う
- Data API と Tool は同等の意味を持つ入力・出力を提供する
- フィルタは MVP では `browser` と `profile` をサポートする
- `source_device` は保存されていても、MVP の検索条件には含めない
- domain 集計は `url` から抽出した `hostname` を用いる
- URL / title はそのまま返却対象に含める

### 期待する挙動

#### 3.1 Page Views

- API: `GET /v1/data/browser-history/page-views`
- Tool: `get_page_views`
- 指定期間の page view を `started_at_utc DESC` で返す
- 日付境界は UTC 基準とし、`start_date` / `end_date` はどちらも当日を含む
- 入力:
  - `start_date` 必須
  - `end_date` 必須
  - `limit` 任意
  - `browser` 任意
  - `profile` 任意
- 出力:
  - `page_view_id`
  - `started_at_utc`
  - `ended_at_utc`
  - `url`
  - `title`
  - `browser`
  - `profile`
  - `transition`
  - `visit_span_count`
- `visit_span_count` は、その page view に畳み込まれた raw visit 数を表す
- raw の `visit_id` / `referring_visit_id` は返さない

#### 3.2 Top Domains

- API: `GET /v1/data/browser-history/top-domains`
- Tool: `get_top_domains`
- 指定期間の domain ごとの page view 数をランキングで返す
- 入力:
  - `start_date` 必須
  - `end_date` 必須
  - `limit` 任意
  - `browser` 任意
  - `profile` 任意
- 集計単位:
  - `page_view_count`: domain に属する page view 数
  - `unique_urls`: domain 内で見た異なる URL 数
- `hostname` を抽出できない URL は domain 集計対象から除外する
- 出力:
  - `domain`
  - `page_view_count`
  - `unique_urls`
- 並び順:
  - `page_view_count DESC`
  - 同率時は `unique_urls DESC`
  - さらに同率時は `domain ASC`

### 画面/入出力（ある場合）

#### Page Views request 例

```text
GET /v1/data/browser-history/page-views?start_date=2026-03-01&end_date=2026-03-24&limit=50&browser=edge&profile=Default
```

#### Page Views response 例

```json
[
  {
    "page_view_id": "browser_history_page_view_xxx",
    "started_at_utc": "2026-03-24T10:15:12Z",
    "ended_at_utc": "2026-03-24T10:15:13Z",
    "url": "https://github.com/owner/repo/pull/79",
    "title": "fix(browser-history): remove visit count and expand initial sync",
    "browser": "edge",
    "profile": "Default",
    "transition": "link",
    "visit_span_count": 2
  }
]
```

#### Top Domains request 例

```text
GET /v1/data/browser-history/top-domains?start_date=2026-03-01&end_date=2026-03-24&limit=20&browser=edge&profile=Default
```

#### Top Domains response 例

```json
[
  {
    "domain": "github.com",
    "page_view_count": 42,
    "unique_urls": 18
  }
]
```

## 4. Scope

### 今回やる（MVP）

- `page-views` と `top-domains` の Data API を追加する
- `get_page_views` と `get_top_domains` の Tool を追加する
- `browser` / `profile` フィルタをサポートする
- page view 一覧と domain ランキングを返す
- browser history 用 query / repository / schema / tests を追加する

### 今回やらない（Won't）

- raw visit を直接参照する API / Tool
- `source_device` フィルタ
- 時系列 stats API (`period` ベース集計)
- domain のトレンド推移
- URL / title の全文検索
- 滞在時間推定
- eTLD+1 など高度な domain 正規化

### 次回以降（あれば）

- domain trend / day-week-month 集計の追加
- URL / title 検索
- `source_device` フィルタ
- YouTube など特定 domain の派生 API
- privacy 要件に応じた URL / title のマスキング方針追加

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 期間を指定する | `start_date` と `end_date` を指定できる | relative date やプリセット期間を指定できる |
| 閲覧履歴を確認する | `page-views` で page view 一覧を返す | URL / title で検索できる |
| 傾向を把握する | `top-domains` で domain ランキングを返す | 日別・週別の trend を見られる |
| 条件で絞る | `browser` / `profile` で絞れる | `source_device` でも絞れる |
| LLM から使う | Tool から同等の参照ができる | MCP / Skill からも共通利用できる |

## 6. Acceptance Criteria

- Given browser history の page view が保存済み, When `page-views` API または `get_page_views` を呼ぶ, Then 指定期間の page view が `started_at_utc` 降順で返る
- Given `browser=edge` を指定, When `page-views` または `top-domains` を呼ぶ, Then Edge のデータのみが返る
- Given `profile=Default` を指定, When `page-views` または `top-domains` を呼ぶ, Then その profile のデータのみが返る
- Given 指定期間に複数の page view がある, When `top-domains` を呼ぶ, Then `hostname` 単位の `page_view_count` と `unique_urls` が返る
- Given 指定期間にデータが 0 件, When `page-views` または `top-domains` を呼ぶ, Then `200` と空配列を返す

## 7. 例外・境界

- 失敗時（通信/保存/権限）：
  - 認証失敗時は既存 Data API と同様に `401/403`
  - 不正な日付や limit は `400` または `422` のバリデーションエラー
  - query 実行失敗時は内部エラーとして扱う
- 空状態（データ0件）：
  - `page-views` も `top-domains` も空配列を返す
- 上限（文字数/件数/サイズ）：
  - `limit` は必須ではないが上限を持つ
  - MVP の既定値候補は `page-views=50`, `top-domains=20`
  - MVP の上限候補は `page-views=200`, `top-domains=100`
- 既存データとの整合（互換/移行）：
  - 新規 read 機能追加のため既存互換は不要
  - 対象 dataset は既存 ingest が生成する `events/browser_history/page_views` をそのまま使用する
  - `start_date` / `end_date` は UTC 日付の両端を含む条件として扱う

## 8. Non-Functional Requirements (FURPS)

- Performance：期間・パーティションを絞ったクエリで、日常的な問い合わせに耐えること
- Reliability：ingest 済みの page view をそのまま参照し、同一条件では安定した結果が返ること
- Usability：API 名 / Tool 名から返却内容が直感的に分かること
- Security/Privacy：browser history は高センシティブだが、MVP では Edge 利用前提で URL / title をそのまま返す
- Constraints（技術/期限/外部APIなど）：集計は現在保存済みの page view スキーマに従い、raw visit 前提の指標は扱わない

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

- Risk：Chrome History API の同期仕様により、保存データが必ずしもローカル端末由来とは限らない可能性がある
- Assumption：MVP では URL / title を返しても問題ない運用前提である
- Issue：domain 抽出失敗時の扱いと、将来の hostname 正規化方針は別途詰める必要がある
- Dependency：`events/browser_history/page_views` dataset、backend の Tool / Data API 基盤、DuckDB / R2 クエリ基盤

## 10. Reference

- [browser_history_collection.md](./browser_history_collection.md)
- [browser-history.md](../10.architecture/03-ingest/browser-history.md)
- [data.py](../../../backend/api/data.py)
- [stats.py](../../../backend/domain/tools/spotify/stats.py)
- [history.ts](../../../browser-extension/chromium-history/src/background/history.ts)
