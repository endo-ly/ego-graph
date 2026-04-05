# データ戦略

EgoGraph におけるデータの保存場所と責務分担を定義する。1002_data_model.md と 1003_storage_responsibilities.md を統合し、一貫した指針を提供する。

---

## 1. ストレージ責務分離

### 1.1 3層モデル

データの保管場所と役割を以下の3つに明確に分離する。

1.  **Cloudflare R2 (Object Storage)**: **正本 (Original)**
    - データの「原本」置き場。テキスト本文やログの実体はここに置く。
2.  **DuckDB**: **台帳 (Ledger) & 分析エンジン**
    - データの「所在」と「状態」を管理するカタログ。R2 上の Parquet を `VIEW` (Mart) として定義し、クエリを可能にする。
    - 「昨日の曲」のような決定論的なクエリ（集計・分析）を担当。
3.  **Qdrant**: **索引 (Index)**
    - 意味検索（ベクトル検索）のためのディクショナリ。
    - 正本は持たず、IDと検索に必要な最小限のタグのみを持つ。

### 1.2 SQLite の責務

EgoGraph ではストレージの役割を以下のように分離する。

- **SQLite**: アプリケーション状態・会話履歴・小規模な運用メタデータ
- **DuckDB**: 分析クエリ実行、集計、横断参照、派生データ生成
- **Parquet**: 分析用データの正規フォーマット、長期保存、データ交換
- **Raw JSON / Object Storage**: APIレスポンスなどの監査・再処理用原本

この分離により、更新系と分析系の要件を混在させず、保守性・性能・設計の見通しを維持する。

---

## 2. 基本原則

### 2.1 正本と分析基盤を分ける

- 日々の更新・削除・状態遷移が発生するデータは、**SQLite を正本**とする
- 集計・探索・横断分析に使うデータは、**DuckDB / Parquet に複製して利用**する
- 分析のために、更新系の正本を直接複雑化させない

### 2.2 更新系は SQLite に寄せる

以下の特徴を持つデータは SQLite を優先する。

- 1件ずつ追加・更新・削除される
- UI / API から逐次 CRUD される
- アプリケーション状態として扱う
- 行数よりも整合性・操作性が重要

### 2.3 分析系は DuckDB / Parquet に寄せる

以下の特徴を持つデータは DuckDB / Parquet を優先する。

- 時系列で増え続ける
- 後から集計・再分析したい
- プロバイダ横断で参照したい
- Object Storage 上で長期保存したい
- バッチ変換や再生成を前提にできる

### 2.4 SQLite と DuckDB を競合させない

SQLite と DuckDB は代替関係ではなく責務分離の関係とする。

- SQLite は **アプリケーション DB**
- DuckDB は **分析エンジン**
- Parquet は **分析データの保存形式**

### 2.5 Parquet-first を採用する理由

EgoGraph が Parquet-first である理由は、単に流行や技術的な面白さではなく、**ライフログを後から何度でも再解釈できる分析基盤を優先するため**である。

- 個人ログは後から集計軸が増えやすい
- Provider ごとの API 仕様変更に対して、Raw と Curated を分離したい
- バックエンドの常駐 DB を肥大化させず、Object Storage を正本として扱いたい
- 分析用途では行指向 DB より列指向フォーマットの恩恵が大きい

一方で、Parquet-first は **すべてのデータを Parquet に置く** ことを意味しない。更新系・状態系のデータまで Parquet を正本にすると、実装と運用が不自然になる。

### 2.6 Parquet-first が適切な条件

以下を満たすなら、Parquet-first は合理的である。

- 主役のデータが時系列イベントログである
- 主要ユースケースが CRUD より分析・集計である
- 正本を Object Storage に寄せたい
- 再計算や再キュレーションを前提にできる
- 多少のバッチ指向を受け入れられる

逆に、以下が主役なら Parquet-first に寄せすぎない。

- アプリケーション状態管理
- 会話履歴の逐次更新
- 小規模だが整合性が重要なメタデータ
- リアルタイムな単純 CRUD

---

## 3. ストレージごとの責務

### 3.1 SQLite の責務

SQLite は、EgoGraph における更新系・状態系の正本ストアとする。

#### 代表例

- 会話履歴（threads, messages, attachments）
- UI 状態（既読、ピン留め、ラベル、アーカイブ）
- ジョブ状態（embedding queue, retry state, sync state）
- 小規模な設定・マスターデータ

#### 採用理由

- 小規模 CRUD に向く
- ローカルファイルで完結する
- アプリケーション DB として責務が明快
- 更新系の整合性を保ちやすい

### 3.2 DuckDB の責務

DuckDB は、EgoGraph における分析・集計・横断参照の実行基盤とする。

#### 代表例

- Spotify / YouTube / GitHub などのライフログ分析
- 会話履歴の集計分析
- 日次・週次・月次の派生集計
- Parquet データセットの横断 SQL
- バックエンド API の分析クエリ

#### 採用理由

