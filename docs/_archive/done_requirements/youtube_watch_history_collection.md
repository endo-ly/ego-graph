# 要件定義: YouTube視聴履歴収集機能

## 1. Summary

- **やりたいこと**: Google MyActivityからYouTube視聴履歴を1日1回自動収集し、R2 Data Lakeに保存する
- **理由**: Personal Data Warehouseとして、個人のデジタルライフログを統合的に管理するため
- **対象**: 2つのGoogleアカウントのYouTube視聴履歴（account1, account2）
- **優先**: Phase 1として完全動作が必須。他Googleサービス対応は将来拡張。

---

## 2. Purpose (WHY)

### いま困っていること
- YouTube視聴履歴がYouTube内にしか存在せず、他のライフログと統合的に分析できない
- YouTube Data APIは2016年に視聴履歴取得機能が廃止されており、公式APIでの取得が不可能
- 複数のGoogleアカウントを使い分けており、統一的に管理したい

### できるようになったら嬉しいこと
- 日次で自動的にYouTube視聴履歴がR2に蓄積される
- SpotifyやLastFMなどの他のライフログと統合してクエリ・分析できる
- 複数アカウントの視聴履歴を一元管理できる
- 動画メタデータ（チャンネル情報、再生時間など）も合わせて取得できる

### 成功すると何が変わるか
- 個人のデジタルライフログが時系列で統合され、LLMを活用した検索・分析が可能になる
- YouTube視聴履歴がバックアップされ、データ消失リスクが軽減される
- 将来的にChrome閲覧履歴、Google検索履歴など他のGoogleサービスにも同じパターンで拡張可能

---

## 3. Requirements (WHAT)

### 機能要件

#### 3.1 YouTube視聴履歴の自動収集
- Google MyActivity（myactivity.google.com）からYouTube視聴履歴をスクレイピング
- 2つのGoogleアカウント（account1, account2）に対応
- GitHub Actionsで1日1回自動実行
- 前回取得時刻以降の差分のみ取得（増分収集）
- 初回実行時は可能な限り遡って取得（バックフィル: 数百〜数千件）

#### 3.2 動画マスターデータのエンリッチ
- 視聴履歴から新規video_idを抽出
- YouTube Data API v3で動画メタデータを取得
  - タイトル、チャンネル情報、再生時間、サムネイルなど
- Spotifyのトラック/アーティストマスターと同様のパターンで実装
- 既存マスターに存在しないvideo_idのみ取得（重複回避）

#### 3.3 Cookie認証管理
- 半自動化: スクリプトでブラウザからCookie取得を補助
- GitHub Secretsで暗号化保管
- アカウントごとに独立したCookie管理

#### 3.4 データ保存
- R2に年月パーティション（Hiveスタイル）で保存（Spotifyと統一パターン）
- 全レコードに`account_id`カラムを追加（アカウント識別）
- 状態管理ファイルをアカウント別に保存

**R2ファイル構造**:
```
R2 Bucket/
├── raw/youtube/                            # 生データ（JSON/HTML）
│   ├── activity/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}_{account_id}.json
│   ├── videos/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
│   └── channels/{YYYY}/{MM}/{DD}/{timestamp}_{uuid}.json
│
├── events/youtube/                         # イベントデータ（Parquet）
│   └── watch_history/year={YYYY}/month={MM}/{uuid}.parquet
│
├── master/youtube/                         # マスターデータ（Parquet）
│   ├── videos/year={YYYY}/month={MM}/{uuid}.parquet
│   └── channels/year={YYYY}/month={MM}/{uuid}.parquet
│
└── state/                                  # 状態管理（JSON）
    ├── youtube_account1_state.json
    └── youtube_account2_state.json
```

### 期待する挙動

1. **通常実行（差分取得）**
   - 状態ファイルから前回取得時刻（`latest_watched_at`）を読み込み
   - MyActivityから該当時刻以降の視聴履歴のみスクレイピング
   - 新規video_idがあればYouTube Data API v3でメタデータ取得
   - Parquetに変換してR2保存
   - 状態ファイルを最新の`watched_at`で更新

