# 要件定義: Chromium系ブラウザ履歴収集機能

## 1. Summary

- やりたいこと: Windows PC 上の Chromium 系ブラウザ拡張から訪問履歴を収集し、EgoGraph の Data Lake に保存する
- 理由: ブラウザ行動履歴を Spotify や YouTube と同じく個人データ基盤へ統合し、時系列分析や後続の LLM/MCP 活用につなげるため
- 対象: Edge / Brave を主対象、Chrome を互換対象とする個人用ローカル導入の Chromium 拡張 + ミニPC側 Pipelines ingest endpoint
- 優先: 高。MVP では訪問履歴の確実な蓄積を最優先とし、YouTube 専用の二次利用は後続に回す

---

## 2. Purpose (WHY)

### いま困っていること
- 日々のブラウザ利用履歴がブラウザ内に閉じており、他のライフログと横断分析できない
- Edge と Brave を使い分けているため、ブラウザ別に履歴を見たい
- Windows 常駐ツールや DB 直読は配布・運用負荷が高く、個人運用に対して重い

### できるようになったら嬉しいこと
- ブラウザ起動時に前回同期以降の履歴が自動でミニPCへ送信される
- Edge / Brave / Chrome を同一実装の拡張で扱える
- URL 単位で YouTube 動画ページなども後から分析できる
- 保存済みデータを compact / local mirror / MCP へ自然に広げられる

### 成功すると何が変わるか
- 個人の Web 行動履歴が append-only で Data Lake に蓄積される
- ブラウザ別・プロファイル別・デバイス別の分析が可能になる
- 将来的に YouTube URL のみ別 dataset へ再抽出するなど、後段の派生処理を jobs サービスへ分離しやすくなる

---

## 3. Requirements (WHAT)

### 機能要件

#### 3.1 Chromium 拡張による履歴収集
- Manifest V3 ベースの Chromium 拡張を実装する
- Edge / Brave を主対象、Chrome を互換対象とする
- 拡張は `history` API を使って訪問履歴を取得する
- 取得対象は訪問履歴のみとし、ブックマーク・ダウンロード・検索語は対象外とする
- ブラウザ起動時に `last_successful_sync_at` 以降の差分履歴を取得する
- ブラウザごとに `browser` 識別子を付与して送信する
- `profile` は拡張設定で明示的に与え、MVP では送信必須とする

#### 3.2 送信・再送制御
- 拡張は起動時同期を基本とし、厳密な定刻バッチは要求しない
- 拡張は同期リクエストごとに `sync_id` を生成して送信する
- 同期失敗時は `last_successful_sync_at` を進めず、次回起動時に同範囲を再送する
- 配信方式は at-least-once を前提とし、重複吸収はサーバ側でも扱えるようにする

#### 3.3 ミニPC側の受信
- 受信口は `pipelines` に HTTP endpoint として置く
- `backend` は Browser History 書き込み口を持たず、読み取り API に集中する
- Tailscale / Tailscale Serve 経由で Windows PC から到達可能とする
- 認証は共有 `Bearer token` によるシンプルな方式とする
- `pipelines` は認証・バリデーション・リクエスト受付・変換・保存を担当し、
  受信直後に `browser_history_compact_workflow` を enqueue する
- `backend` proxy 互換は設けず、拡張機能は `pipelines` を直接叩く

#### 3.4 永続化
- 受信 payload は raw JSON として保存する
- 正規化済みイベントを Parquet として保存する
- compacted parquet は既存実装に合わせて生成する
- R2 を正本とし、必要に応じて compacted parquet をローカル mirror に同期する
- 既存 ingest と同じ append-only 方針に合わせる

#### 3.5 エラー処理と同期状態管理
- サーバは `sync_id` 単位で同期状態を追跡できること
- 最低限 `received`, `raw_saved`, `events_saved`, `failed` の区別ができること
- 失敗理由は短いコードで保持できること
- state JSON に保持するのは最新同期の状態のみとし、完全な履歴監査ログは MVP の対象外とする

#### 3.6 将来拡張の余地
- YouTube 動画 URL のみを二次抽出して別 schema / dataset に保存できるようにする
- compact / 再処理 / local mirror sync は `pipelines` の workflow として扱う
- データ参照 API は将来的に MCP / Skill へ置き換え可能な構造を維持する