- 列指向で集計に強い
- Parquet を直接扱える
- バッチ生成された派生データを即座に分析できる
- 大きな時系列データでも個人運用の範囲で高性能

### 3.3 Parquet の責務

Parquet は、分析用データの標準保存形式とする。

#### 代表例

- ingest で生成される curated dataset
- 会話履歴の分析用エクスポート
- 日次・月次の集計済み派生データ
- DuckDB から参照される分析用データセット

#### 採用理由

- 列指向で圧縮効率が良い
- 分析クエリに適する
- Object Storage と相性が良い
- 再利用・再計算・移送がしやすい

---

## 4. レイヤー別データ構造

### 4.1 正本 (Cloudflare R2) - "The Bookshelf"

ソースデータから抽出・加工された実データ（Parquet形式推奨）の永続化場所。

**R2 Directory Structure**:
```text
s3://{bucket}/
├── events/          # 時系列データ (Analytics / Recall)
│   └── spotify/
│       └── plays/   # Spotify 再生ログ (year={yyyy}/month={mm}/...)
├── master/          # 非時系列・マスタデータ (Enrichment)
│   └── spotify/     # Spotify マスター (tracks/, artists/)
├── raw/             # 生データ (Audit / Reprocessing)
│   └── spotify/     # API レスポンス (JSON)
└── state/           # 進捗管理 (Cursors)
    ├── spotify_ingest_state.json
    └── lastfm_ingest_state.json  # Archived
```

**Spotify Archives**:
- 再生履歴の事実データ（Parquet）。
- Path: `s3://{bucket}/events/spotify/plays/year={yyyy}/month={mm}/{uuid}.parquet`

**Spotify Master**:
- 楽曲・アーティストのマスターデータ（Parquet）。
- Track Path: `s3://{bucket}/master/spotify/tracks/year={yyyy}/month={mm}/{uuid}.parquet`
- Artist Path: `s3://{bucket}/master/spotify/artists/{uuid}.parquet`

**Last.fm**:
- Deprecated。ジョブ停止中のため新規データは投入しない。

**State Management**:
- インジェストの進捗管理ファイル。
- Path: `s3://{bucket}/state/{source}_ingest.json`

### 4.2 台帳 (DuckDB) - "The Catalog"

実データへの参照（パス）、メタデータ、運用状態を管理する。LLMやAPIはこの層を通じてデータにアクセスする。
**この層の `mart` スキーマは R2 上のフォルダ構造ではなく、DuckDB 内の論理的なビュー構成である。**

#### Schema Layers

データの用途に応じて3つのスキーマを使い分ける。

```sql
CREATE SCHEMA IF NOT EXISTS raw;   -- 取り込み直後（ほぼ生）
CREATE SCHEMA IF NOT EXISTS mart;  -- API/LLMが使う整形済み
CREATE SCHEMA IF NOT EXISTS ops;   -- ingest状態・ログ
```

#### 管理データ (Meta & Ops)

- **Documents Ledger (`mart.documents`)**
  - **役割**: ドキュメントの管理台帳。
  - **主な項目**: `doc_id`, `title`, `uri` (S3 path), `hash` (変更検知用), `updated_at`.
- **Ingest State (`ops.ingest_state`)**
  - **役割**: 取り込み処理の進捗管理（カーソル）。
  - **主な項目**: `source`, `cursor_value` (timestamp/token), `status`.

#### 分析・参照データ (Analytics & Lookup)

- **Spotify History (`mart.spotify_plays`)**
  - **役割**: 履歴の検索・集計用ビュー。R2上のParquetを参照。
  - **主な項目**: `play_id`, `track_name`, `played_at`, `artist_names`.
- **Spotify Master (`mart.spotify_tracks`, `mart.spotify_artists`)**
  - **役割**: 楽曲・アーティストの詳細属性（genres, popularity 等）。
  - **主な項目**: `track_id`, `name`, `genres`, `popularity`, `followers_total`.
- **Spotify Enriched (`mart.spotify_plays_enriched`)**
  - **役割**: 再生履歴にマスターデータを付与した分析用ビュー。
  - **主な項目**: `play_id`, `played_at_utc`, `track_id`, `genres`, `preview_url`.
- **Daily Summaries (`mart.daily_summaries`)**
  - **役割**: エージェントが生成した日次サマリーの正本（テキスト）。
  - **主な項目**: `summary_id`, `date`, `summary_text`, `stats_json`.

### 4.3 索引 (Qdrant) - "The Index Cards"

意味検索を行い、候補となるIDリストを返すことに特化する。**本文（Text）は保持しない。**

#### Document Index (`doc_chunks_v1`)
- **Vector**: チャンクテキストの埋め込み。
- **Payload**: フィルタリング用メタデータのみ。
  - `type`: "doc_chunk"
  - `doc_id`: UUID
  - `lang`: "ja"
  - `source`: "drive", "notion" etc.
  - `tags`: ["topic:RAG"]