2. **初回実行（バックフィル）**
   - 状態ファイルが存在しない
   - 無限スクロールで可能な限り遡って取得（数百〜数千件）
   - レート制限考慮: 2-5秒の間隔でスクロール

3. **失敗時**
   - Cookie期限切れ、レート制限、ページ構造変更などを検出
   - GitHub Actions logsにエラー出力
   - パイプラインが失敗ステータスで終了

### データスキーマ

#### 視聴履歴（events/youtube/watch_history/）
```sql
watch_id          VARCHAR PRIMARY KEY  -- account_id + video_id + watched_at のハッシュ
account_id        VARCHAR NOT NULL     -- 'account1' or 'account2'
watched_at_utc    TIMESTAMP NOT NULL
video_id          VARCHAR NOT NULL
video_title       VARCHAR
channel_id        VARCHAR
channel_name      VARCHAR
video_url         VARCHAR
context           VARCHAR              -- 推薦/検索/再生リスト経由（取得できれば）
```

**パーティショニング**: `watched_at_utc`の年月でHiveパーティション

---

#### 動画マスター（master/youtube/videos/）
```sql
video_id          VARCHAR PRIMARY KEY
title             VARCHAR NOT NULL
channel_id        VARCHAR NOT NULL
channel_name      VARCHAR
duration_seconds  INTEGER
view_count        BIGINT
like_count        BIGINT
comment_count     BIGINT
published_at      TIMESTAMP
thumbnail_url     VARCHAR
description       VARCHAR              -- 要約版
category_id       VARCHAR
tags              VARCHAR[]
updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

**パーティショニング**: エンリッチ実行時の年月でHiveパーティション

---

#### チャンネルマスター（master/youtube/channels/）
```sql
channel_id        VARCHAR PRIMARY KEY
channel_name      VARCHAR NOT NULL
subscriber_count  BIGINT
video_count       INTEGER
view_count        BIGINT
published_at      TIMESTAMP
thumbnail_url     VARCHAR
description       VARCHAR
country           VARCHAR
updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

**パーティショニング**: エンリッチ実行時の年月でHiveパーティション

---

## 4. Scope

### 今回やる（MVP - Phase 1）
- YouTube視聴履歴収集（2アカウント対応）
- PlaywrightによるMyActivityスクレイピング
- YouTube Data API v3による動画マスターエンリッチ
- Cookie取得スクリプト（半自動化ツール）
- GitHub Actionsで1日1回自動実行
- R2へのParquet保存（年月パーティション）
- 差分取得とバックフィル
- ユニットテスト（パーサー、変換ロジック）
- 統合テスト（ローカルでスクレイピング動作確認、手動実行）

### 今回やらない（Won't）
- Slack/Email通知機能（失敗検知はGitHub Actions logsのみ）
- Backend DuckDB Viewからのデータ参照（別Issue）
- 他のGoogleサービス対応（Chrome, 検索, Maps）
- E2Eテスト、スナップショットテスト
- 完全自動Cookie更新（Playwright認証フロー）

### 次回以降（Phase 2）
- 通知機能実装（Slack/Email）
- Backend統合（DuckDB View作成、API提供）
- 他Googleサービスへの拡張（Chrome閲覧履歴、Google検索履歴、Maps履歴）

---

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| **準備** | Cookie取得スクリプトでGoogle認証情報を取得 | 完全自動Cookie更新 |
| **収集** | PlaywrightでMyActivityからYouTube視聴履歴をスクレイピング（2アカウント順次実行） | 並列実行 |
| **変換** | HTML/JSONをParquetスキーマに変換 | - |
| **保存** | R2に年月パーティションで保存（account_id付き） | - |
| **エンリッチ** | YouTube Data API v3で動画マスター取得 | チャンネルマスターも取得 |
| **監視** | GitHub Actionsで1日1回自動実行 | 失敗時にSlack通知 |

