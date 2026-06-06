# データモデル

## 1. 概要

EgoGraphは、データの性質に応じて「**事実（Facts）**」と「**意味（Meaning）**」を分離して管理する。

- **Supabase (PostgreSQL)**: すべての「事実」データ（構造化ログ、トランザクション）を格納。
- **Qdrant (Vector DB)**: 「意味」データ（要約、自然言語テキスト、埋め込みベクトル）を格納。

---

## 2. SQL Schema definition (Supabase)

Supabaseは「Data Warehouse」として機能し、すべての生データと構造化データを保持する。

### 2.1 `events` Table (Universal Log)

すべての時系列イベントを格納する統合テーブル。
検索性を高めるため、JSONBカラムに詳細データを格納する。

```sql
CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  
  -- 基本属性
  user_id UUID NOT NULL REFERENCES auth.users(id),
  source VARCHAR(50) NOT NULL,    -- 'spotify', 'bank', 'location'
  category VARCHAR(50) NOT NULL,  -- 'music', 'transaction', 'place'
  
  -- 時間情報 (Timezone aware & Local)
  occurred_at_utc TIMESTAMPTZ NOT NULL,
  local_date DATE NOT NULL,       -- '2023-12-11' (パーティショニング用)
  
  -- データ本体
  data JSONB NOT NULL,            -- 構造化データの本体
  metadata JSONB,                 -- その他の付属情報
  
  -- 管理用
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX idx_events_source_date ON events (source, local_date);
CREATE INDEX idx_events_data_gin ON events USING GIN (data);
```

### 2.2 `daily_summaries` Table

1日ごとの要約テキストを保持するテーブル。ここからQdrantへの同期を行う。

```sql
CREATE TABLE daily_summaries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  target_date DATE NOT NULL,
  
  content TEXT NOT NULL,          -- 生成された要約テキスト
  summary_metadata JSONB,         -- 'mood', 'primary_activity' など
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 3. Lexia標準スキーマ (Vector DB / Qdrant)

Qdrantには、上記のSQLデータから派生した「**意味（Meaning）**」のみを格納する。
主に「要約（Summary）」や「非構造化チャンク（Chunk）」が対象となる。

### 3.1 Payload構造

```json
{
  "id": "uuid-v4",
  "text": "テキスト本文（要約やチャンク）",
  
  "metadata": {
    // リンク情報
    "source": "daily_summary",
    "linked_sql_ids": ["uuid-1", "uuid-2"], // 関連するSupabase上のID
    "date": "2023-12-11",
    
    // 文脈情報
    "topics": ["work", "coding", "jazz"],
    "sentiment": "positive",
    
    // アクセス制御
    "access_group": "private"
  },
  
  "vector": [/* 768 dim vector */]
}
```

### 3.2 粒度（Granularity）の方針変更

以前はすべてのログ（Atomic）をベクトル化しようとしていたが、**Atomicデータのベクトル化は廃止（または限定的）**とする。

| データ種別 | 以前の方針 | **新方針** | 理由 |
|---|---|---|---|
| スポット再生 (Spotify) | 全曲ベクトル化 | **しない** (SQLで集計) | 「あの曲」検索はSQLまたは外部APIで十分。 |
| 銀行取引 (Bank) | 全件ベクトル化 | **しない** (SQLで集計) | 「食費いくら？」はSQLの方が正確。 |
| 位置情報 (Location) | 全ログベクトル化 | **しない** (Daily Summaryに統合) | 「渋谷にいた」という事実だけ要約に残す。 |
| 日記・メモ (Note) | ベクトル化 | **ベクトル化 (Chunk)** | 意味検索の対象として最適。 |
| Web記事 (Browser) | 全件ベクトル化 | **要約のみベクトル化** | 全文検索より「どんな記事読んだ？」の想起を優先。 |

---

## 4. データフローと連携

### 4.1 SQL → Vector (Summarization)

Agentic Workflowにより、SQLに溜まった「事実」をLLMが読み込み、「意味」に変換してVector DBへ送る。

> **例：12月11日の処理**
> 1. **SQL Query**: `SELECT * FROM events WHERE local_date = '2023-12-11'`
> 2. **Result**: Spotify 50曲, 銀行取引 3件（コンビニ）, 位置情報（会社→自宅）
> 3. **LLM Generation**: *"12月11日は一日中会社で仕事をした。SpotifyでJazzを聴きながら集中し、帰りにコンビニで夕食を買った。"*
> 4. **Vector Upsert**: 生成されたテキストをEmbedしてQdrantへ。

### 4.2 検索時の使い分け (Function Calling)

ユーザーの質問に対して、AgentがどちらのDBを使うか判断する。

| 質問 | 判断 | 実行されるクエリ |
|---|---|---|
| **「先月いくら使った？」** | **分析 (SQL)** | `SELECT SUM(amount) FROM events WHERE category='transaction' ...` |
| **「最近どんな曲聴いてる？」** | **分析 (SQL)** | `SELECT data->>'track_name', COUNT(*) FROM events ... GROUP BY ...` |
| **「仕事が辛かったのはいつ？」** | **意味 (Vector)** | `qdrant.search("仕事 辛い")` → 要約から該当日を特定 |
| **「あの時買ったコーヒー、美味しかったっけ？」** | **ハイブリッド** | 1. `qdrant.search("コーヒー 美味しい")` (日記検索)<br>2. `sql.query(...)` (購入日時特定) |

---

## 5. データ品質管理

### 5.1 Supabase (SQL) 側

- **型制約**: `occurred_at_utc` などの必須カラムはNOT NULL制約で守る。
- **整合性**: `foreign key` 制約により、ユーザーID等の整合性を保つ。

### 5.2 Qdrant (Vector) 側

- **同期ズレの許容**: Vectorデータはあくまで「検索インデックス」であり、マスターデータではないため、多少の遅延は許容する。
- **再生成**: ロジック変更時は、Supabaseの生データからいつでもVectorを再生成（Re-index）できるようにする。

---

## 参考

- [システムアーキテクチャ](./1001_system_architecture.md)
- [技術スタック](./1004_tech_stack.md)
