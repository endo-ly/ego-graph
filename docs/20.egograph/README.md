# EgoGraph

Personal Data Warehouse。各種サービスからデータを定期収集し、Parquetファイルとして一元管理する。

## 構成

### [Backend (Data API + MCP Server)](./backend/architecture.md)

REST API と MCP (Model Context Protocol) で個人データへのアクセスを提供する。

- FastAPI + Uvicorn
- DuckDB `:memory:` + httpfs（R2 から直接 Parquet 読み込み）
- DDD (Domain-Driven Design) レイヤードアーキテクチャ
- REST API — ダッシュボード・可視化向け直接データアクセス
- MCP Server — AIエージェント向けツールインターフェース
- [MCP 設定例](./backend/architecture.md) — architecture.md 内「egopulse 設定例」

### [Pipelines Service](./pipelines/README.md)

常駐サービス。APScheduler によるスケジュール駆動でデータ収集を実行。

- SQLite で workflow / run / step / lock を管理
- 増分取り込み（カーソルで前回位置を追跡）
- 対応データソース: Spotify / GitHub / Browser History

## 関連ドキュメント

- [システム全体設計](../10.architecture/system-architecture.md)
- [データ戦略](../10.architecture/data-strategy.md)
- [技術スタック一覧](../10.architecture/tech-stack.md)
- [デプロイ手順](../50.deploy/backend.md)
