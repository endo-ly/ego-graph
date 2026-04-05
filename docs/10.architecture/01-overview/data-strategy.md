# データ戦略

EgoGraph におけるデータの保存場所と責務分担を定義する。

---

## 1. 設計原則

### 1.1 ストレージ責務分離

EgoGraph のストレージは、更新系と分析系を明確に分離する。

| ストレージ | 役割 | 性質 |
|---|---|---|
| **SQLite** | アプリケーション状態・会話履歴・運用メタデータ | 更新系（逐次 CRUD、整合性重視） |
| **DuckDB** | 分析クエリ実行エンジン | 分析系（集計・横断参照、ステートレス） |
| **Parquet** | 分析用データの標準保存形式 | 分析系（列指向、圧縮、長期保存） |
| **Raw JSON** | APIレスポンスの原本 | 監査・再処理用 |
| **Cloudflare R2** | 正本の永続化 | Object Storage（S3互換、egress無料） |
| **ベクトル検索** | 意味検索のインデックス | 未実装。IDとメタデータのみ保持 |

SQLite と DuckDB は代替関係ではなく責務分離の関係とする。

### 1.2 Parquet-first の理由

EgoGraph が Parquet-first である理由は、**ライフログを後から何度でも再解釈できる分析基盤を優先するため**である。

- 個人ログは後から集計軸が増えやすい
- Provider ごとの API 仕様変更に対して、Raw と Curated を分離したい
- バックエンドの常駐 DB を肥大化させず、Object Storage を正本として扱いたい
- 分析用途では行指向 DB より列指向フォーマットの恩恵が大きい

Parquet-first は **すべてのデータを Parquet に置く** ことを意味しない。更新系・状態系のデータは SQLite が適している。

**Parquet-first が合理的な条件:**
- 主役のデータが時系列イベントログである
- 主要ユースケースが CRUD より分析・集計である
- 正本を Object Storage に寄せたい
- 再計算や再キュレーションを前提にできる

**逆に SQLite が適している条件:**
- アプリケーション状態管理
- 会話履歴の逐次更新
- 小規模だが整合性が重要なメタデータ
- リアルタイムな単純 CRUD

---

## 2. ストレージ別責務

### 2.1 SQLite — 更新系・状態系の正本

**代表例:**

- 会話履歴（threads, messages）
- UI 状態（既読、ピン留め、ラベル）
- ジョブ状態（retry state, sync state）
- 小規模な設定・マスターデータ

**採用理由:** 小規模 CRUD に向き、ローカルファイルで完結し、更新系の整合性を保ちやすい。

**使用箇所:**

| コンポーネント | DBパス | 主要テーブル |
|---|---|---|
| Backend | `data/backend/chat.sqlite` | threads, messages |
| Pipelines | `data/pipelines/state.sqlite3` | workflow_runs, step_runs, workflow_locks |
| EgoPulse | `{data_dir}/egopulse.db` | chats, messages, sessions |

### 2.2 DuckDB — 分析・集計の実行エンジン

**代表例:**

- Spotify / GitHub / Browser History のライフログ分析
- 日次・週次・月次の派生集計
- Parquet データセットの横断 SQL

**採用理由:** 列指向で集計に強く、Parquet を直接扱え、`:memory:` モードでステートレス運用が可能。

**実行モード:** `:memory:`（リクエスト毎に新規接続）。httpfs 拡張で R2 上の Parquet を直接クエリ。ローカルミラーがあれば優先利用。

**Schema Layers:**

```sql
CREATE SCHEMA IF NOT EXISTS raw;   -- 取り込み直後（ほぼ生）
CREATE SCHEMA IF NOT EXISTS mart;  -- API/LLMが使う整形済み
CREATE SCHEMA IF NOT EXISTS ops;   -- ingest状態・ログ
```

**主な mart ビュー:**

| ビュー | 役割 | 主要カラム |
|---|---|---|
| `mart.spotify_plays` | 再生履歴の集計用ビュー | play_id, track_name, played_at, artist_names |
| `mart.spotify_tracks` | 楽曲マスター | track_id, name, genres, popularity |
| `mart.spotify_artists` | アーティストマスター | artist_id, name, genres, followers_total |
| `mart.spotify_plays_enriched` | 再生+マスターの結合ビュー | play_id, played_at_utc, track_id, genres |
| `mart.daily_summaries` | 日次サマリー | summary_id, date, summary_text, stats_json |

### 2.3 Parquet — 分析データの保存形式

**代表例:**

- ingest で生成される curated dataset
- 日次・月次の集計済み派生データ
- DuckDB から参照される分析用データセット

**採用理由:** 列指向で圧縮効率が良く、Object Storage と相性が良く、再利用・再計算・移送がしやすい。

### 2.4 Cloudflare R2 — 正本の永続化先

S3 互換の Object Storage。egress 無料で、分析クエリでの大量読み取りがコストゼロ。