### 期待する挙動

1. **通常同期**
   - ブラウザ起動時に拡張が起動
   - 拡張が `last_successful_sync_at` 以降の履歴を取得
   - 取得データを `sync_id`, `browser`, `profile`, `device_id` 付きでミニPCへ送信
   - サーバが受信 payload を検証し、raw JSON と page view parquet に保存する
   - サーバは `sync_id` 単位で進行状態を更新する
   - 成功時のみ拡張側が `last_successful_sync_at` を更新

2. **送信失敗**
   - ネットワーク断、認証失敗、サーバエラー時は同期失敗として扱う
   - 拡張側はカーソルを更新しない
   - サーバ側は可能なら `failed` と失敗理由を `sync_id` に紐づけて記録する
   - 次回起動時に前回未送信範囲を再送する

3. **初回導入**
   - `last_successful_sync_at` が存在しない
   - 拡張は履歴 API の取得可能範囲で初回バックフィルを実行する
   - 初回バックフィルは全体で最大 50,000 件まで取得し、1 request あたり最大 1,000 件ずつ送る
   - サーバは初回 payload も通常データと同様に保存する

### 画面/入出力（ある場合）

#### 拡張の設定項目
- `server_url`
- `bearer_token`
- `browser_id`
- `device_id`
- `profile`

#### 送信 payload（MVP 案）
```json
{
  "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
  "source_device": "home-windows-pc",
  "browser": "edge",
  "profile": "Default",
  "synced_at": "2026-03-22T12:00:00Z",
  "items": [
    {
      "url": "https://www.youtube.com/watch?v=abc123",
      "title": "Example Video",
      "visit_time": "2026-03-22T08:31:12Z",
      "visit_id": "optional-browser-visit-id",
      "referring_visit_id": "optional-ref-id",
      "transition": "link"
    }
  ]
}
```

---

## 4. Scope

### 今回やる（MVP）
- Chromium 拡張による訪問履歴収集
- Edge / Brave 対応
- Chrome 互換性を考慮した実装
- 起動時差分同期
- `Bearer token` 認証
- `pipelines` 上の受信 endpoint
- raw JSON / page view parquet 保存
- `sync_id` ベースの最小同期状態管理
- `browser`, `profile`, `source_device` を含むイベントスキーマ設計
- 基本的な重複許容 + 後段吸収前提の append-only 保存

### 今回やらない（Won’t）
- 拡張のストア公開
- Windows 常駐ツールや履歴 DB 直読
- 厳密な定時バッチ送信
- YouTube 専用 dataset への分離
- ブックマーク、検索語、ダウンロード、滞在時間の収集
- 汎用 workflow platform 化

### 次回以降（あれば）
- Chrome 実機での互換検証
- YouTube URL 抽出ジョブ
- compact / local mirror sync の jobs サービス移管
- ストア公開向け設定 UI / 導入フロー整備
- データ参照 API の MCP / Skill 移行

---

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 拡張を導入する | Edge / Brave にローカル導入する | ストア配布する |
| 初期設定する | URL / token / browser_id / device_id を設定する | 自動検出する |
| 履歴を収集する | 起動時に差分履歴を読む | 起動中の定期再同期も行う |
| サーバへ送る | Tailscale 経由で一括 POST する | オフラインキューを強化する |
| 保存する | raw JSON / page view parquet に保存する | compact を自動生成する |
| 分析する | browser / profile 単位でクエリできる | YouTube 専用 dataset に派生する |

---

## 6. Acceptance Criteria

### AC1: ブラウザ別の差分同期
**Given** Edge または Brave に拡張が導入されている  
**When** ブラウザを起動する  
**Then** `last_successful_sync_at` 以降の訪問履歴のみが取得される  
**And** 送信 payload に `browser` と `profile` が含まれる

### AC2: 失敗時の再送
**Given** 前回同期で送信エラーが発生した  
**When** 次回ブラウザを起動する  
**Then** 拡張は前回未送信範囲を再送する  
**And** サーバ側で受信・保存できる

### AC3: ミニPC側の保存
**Given** 拡張から有効な payload が送信される  
**When** `pipelines` の ingest endpoint がリクエストを受ける  
**Then** raw JSON が R2 に保存される  
**And** page view parquet が R2 に append-only で保存される  
**And** `sync_id` 単位で処理状態を追跡できる