---

## 6. Acceptance Criteria

### AC1: Cookie取得スクリプト
**Given** ユーザーがローカル環境でスクリプトを実行
**When** ブラウザからGoogle認証情報を抽出
**Then** JSON形式でCookieファイルが生成される
**And** GitHub Secretsへの登録手順が表示される

### AC2: YouTube視聴履歴収集（差分取得）
**Given** R2に`state/youtube_account1_state.json`が存在する
**When** GitHub Actionsが1日1回実行される
**Then** 前回取得時刻（`latest_watched_at`）以降の視聴履歴のみ取得される
**And** 新しいデータがR2の`events/youtube/watch_history/`に保存される
**And** stateファイルが最新の`watched_at`で更新される
**And** 同様にaccount2も処理される

### AC3: 初回実行時のバックフィル
**Given** R2に`state/youtube_account1_state.json`が存在しない
**When** 初回実行される
**Then** 可能な限り遡って視聴履歴を取得する（数百〜数千件）
**And** 無限スクロールで段階的にデータをロードする
**And** レート制限を考慮して2-5秒の間隔を空ける

### AC4: 動画・チャンネルマスターエンリッチ
**Given** 視聴履歴から新規video_idとchannel_idを抽出
**When** 既存マスターに存在しないvideo_id/channel_idがある
**Then** YouTube Data API v3で動画・チャンネル詳細を取得
**And** `master/youtube/videos/`と`master/youtube/channels/`にParquet保存
**And** APIクォータ（10,000 units/day）を超えない
**And** 動画とチャンネルの取得は独立して処理（片方失敗しても他方は保存）

### AC5: 複数アカウント対応
**Given** 2つのGoogleアカウント（account1, account2）が設定されている
**When** GitHub Actionsが実行される
**Then** account1の視聴履歴を収集してR2に保存
**And** account2の視聴履歴を収集してR2に保存
**And** 各レコードに`account_id`が記録される
**And** account1の失敗がaccount2の処理をブロックしない

### AC6: Cookie期限切れ時の失敗
**Given** CookieファイルのGoogleセッションが期限切れ
**When** スクレイピングを試行
**Then** 認証エラーを検出
**And** GitHub Actions logsにエラーを出力
**And** パイプラインが失敗ステータスで終了

### AC7: アカウント別データ参照
**Given** R2にaccount1とaccount2の視聴履歴が保存されている
**When** DuckDBでクエリを実行
**Then** `account_id`でフィルタリング可能
**And** 両アカウントの統合クエリも可能

---

## 7. 例外・境界

### 失敗時（通信/保存/権限）
- **Playwright接続エラー**: 最大3回リトライ
- **APIクォータ超過**: エラーログ出力、次回実行時に再試行
- **部分的成功**: 視聴履歴取得は成功したがエンリッチ失敗の場合、履歴のみ保存
- **状態ファイル更新**: 全処理成功後のみ更新（データ整合性保証）

### 空状態（データ0件）
- 前回取得時刻以降に視聴履歴がない場合、stateファイルを更新せずに正常終了
- ログに「No new data found」を出力

### 上限（文字数/件数/サイズ）
- 1回の実行で取得する上限: 特に設定しない（スクロール可能な限り取得）
- ただしGitHub Actions timeout（30分）を考慮
- YouTube Data API v3は50件/リクエストでバッチ処理

### 既存データとの整合（互換/移行）
- 既存データなし（新規実装）
- 将来的にSpotifyも複数アカウント対応する場合、この設計パターンを適用

---

## 8. Non-Functional Requirements (FURPS)

### Performance
- スクレイピング時間: 100件あたり2-5分程度（スクロール + パース）
- API呼び出し: YouTube Data API v3は50件/リクエストでバッチ処理
- GitHub Actions timeout: 30分以内に完了

### Reliability
- リトライ: Playwright接続エラー時は最大3回リトライ
- 部分的成功: 視聴履歴取得は成功したがエンリッチ失敗の場合、履歴のみ保存
- 状態管理: stateファイル更新は全処理成功後のみ

