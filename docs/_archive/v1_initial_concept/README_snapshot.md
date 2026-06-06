# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

EgoGraphは、個人データ統合RAGシステム。
**ハイブリッド・アーキテクチャ (SQL + Vector)** を採用し、正確な分析と意味検索の両立を目指す。

## アーキテクチャ方針

### 1. Hybrid Storage Strategy
- **Supabase (PostgreSQL)**: **事実 (Facts)** のためのSSOT（Single Source of Truth）。
  - 履歴・時系列などの構造化データ
  - 用途: 集計 (COUNT, SUM), 時系列分析, 正確な値の取得
- **Qdrant (Vector DB)**: **意味 (Meaning)** のための検索インデックス。
  - 用途: あいまい検索, 要約の検索 (Recall), 履歴・時系列データの**デイリーサマリー**
  - **重要**: Atomicなログ（1曲ごとの再生など）は原則ベクトル化しない。

### 2. Agentic Workflow
- ユーザーのクエリに対して、**Agent** がツールを使い分ける。
- `Tool: SQL_Client` vs `Tool: Vector_Search`

## 開発コマンド (uv)

```bash
# 全依存関係の同期
uv sync

# Spotify取り込み (現状のIngestコードは要改修)
uv run --package egograph-ingest python ingest/main.py
```

## データモデル

### SQL: `events` Table (Supabase)
```sql
TABLE events (
  id UUID,
  source VARCHAR,      -- 'spotify', 'bank'
  category VARCHAR,    -- 'music', 'transaction'
  occurred_at_utc TIMESTAMPTZ,
  data JSONB,          -- { "track": "...", "amount": 1000 }
  metadata JSONB
)
```

### Vector: Payload (Qdrant)
- `text`: 日次要約などの自然言語テキスト
- `metadata`: `source: daily_summary`, `date: 2023-12-11`

## ディレクトリ構成

- **`ingest/`**: データ収集 (SuppabaseへのInsert担当)
- **`shared/`**: 共通モデル (SQLModel/Pydantic)
- **`backend/`**: Agent API (FastAPI)
- **`docs/`**: 設計ドキュメント

## 重要な実装ポイント

1. **Atomic Logs are SQL only**:
   - 個別のログ（曲再生、取引）はSQLにのみ保存する。
   - ベクトル化するのは「要約」のみ。

2. **Summarization Batch**:
   - 定期的にSQLからデータを引き、「要約」を生成してQdrantへSyncするバッチが必要。

3. **Function Calling**:
   - Agentは必ずTool経由でデータにアクセスする。直接DBを叩くRAGではない。

## 主要ファイル

### コアモデル
- `shared/models.py`: UnifiedDataModelとEnum定義
- `shared/config.py`: 設定管理

### 取り込みパイプライン
- `ingest/main.py`: メインパイプライン（5ステップ）
- `ingest/spotify/collector.py`: Spotify API収集
- `ingest/spotify/transformer.py`: Spotify→UnifiedDataModel変換
- `ingest/pipeline/etl.py`: LlamaIndex ETL処理
- `ingest/pipeline/embeddings.py`: ローカル埋め込み生成
- `ingest/pipeline/storage.py`: Qdrant保存

### ドキュメント
- `docs/10.architecture/1001_system_architecture.md`: システム設計全体
- `docs/10.architecture/1002_data_model.md`: Lexiaスキーマ詳細
- `docs/90.plan/mvp_spotify/00.plan.md`: MVP実装計画

## Obsidianの活用

技術的な学びなどのナレッジや、複雑な問題が解決できた場合、知識財産としてObsidianにまとめます。
`~/myVault` がObsidianのデータディレクトリです。