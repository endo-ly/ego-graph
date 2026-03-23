# Browser History Ingest Design

## 概要

Chromium の `chrome.history` API は、同じ URL に対して短時間に複数の distinct visit を返すことがある。特に GitHub の PR 画面や YouTube など、画面内遷移や再読込が多いページでは `link` と `reload` が数十ms〜数秒の間隔で連続する。

そのまま visit 単位で `events` に保存すると、分析や UI では「同じページが連続で大量に並ぶ」ように見えやすい。一方で、収集段階で完全に捨ててしまうと、後から History API の挙動や再処理を検証しづらくなる。

このため browser history では、`raw` に受信 payload JSON を保存し、`events` には visit を 2 秒窓で畳み込んだ page view を保存する。

## 責務分離

### `raw/browser_history/...`

- 受信 payload JSON の原本
- 拡張機能が送ってきたデータをそのまま保全する
- 必要ならここから visit 行 Parquet を再生成できる

### `events/browser_history/page_views/...`

- 2 秒以内の同一 URL 連続 visit を畳んだ page view
- UI や分析で日常的に使う主データ
- browser history の「見た目上の重複」を吸収したデータ

## 背景

### History API の返り値の性質

- `chrome.history.search()` は URL 単位の `HistoryItem` を返す
- `chrome.history.getVisits({ url })` はその URL に紐づく visit 群を返す
- 同一 URL でも短時間に別 `visit_id` が複数発生することがある
- `visitCount` は visit 単位の値ではなく URL 全体の累積回数に近く、1 行の visit 事実としては不適切

### そのまま保存した場合の問題

- ページ一覧・時系列表示でノイズが多い
- 集計結果が人間の直感とずれやすい
- `reload` 由来の連続 visit がページ閲覧数を過大に見せる

## 検討した案

### 案1: 拡張機能側で除外する

- 利点: 通信量と保存量を減らせる
- 欠点: 収集時点で事実を捨てることになり、ルール変更や再評価が難しい

### 案2: `raw` は原本、`events` は page view にする

- 利点: ストレージ構造が `raw` / `events` の 2 層で分かりやすい
- 利点: UI や分析で使う主データが最初からノイズ少なめになる
- 利点: 原本は `raw` に残るため、必要なら visit 行 Parquet を再生成できる
- 欠点: `events` は visit の完全な写像ではなくなる

### 案3: `events` は visit のまま保持し、別 dataset に page view を追加する

- 利点: 生の visit と派生 page view を両方クエリできる
- 欠点: compacted を含めて dataset が増え、利用者にとって分かりにくい

## 採用方針

案2を採用する。

- `raw/browser_history/...`
  - 受信 payload JSON の原本
- `events/browser_history/page_views/...`
  - 2 秒以内の同一 URL 連続 visit を畳んだ page view

これにより、「生データの保全」と「日常的に使うデータの見やすさ」を両立する。

## 畳み込みルール

### グルーピングキー

以下が一致する visit を同じ系列として扱う。

- `source_device`
- `browser`
- `profile`
- `url`

### 時間窓

- 直前 visit との差が `2秒以内` なら同一クラスタに含める
- `2秒超` なら新しい page view を開始する

2 秒を採用した理由:

- 1 秒だと GitHub などの短い連続遷移を取りこぼしやすい
- 2 秒なら実観測された 49ms / 102ms / 217ms / 1.97s 付近を自然に吸収できる
- それ以上広げると、本当の再訪問を潰し始めるリスクが上がる

### 代表 transition

クラスタ内で複数の transition が混在する場合は、以下の優先順位で代表値を選ぶ。

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

## page view スキーマ

`events/browser_history/page_views` では以下の列を持つ。

- `page_view_id`
- `started_at_utc`
- `ended_at_utc`
- `url`
- `title`
- `browser`
- `profile`
- `source_device`
- `transition`
- `visit_span_count`
- `synced_at_utc`
- `ingested_at_utc`

visit 単位の `visit_id` や `referring_visit_id` は `events` には持たせず、必要なら `raw` から再構成する。

## 副作用と既知の制約

- `events` は visit の 1:1 写像ではなく、page view へ正規化された主データになる
- 1000 件チャンク境界をまたぐ極端なケースでは、本来 1 つにまとまるクラスタが分断される可能性がある
- 現時点ではシンプルさを優先し、payload 単位のクラスタリングとする

## 将来の見直しポイント

- sync 全体単位でのクラスタリングに移行し、チャンク境界問題を解消する
- page view とは別に visit 派生 Parquet を持つかどうか再評価する
- UI や分析要件に応じて時間窓を設定化する

## 関連ドキュメント

- [browser_history_collection.md](../../00.project/features/browser_history_collection.md)