### AC4: ブラウザ別の分析可能性
**Given** Edge と Brave の履歴が保存されている  
**When** 後段で DuckDB / MCP から参照する  
**Then** `browser` でフィルタリングできる  
**And** `profile` でも分離可能である

### AC5: 将来の YouTube 二次抽出との両立
**Given** YouTube 動画ページ URL が browser history として保存されている  
**When** 将来の再処理ジョブを追加する  
**Then** browser history 正本を壊さずに YouTube 専用 dataset を派生生成できる

### AC6: compact の整合
**Given** browser history の page view parquet が保存されている  
**When** 既存 provider と同じ compaction フローを実行する  
**Then** browser history も同じパターンで compacted parquet を生成できる

---

## 7. 例外・境界

### 失敗時（通信/保存/権限）
- 認証失敗: `401/403` を返し、拡張はカーソルを更新しない
- R2 保存失敗: endpoint は失敗として扱い、部分成功時の扱いをログで明示する
- 拡張権限拒否: 履歴取得不可として同期失敗にする
- 失敗状態は `sync_id` に紐づけて記録する

### 空状態（データ0件）
- 前回同期以降の新規履歴が 0 件でも正常終了とする
- 空同期時は raw 保存を省略してもよいが、同期成功扱いの判断は明示する

### 上限（文字数/件数/サイズ）
- 初回バックフィルで大量件数になる可能性があるため、payload は上限制御または分割送信を考慮する
- MVP では 1 request あたり最大 1,000 件を目安に分割する

### 既存データとの整合（互換/移行）
- 新規データソースとして追加するため既存互換は不要
- `backend` に旧 write endpoint を残さず、拡張機能の送信先を `pipelines` へ一本化する

---

## 8. Non-Functional Requirements (FURPS)

### Performance
- 起動時同期はブラウザ体験を極端に阻害しないこと
- 保存形式は既存 Data Lake パターンに合わせ、後段クエリ可能であること

### Reliability
- at-least-once 配信前提で、送信失敗時に取りこぼさないこと
- 正本を R2 に集約し、ローカル mirror がなくてもデータ損失しないこと
- `sync_id` 単位で失敗地点を追えること

### Usability
- 個人利用ではローカル導入で始められること
- 設定項目は最小限に抑えること

### Security/Privacy
- 通信経路は Tailscale / Tailscale Serve を前提とする
- 追加で `Bearer token` を付与し、共有 URL だけでは受け付けない
- ブラウザ履歴は高センシティブデータとして扱う

### Constraints（技術/期限/外部APIなど）
- Chromium 拡張 API の取得範囲に従う
- 取得対象はページ訪問履歴であり、厳密な再生イベントや滞在時間は対象外
- `.env` 読み取り禁止の運用ルールに従う

---

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

### Risk
- 拡張 API の挙動差や MV3 制約で、ブラウザ間に微差が出る可能性がある
- 初回バックフィル量が多いと request サイズや処理時間が膨らむ

### Assumption
- 主運用ブラウザは Edge / Brave であり、Chrome は互換対象である
- 自宅 Windows PC からミニPCへ Tailscale で到達できる

### Issue
- `pipelines` 側の run 管理・再試行・ログ保持は別設計に沿って継続拡張する必要がある
- `backend` は chat/read API 中心の境界へ寄せる

### Dependency
- Chromium `history` API
- `pipelines` の HTTP 受信基盤
- R2 保存基盤
- local mirror sync の既存パターン

---

## 10. Reference

- `.github/ISSUE_TEMPLATE/requirements.md`
- `docs/00.project/features/youtube_watch_history_collection.md`
- `docs/10.architecture/1001_system_architecture.md`
- `docs/10.architecture/1002_data_model.md`
- Issue #72: Separate scheduled jobs into a dedicated jobs service
- Chrome Extensions `history` API: https://developer.chrome.com/docs/extensions/reference/api/history
- MDN `history.getVisits()`: https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/history/getVisits

---

## 11. API 設計メモ

### 11.1 Endpoint

`POST /v1/ingest/browser-history`

### 11.2 Request Header

- `Authorization: Bearer <token>`
- `Content-Type: application/json`

### 11.3 Request Body

