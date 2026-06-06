# システムアーキテクチャ

## 概要

EgoGraphのシステムアーキテクチャ設計。全体構成、データモデル、技術スタック、セキュリティ対策を定義。

---

## ドキュメント一覧

| ドキュメント | 内容 |
|---|---|
| [system-architecture](./system-architecture.md) | 全体構成図、データフロー、各レイヤーの役割 |
| [data-strategy](./data-strategy.md) | データ戦略：ストレージ責務分離、データモデル、判断基準 |
| [tech-stack](./tech-stack.md) | コンポーネント別技術選定一覧 |

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

詳細は [data-strategy](./data-strategy.md) を参照。

### 段階的実装

MVPから始め、段階的に機能拡張する。

---

## コンポーネント別ドキュメント

| コンポーネント | ドキュメント | 内容 |
|---|---|---|
| EgoGraph (Backend) | [20.egograph/backend/](../20.egograph/backend/) | Data API、MCP Server、DDD設計、Tool System |
| EgoGraph (Pipelines) | [20.egograph/pipelines/](../20.egograph/pipelines/) | データ収集サービス、各データソース設計 |
| Frontend | [40.frontend/](../40.frontend/) | KMP Androidアプリ、MVVM設計 |
| Deploy | [50.deploy/](../50.deploy/) | 各コンポーネントのデプロイ手順 |

### 関連リポジトリ

| リポジトリ | 内容 |
|---|---|
| [endo-ly/egopulse](https://github.com/endo-ly/egopulse) | AIエージェントランタイム（TUI/Web/Discord/Telegram） |

---

## 関連ドキュメント

- [技術選定詳細](../70.knowledge/technical-selections/)