ディレクトリ構造の詳細は [§3 データ配置](#3-データ配置) を参照。

### 2.5 ベクトル検索 — 意味検索のインデックス（未実装）

意味検索を行い、候補となるIDリストを返すことに特化する。**本文は保持しない。**

実装方式（Qdrant Cloud / ローカル等）は別途技術選定する。

**設計段階のコレクション構成:**

| コレクション | Vector | Payload |
|---|---|---|
| `doc_chunks_v1` | チャンクテキストの埋め込み | type, doc_id, lang, source, tags |
| `daily_summaries_v1` | サマリーテキストの埋め込み | type, summary_id, date, mood |

---

## 3. データ配置

### 3.1 R2 ディレクトリ構造

```
s3://{bucket}/
├── events/                      # 時系列データ
│   ├── spotify/plays/           # 再生ログ (year={yyyy}/month={mm}/)
│   ├── github/                  # GitHub活動
│   └── browser_history/         # ブラウザ履歴
├── master/                      # マスターデータ
│   └── spotify/                 # tracks/, artists/
├── raw/                         # APIレスポンス原本 (JSON)
│   └── spotify/
├── state/                       # 増分取り込みカーソル
│   ├── spotify_ingest_state.json
│   └── github_ingest_state.json
└── compacted/                   # Compaction済み Parquet
    ├── events/spotify/plays/    # 月次マージ済み
    └── events/github/
```

### 3.2 ローカルファイル配置

実行時データは Git 管理外の `data/` 配下に集約する。

```
<app-root>/
├── repo/                        # Git root（コードのみ）
└── data/                        # 実行時データ
    ├── backend/
    │   └── chat.sqlite          # 会話履歴
    ├── pipelines/
    │   ├── state.sqlite3        # ジョブ状態
    │   └── logs/                # Step実行ログ
    ├── parquet/
    │   └── compacted/...        # R2 Parquetのローカルミラー
    └── legacy/                  # 旧形式データ（退避用）
```

**配置ルール:**
- `repo/` 内に実行時データを置かない
- 旧配置（`repo/data`, `egograph/backend/data`）は新規に使わない
- 旧形式や一時退避が必要なデータだけを `data/legacy/` に残す

### 3.3 データ分類

| データ種別 | 正本 | 分析先 | 備考 |
|---|---|---|---|
| Spotify / GitHub / Browser History ログ | Raw JSON + Parquet | DuckDB | ライフログの中心 |
| EgoGraph 会話履歴 | SQLite | DuckDB / Parquet | 正本と分析を分離 |
| ChatGPT 等の外部会話履歴 | SQLite | DuckDB / Parquet | 取り込み後に分析可能化 |
| UI 状態・ユーザー設定 | SQLite | 原則不要 | アプリ状態 |
| ジョブ・同期状態 | SQLite | 必要なら DuckDB へ複製 | ジョブ管理 |

---

## 4. データ種別別の方針

### 4.1 会話履歴

会話履歴は **SQLite を正本**とする。

**理由:** スレッド/メッセージの構造は更新系に属し、逐次保存・削除・ラベル付けなど CRUD 要求が増えやすく、ライフログ本体よりもアプリケーション状態に近い。

**分析の逃がし先:** 会話履歴のうち分析に必要なものは Parquet にエクスポートし、DuckDB で扱う。

想定分析: 月別メッセージ数、モデル別 usage 集計、ツール利用傾向、外部ライフログと会話の相関分析。

**ベクトル化:** 会話検索の embedding / vector index は正本ではなく派生インデックスとして扱う。ベクトル検索の方式を見直しても正本スキーマが破綻しない構造にする。

### 4.2 ライフログ（Spotify / GitHub / Browser History 等）

**正本:** Raw JSON（監査用） + Parquet（分析用）

**フロー:** Collector → Transform → R2（raw/ + events/ + master/）→ Compaction → compacted Parquet

**アクセス:** Backend の ToolExecutor が DuckDB `:memory:` で httpfs 経由（またはローカルミラー）から直接クエリ。

### 4.3 アプリケーション状態

**正本:** SQLite のみ。分析基盤へのエクスポートは原則不要。

該当: UI 状態（既読、ピン留め）、ユーザー設定、小規模マスターデータ。

### 4.4 ベクトル検索インデックス（未実装）

正本とは完全に分離された派生インデックス。ID とフィルタリング用メタデータのみを保持する。実装方式は別途技術選定。

---

## 5. 運用ルール

### 5.1 判断フローチャート

新しいデータを追加する際は、以下の順で判定する。

```
UI/APIから逐次更新される？ → Yes → SQLite
    ↓ No
後から集計・横断分析したい？ → Yes → Parquet + DuckDB
    ↓ No
長期保存・監査用？ → Yes → Raw JSON (R2)
    ↓ No
将来的に検索インデックスを作る？ → Yes → 正本とは分けて派生インデックスとして設計
```

### 5.2 反パターン

以下は避ける。

- 更新系データを最初から分析基盤に直接押し込む
- ちょっとしたメタデータまで全部 DuckDB に集約する
- 正本、分析用派生、検索インデックスの境界を曖昧にする
- ベクトル検索の都合で正本スキーマを歪める

### 5.3 ガードレール

1. 更新系の正本は SQLite に置く
2. Parquet は分析用・長期保存用に限定する
3. 派生データは再生成可能に保つ
4. 正本、分析用派生、検索インデックスの境界を分ける
5. 「DuckDB でできるから」で更新系まで DuckDB に寄せない

この前提を守れる限り、EgoGraph の Parquet-first は合理的な選択である。
もし将来の主役がライフログ分析よりもアプリケーション状態管理に寄るなら、アーキテクチャ全体の重心を SQLite 側へ見直してよい。