```json
{
  "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
  "source_device": "home-windows-pc",
  "browser": "edge",
  "profile": "Default",
  "synced_at": "2026-03-22T12:00:00Z",
  "items": [
    {
      "url": "https://example.com",
      "title": "Example",
      "visit_time": "2026-03-22T08:31:12Z",
      "visit_id": "12345",
      "referring_visit_id": "12344",
      "transition": "link"
    }
  ]
}
```

### 11.4 Response Body

```json
{
  "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
  "accepted": 120,
  "raw_saved": true,
  "events_saved": true,
  "received_at": "2026-03-22T12:00:01Z"
}
```

### 11.5 Validation 方針

- `browser` は `edge | brave | chrome` を MVP 対象とする
- `source_device` は必須
- `sync_id` は必須
- `profile` は必須
- `items` は空配列を許容する
- `url` と `visit_time` は必須
- `visit_id`, `referring_visit_id`, `transition`, `title` は任意

---

## 12. スキーマ設計メモ

### 12.0 同期状態ログ

既存の state JSON 管理に合わせて、browser history 用 state に最小限の同期状態を保持する。
これは「直近の同期状態を知るための state」であり、完全な履歴監査ログではない。

想定項目:

```json
{
  "sync_id": "2f4377e4-8c80-4ef4-a6bb-7f9350dbd6cf",
  "last_successful_sync_at": "2026-03-22T12:00:01Z",
  "last_sync_status": "events_saved",
  "last_failure_code": null,
  "last_received_at": "2026-03-22T12:00:01Z",
  "last_accepted_count": 120
}
```

### 12.1 Raw 保存

```text
raw/browser_history/{browser}/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
```

### 12.2 Events 保存

```text
events/browser_history/page_views/year={YYYY}/month={MM}/{uuid}.parquet
```

### 12.3 Events スキーマ案

```sql
page_view_id        VARCHAR PRIMARY KEY  -- browser/profile/url/start/end などから生成する安定ID
started_at_utc      TIMESTAMP NOT NULL
ended_at_utc        TIMESTAMP NOT NULL
url                 VARCHAR NOT NULL
title               VARCHAR
browser             VARCHAR NOT NULL     -- edge / brave / chrome
profile             VARCHAR NOT NULL
source_device       VARCHAR NOT NULL
transition          VARCHAR
visit_span_count    INTEGER NOT NULL
synced_at_utc       TIMESTAMP NOT NULL
ingested_at_utc     TIMESTAMP NOT NULL
```

### 12.4 一意性と重複方針

- 拡張側は at-least-once 配信
- サーバ側では `page_view_id` を安定生成できるようにする
- ただし append-only 保存を優先し、重複完全排除は compact / 再処理で吸収可能な設計とする

---

## 13. 実装構造（予定）

```text
browser-extension/
└── chromium-history/
    ├── manifest.json
    ├── package.json
    ├── tsconfig.json
    ├── src/
    │   ├── background/
    │   │   ├── main.ts
    │   │   ├── sync.ts
    │   │   ├── history.ts
    │   │   └── storage.ts
    │   ├── options/
    │   │   ├── index.html
    │   │   └── main.ts
    │   └── shared/
    │       ├── types.ts
    │       └── api.ts
    ├── dist/
    └── README.md

backend/
├── api/
│   └── browser_history_data.py
├── api/schemas/
│   └── data.py
└── usecases/
    └── tools/

pipelines/
└── browser_history/
    ├── storage.py
    ├── transform.py
    └── schema.py
```

- Chromium 拡張は `frontend/` 配下には置かず、ルート直下の独立パッケージとして扱う
- これにより KMP フロントエンドと責務を分離し、将来のローカル配布やストア公開に備えやすくする
- 実行時は `pipelines` が入口となり、Browser History の変換・保存・compact enqueue を担当する

---

## 14. 備考

- YouTube 動画単位の分析は、`watch?v=...` のような URL を後段で抽出することでかなり対応可能
- ただし browser history は「ページ訪問履歴」であり、「再生イベントそのもの」ではない
- 受信口は `pipelines` に置き、`backend` は read/query API のみに限定する
- raw JSON と page view parquet の責務分離、および 2 秒クラスタリングの判断理由は [browser-history.md](../10.architecture/03-ingest/browser-history.md) を参照
