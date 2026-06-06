# 技術スタック

## 1. 概要

本ドキュメントでは、EgoGraphの各コンポーネントにおける技術選定とその理由を記載する。
**ハイブリッド・アーキテクチャ（SQL + Vector）** への移行に伴い、Supabaseをコアコンポーネントとして採用する。

---

## 2. コンポーネント別技術選定

### 2.1 Data Warehouse (Core Storage)

| 用途 | 技術 | 理由 |
|---|---|---|
| **構造化データ保存** | **Supabase (PostgreSQL)** | - **必須**: 堅牢なRDB機能（ACIDトランザクション）<br>- **分析**: SQLによる正確な集計が可能<br>- **Auth**: 認証機能が統合されている<br>- **API**: REST/GraphQL APIが自動生成される |
| **生データ保存** | PostgreSQL JSONB | JSONをそのまま格納しつつインデックスが効く |

**Supabaseを選んだ理由**：
- フルマネージドなPostgreSQLであり、運用コストが低い
- Row Level Security (RLS) により、将来的なマルチユーザー対応時のセキュリティが確保しやすい
- ベクトル検索機能（pgvector）も一応持っているが、今回は**分析用DB**として特化して使用する

### 2.2 Vector Database (Semantic Storage)

| 用途 | 技術 | 理由 |
|---|---|---|
| **意味検索** | **Qdrant** | - 検索速度と精度（HNSW）<br>- メタデータフィルタリングが強力<br>- Pythonクライアントが使いやすい |
| **保存対象** | 要約、非構造化テキスト | Fact（事実）ではなくMeaning（意味）を保存 |

### 2.3 Agent / LLM Provider

| 用途 | 技術 | 理由 |
|---|---|---|
| **Agent LLM** | **OpenAI GPT-4o** or **DeepSeek v3** | - **必須**: 高度なFunction Calling能力<br>- 複雑なSQL生成やツール選択の判断が必要 |
| **Embedding** | **Ruri-v3 (Local)** | - 日本語特化、プライバシー保護 |
| **Summarizer** | **DeepSeek v3** | - コストパフォーマンスが高く、大量のログ要約に適する |

### 2.4 Data Collection（データ収集）

| 用途 | 技術 | 理由 |
|---|---|---|
| **API連携** | Python + `requests` | 汎用性が高く、各種APIクライアントライブラリが充実 |
| **Spotify API** | `spotipy` | Spotify公式推奨のPythonライブラリ |
| **Webスクレイピング** | Playwright | JavaScriptレンダリング対応、PDFダウンロード可能 |
| **Batch処理** | GitHub Actions | 定期実行（cron）基盤として利用 |

### 2.5 Orchestration (Agentic Workflow)

| 用途 | 技術 | 理由 |
|---|---|---|
| **Framework** | **LangChain** or **LlamaIndex** | - Agent構築、Tool定義が容易<br>- SQLChainなどの既存コンポーネントが活用できる |
| **Server** | **FastAPI** | Python製のAgentをAPIとして公開 |

---

## 3. デプロイ構成

### Phase 1 (MVP)

| コンポーネント | デプロイ先 |
|---|---|
| **Data Warehouse** | **Supabase Cloud (Free Tier)** |
| **Vector DB** | **Qdrant Cloud (Free Tier)** |
| **Ingestion** | GitHub Actions |
| **Agent API** | Local / Cloud Run (Optional) |

---

## 4. 技術選定の原則（改定）

1. **適材適所 (Right Tool for the Right Job)**
   - **集計・分析** → RDB (SQL)
   - **探索・想起** → Vector DB (Semantic Search)
   
2. **プライバシーとセキュリティ**
   - 機密データ（Raw Logs）はRLSで保護されたSupabaseへ
   - Embeddingモデルはローカル実行を推奨

3. **Agentic Design**
   - 静的なパイプラインではなく、LLMが自律的にツール（SQL, Search）を選択する動的な構成を目指す

---

## 参考

- [システムアーキテクチャ](./1001_system_architecture.md)
- [データモデル](./1002_data_model.md)
