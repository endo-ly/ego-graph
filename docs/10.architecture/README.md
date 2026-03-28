# システムアーキテクチャ

## 概要

EgoGraphのシステムアーキテクチャ設計。全体構成、データモデル、技術スタック、セキュリティ対策を定義。

---

## ドキュメント構成

### 01-overview: 全体設計

| ドキュメント | 内容 |
|---|---|
| [system-architecture](./01-overview/system-architecture.md) | 全体構成図、データフロー、各レイヤーの役割 |
| [data-strategy](./01-overview/data-strategy.md) | データ戦略：ストレージ責務分離、データモデル、判断基準 |
| [tech-stack](./01-overview/tech-stack.md) | コンポーネント別技術選定と理由 |

### 02-backend: バックエンド設計

| ドキュメント | 内容 |
|---|---|
| [architecture](./02-backend/architecture.md) | Clean Architecture (DDD) 設計 |
| [tool-system](./02-backend/tool-system.md) | LLM Tool Use（ツール呼び出し）アーキテクチャ |
| [streaming](./02-backend/streaming.md) | LLM ストリーミングアーキテクチャ |

### 02-frontend: フロントエンド設計

| ドキュメント | 内容 |
|---|---|
| [architecture](./02-frontend/architecture.md) | MVVMアーキテクチャ、状態管理 |
| [chat](./02-frontend/chat.md) | チャット機能設計 |
| [terminal](./02-frontend/terminal.md) | ターミナル機能設計 |
| [settings](./02-frontend/settings.md) | 設定・サイドバー機能設計 |

### 03-ingest: データ収集設計

| ドキュメント | 内容 |
|---|---|
| [README](./03-ingest/README.md) | データソース別設計の概要 |
| [spotify](./03-ingest/spotify.md) | Spotifyデータソース設計 |
| [GitHub](./03-ingest/github.md) | GitHubデータソース設計 |
| [browser-history](./03-ingest/browser-history.md) | ブラウザ履歴データソース設計 |
| [_template](./03-ingest/_template.md) | データソース設計テンプレート |

---

## 設計原則

### プライバシーファースト

すべての設計判断において、プライバシー保護を最優先する。

- 機密データはPrivate DB（NAS）に隔離
- LLM送信前に必ずマスク処理
- データは自己管理、第三者サービスへの依存を最小化

### ストレージ責務分離

SQLite と DuckDB / Parquet を責務で分離する。

- 更新系・会話履歴・運用メタデータ → SQLite
- 分析・集計・横断参照 → DuckDB
- 分析用データセット・長期保存 → Parquet

詳細は [data-strategy](./01-overview/data-strategy.md) を参照。

### 段階的実装

MVPから始め、段階的に機能拡張する。

---

## 関連ドキュメント

- [技術選定詳細](../20.technical_selections/)
