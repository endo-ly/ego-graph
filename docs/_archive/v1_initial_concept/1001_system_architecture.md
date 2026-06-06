# システムアーキテクチャ

## 1. 全体構成図

**ハイブリッド・アーキテクチャ**：
構造化データ（事実・統計）はRDBに、非構造化データ（意味・文脈）はVector DBに保存し、**Agent（LLM + Tools）** がユーザーの意図に応じて最適なデータソースを選択して回答する。

```
                                            ┌────────────────────┐
                                            │ Monitoring / APM   │
                                            │ (Prometheus/Graf.) │
                                            └──────────┬─────────┘
                                                       │
┌──────────────┐     ┌─────────────┐     ┌───────────▼──────────┐
│ Data Sources │────▶│ Collectors  │────▶│ Ingestion Orchestr.  │
│              │     │             │     │ (GitHub Actions)     │
└──────────────┘     └─────────────┘     └───────────┬──────────┘
                                                     │
                                                     ▼
                                         ┌──────────────────────────┐
                                         │ Data Warehouse (Events)  │
                                         │ (Supabase / PostgreSQL)  │
                                         │                          │
                                         │ - Raw JSON logs          │
                                         │ - Normalized tables      │
                                         └───────────┬──────────────┘
                                                     │
                                         ┌───────────▼──────────────┐
                                         │ Summarizer / Embedder    │
                                         │ (LlamaIndex / Ruri-v3)   │
                                         │                          │
                                         │ - Generate Daily Summary │
                                         │ - Semantification        │
                                         │ - Vectorize              │
                                         └───────────┬──────────────┘
                                                     │
                                                     ▼
                                         ┌──────────────────────────┐
                                         │ Vector Database          │
                                         │ (Qdrant)                 │
                                         │                          │
                                         │ - Summaries              │
                                         │ - Unstructured Chunks    │
                                         └───────────┬──────────────┘
                                                     │
                                                     │
┌──────────────┐                                     │
│ User Query   │                                     │
└──────┬───────┘                                     │
       │                                             │
       ▼                                             │
┌──────────────┐    ┌────────────────────────────────▼──────────────────┐
│ Application  │    │ Agent Layer (Function Calling / Reasoning)        │
│ Layer        │───▶│                                                   │
│ (FastAPI)    │    │ ┌───────────────┐  ┌───────────────────────────┐  │
└──────────────┘    │ │ Tool: SQL     │  │ Tool: Vector Search       │  │
                    │ │ (Analytics)   │  │ (Fuzzy Recall)            │  │
                    │ └───────┬───────┘  └─────────────┬─────────────┘  │
                    └─────────┼────────────────────────┼────────────────┘
                              │                        │
                              ▼                        ▼
                       (Query Supabase)          (Query Qdrant)
```

---

## 2. 各レイヤーの詳細

### 2.1 Storage Layer（ストレージ層）：ハイブリッド構成

データの性質に応じて保存先を厳格に分離する。

#### A. Data Warehouse (Supabase / PostgreSQL)
**「事実（Facts）」の保存場所**。
- **役割**:
  - 生データ（Raw JSON）の永続化
  - 構造化データの正規化保存（SQLテーブル）
  - 正確な集計・分析（SUM, COUNT, AVG, 推移）の実行
- **格納データ**:
  - Spotify再生履歴（全件）
  - 銀行取引明細
  - 位置情報ログ
  - 健康データ（歩数、心拍数）

#### B. Vector Database (Qdrant)
**「意味（Meaning）」の保存場所**。
- **役割**:
  - テキストの意味検索（Semantic Search）
  - 曖昧な記憶の想起（Recall）
  - 膨大なログの「要約」の保持
- **格納データ**:
  - デイリーサマリー（「今日は13~15時にXXの音楽を聴いた」）
  - 日記、メモ、メール本文
  - Web記事のチャンク

### 2.2 Ingestion & Processing（取り込み・処理層）

1. **Collection**: GitHub Actionsで各APIからデータを取得。
2. **Load to SQL**: まずSupabaseに生データ（Raw）と正規化データ（Structured）を格納。**ここが正（Source of Truth）となる**。
3. **Summarization**:
   - Supabaseから「昨日のデータ」を読み込む。
   - LLMを使って「デイリーサマリー」や「特徴的なイベント」を文章化（Semantification）。
4. **Embedding**: 生成されたテキストを `Ruri-v3` でベクトル化し、Qdrantへ保存。

### 2.3 Agent Layer（エージェント層）

従来の「いきなりベクトル検索」ではなく、**ユーザーの質問意図を解釈してツールを使い分けるエージェント**を配置する。

- **Tool: SQL Client**
  - **発動条件**: 「何回？」「合計は？」「いつ？」「推移は？」などの分析的質問。
  - **動作**: LLMがSQLクエリを生成し、Supabaseに対して実行。正確な値を返す。
  - **例**: 「先月の食費の合計は？」→ `SELECT SUM(amount) FROM transactions WHERE category = 'food' ...`

- **Tool: Vector Search**
  - **発動条件**: 「どんな感じ？」「あれなんだっけ？」「要約して」などの定性的・探索的質問。
  - **動作**: クエリをベクトル化し、Qdrantから類似テキスト（要約やメモ）を検索。
  - **例**: 「先月、悲しい時に聴いてた曲は？」→ `vector_search("sad music last month")`

### 2.4 Application Layer（アプリケーション層）

- **FastAPI**: エージェントのホスティング、認証（Supabase Auth）、API提供。
- **Next.js**: チャットUI、ダッシュボード（Supabaseから直接統計データを引くことも可能）。

---

## 3. データフロー

### 3.1 Ingestion Flow（取り込みフロー）

```
1. Data Sources (Spotify, Bank, etc.)
   ↓
2. Collectors (Python Scripts)
   ↓
3. Supabase (Insert Raw/Structured Data)  <-- ここでデータ確定
   ↓
4. Processing Job (Daily/Weekly Batch)
   ↓ (Fetch structured data)
5. LLM Summarizer (Generate Text Summary)
   ↓
6. Embedding (Ruri-v3)
   ↓
7. Qdrant (Upsert Vectors)
```

### 3.2 Query Flow（検索フロー）

```
1. User Query ("先月の食費は？")
   ↓
2. Agent (Router)
   ↓ (Decision: Analytics needed -> Use SQL Tool)
3. Tool: SQL Client
   ↓ (Generate & Execute SQL)
4. Supabase
   ↓ (Return: 45,000 JPY)
5. Agent (Format response)
   ↓
6. Response ("先月の食費は45,000円でした。")
```

---

## 4. スケーラビリティとプライバシー

### 4.1 プライバシー（機密データの扱い）
- **Supabase**: RLS (Row Level Security) を設定し、将来的なマルチユーザー対応やアクセス制御に備える。
- **機密性の高いテキスト**: ベクトル化する際、個人情報（PII）はマスクするか、ローカル/プライベートなQdrantインスタンス（NAS）のみに保存するルーティングを行う。

### 4.2 スケーラビリティ
- **Supabase**: 数百万行レベルならPostgreSQLの標準機能で十分高速。パーティショニングも検討。
- **Qdrant**: 全ログをベクトル化せず「要約」のみを保存するため、インデックスサイズを抑制できる。