#### Summary Index (`daily_summaries_v1`)
- **Vector**: サマリーテキストの埋め込み。
- **Payload**: 日付検索用メタデータ。
  - `type`: "daily_summary"
  - `summary_id`: UUID
  - `date`: "YYYY-MM-DD"
  - `mood`: ["focus", "chill"]

### 4.4 ローカル実行時データの配置

ローカル実行時データは、Git 管理される `repo/` の中に置かず、`repo` の兄弟 `data/` 配下に集約する。

- `repo/`: コード専用
- `data/`: 実行時データ専用

```text
<app-root>/
├── repo/                      # Git root
└── data/                      # runtime data root
    ├── backend/
    │   └── chat.sqlite
    ├── pipelines/
    │   ├── state.sqlite3
    │   └── logs/
    ├── parquet/
    │   └── compacted/...
    └── legacy/
        └── chat.duckdb
```

#### 配置ルール

- 会話履歴の正本 SQLite は `data/backend/chat.sqlite` に置く
- Pipelines の状態 DB と step log は `data/pipelines/` に置く
- compacted parquet の local mirror は `data/parquet/compacted/...` に置く
- 旧形式や一時退避が必要なデータだけを `data/legacy/` に残す
- `repo/data` や `egograph/backend/data` のような旧配置は新規に使わない

---

## 5. 主要データ分類

| データ種別 | 正本 | 分析先 | 備考 |
|---|---|---|---|
| Spotify / YouTube / GitHub ログ | Raw JSON + Parquet | DuckDB | ライフログの中心 |
| EgoGraph 会話履歴 | SQLite | DuckDB / Parquet | 正本と分析を分離 |
| ChatGPT 等の外部会話履歴 | SQLite | DuckDB / Parquet | 取り込み後に分析可能化 |
| UI 状態・ユーザー設定 | SQLite | 原則不要 | アプリ状態 |
| embedding job / sync state | SQLite | 必要なら DuckDB へ複製 | ジョブ管理 |

---

## 6. 会話履歴の方針

会話履歴は **SQLite を正本**とする。

### 6.1 正本として SQLite を使う理由

- スレッド / メッセージ / 添付の構造は更新系に属する
- 逐次保存、再同期、削除、ラベル付けなどの要求が増えやすい
- ライフログ本体よりもアプリケーション状態に近い

### 6.2 分析は DuckDB / Parquet に逃がす

会話履歴のうち、分析に必要なものは Parquet にエクスポートし、DuckDB で扱う。

#### 想定分析

- 月別メッセージ数
- モデル別 usage 集計
- ツール利用傾向
- トピック別の出現傾向
- 外部ライフログと会話の相関分析

### 6.3 ベクトル化の扱い

会話検索のための embedding / vector index は、まず **会話履歴の正本に近い層**で扱う。
実装方式は別途選定するが、少なくとも以下を守る。

- 会話履歴の正本と分析基盤を混同しない
- vector index は正本そのものではなく派生インデックスとして扱う
- ベクトル検索の方式を見直しても、正本スキーマが破綻しない構造にする

---

## 7. 判断フローチャート

新しいデータを追加する際は、以下の順で判定する。

1. そのデータは UI / API から逐次更新されるか？
   - Yes → SQLite を検討
2. そのデータは後から集計・横断分析したいか？
   - Yes → DuckDB / Parquet を検討
3. そのデータは「正本」か「分析用派生」か？
   - 正本 → SQLite または Raw/Parquet
   - 派生 → Parquet + DuckDB
4. 将来的に検索インデックスを作るか？
   - Yes → 正本とは分けて派生インデックスとして設計

---

## 9. 反パターン

以下は避ける。

- 更新系データを最初から分析基盤に直接押し込む
- ちょっとしたメタデータまで全部 DuckDB に集約する
- 正本、分析用派生、検索インデックスの境界を曖昧にする
- ベクトル検索の都合で正本スキーマを歪める

---

## 10. リスクとガードレール

このアーキテクチャは面白いが、Parquet-first を誤用すると複雑化しやすい。
以下をガードレールとして維持する。

- **ガードレール1**: 更新系の正本は SQLite に置く
- **ガードレール2**: Parquet は分析用・長期保存用に限定する
- **ガードレール3**: 派生データは再生成可能に保つ
- **ガードレール4**: 正本、分析用派生、検索インデックスの境界を分ける
- **ガードレール5**: 「DuckDB でできるから」で更新系まで DuckDB に寄せない

この前提を守れる限り、EgoGraph の Parquet-first は十分に理由のある選択である。
ただし、もし将来の主役がライフログ分析よりもアプリケーション状態管理や会話同期に寄るなら、アーキテクチャ全体の重心は SQLite 側へ見直してよい。

---

## 11. 今後の移行指針

### 優先度高

1. 会話履歴の正本を SQLite に移行する
2. 会話履歴の分析用エクスポート先を Parquet / DuckDB として定義する

### 優先度中

3. 既存ドキュメントの Qdrant 前提表現を整理する
4. ベクトル検索方式を別ドキュメントで技術選定する