### Usability
- Cookie取得スクリプトで半自動化、運用負荷を低減
- ログ出力でデバッグ可能（構造化ログ）

### Security/Privacy
- Cookie保管: GitHub Secretsで暗号化保管
- 個人情報: YouTubeアカウント情報はログ出力しない
- API Key: YouTube Data API Keyも同様にSecrets管理

### Constraints（技術/期限/外部APIなど）
- YouTube Data API クォータ: 10,000 units/day（video取得: 1 unit/件）
- Playwright依存: Chromiumブラウザが必要（GitHub Actionsでインストール）
- Google ToS: スクレイピングはグレーゾーン、個人利用目的に限定
- 実装期限: 特になし（ベストエフォート）

---

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

### Risk
- **ページ構造変更**: GoogleがMyActivityのHTML構造を変更した場合、パーサー修正が必要
- **Cookie有効期限**: 数ヶ月ごとに手動更新が必要（運用負荷）
- **レート制限**: 過度なスクレイピングでIPブロックされる可能性
- **ToS違反**: Googleの利用規約違反によるアカウント停止リスク（個人利用なら実質的には低い）

### Assumption
- MyActivityのURL構造は安定している（`myactivity.google.com/product/youtube`）
- PlaywrightのCookie認証が継続して機能する
- YouTube Data API v3のクォータは日次収集に十分
- モバイルアプリでの視聴履歴もMyActivityに含まれる

### Issue
- 現時点では通知機能未実装（失敗検知が遅れる可能性）
- CI/CDでの統合テスト実行が困難（外部サイト依存）

### Dependency
- **google_takeout_parser**: 既存OSSの実装を参考にする
- **Spotify pipeline**: 同様のアーキテクチャパターンを踏襲
- **GitHub Actions**: 定期実行基盤
- **Playwright**: ブラウザ自動化ライブラリ
- **YouTube Data API v3**: 動画メタデータ取得

---

## 10. Reference

### 技術選定ドキュメント
- [YouTube視聴履歴収集の技術選定](../70.knowledge/technical-selections/youtube-history-collection.md)

### 参考実装
- `egograph/pipelines/sources/spotify/`: Spotify収集パイプライン（アーキテクチャの参考）
- [google_takeout_parser](https://github.com/seanbreckenridge/google_takeout_parser): MyActivityパーサーの参考実装

### 実装構造（予定）
```
egograph/pipelines/sources/google_activity/
├── main.py                    # アカウントループのエントリポイント
├── collector.py               # Playwrightスクレイパー
├── config.py                  # アカウント設定管理
├── transform.py               # YouTube Activity → Parquet
├── youtube_api.py             # YouTube Data API メタデータ補完
├── storage.py                 # R2保存（account_id対応）
├── pipeline.py                # ingest / compact エントリーポイント
├── schema.py                 # スキーマ定義
└── scripts/
    └── export_cookies.py     # Cookie取得スクリプト
```

定期実行は `google_activity_ingest_workflow` が担い、
旧 `.github/workflows/job-ingest-google-youtube.yml` は削除済み。

### Spotify実装との比較

| 項目 | Spotify | YouTube（今回） |
|------|---------|----------------|
| アカウント数 | 1（単一） | 2（複数対応） |
| 識別子 | なし | `account_id` カラム |
| 状態管理 | `spotify_ingest_state.json` | `youtube_{account_id}_state.json` |
| 実行方法 | 単一実行 | ループで順次実行 |
| 認証 | OAuth（リフレッシュトークン） | Cookie認証 |
| データソース | 公式API | スクレイピング（MyActivity） |

---

## 備考

- 将来的にSpotifyも複数アカウント対応が必要になった場合、この設計パターンを適用可能
- 他のGoogleサービス（Chrome閲覧履歴、Google検索履歴、Maps履歴）への拡張を見据えた汎用的な設計
