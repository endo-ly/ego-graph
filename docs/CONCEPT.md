# EgoGraph — 設計思想と背景

> 「自分のデータは自分で所有し、自分のために使う」

---

## Vision

**「自分自身のデジタル分身を構築し、過去の自分と対話・分析できる未来を創る」**

散在するデータを統合し、AIがその文脈を理解し、いつでもどこからでも自分の過去と未来について対話できる世界。データをエクスポートして死蔵するのではなく、常に生きた状態で、自分のために使える状態にしておく。

---

## Problem Statement

個人のデジタルデータは、Spotify、GitHub、ブラウザ、YouTubeなど数多くのサービスに分散している。これらのデータは各サービスの閉じた世界にあり、横断して振り返ることはできない。「去年の夏によく聴いていた曲は？」「あの技術記事をいつ読んだっけ？」——こうした問いに答えるには、サービスを一つずつ開いて探すしかない。

汎用的なAIチャットボットに聞いても、自分のデータにはアクセスできないため答えられない。AIは賢いが、私のことを何も知らない。

EgoGraphは、この2つの課題——**データの散在**と**AIのコンテキスト不足**——を同時に解決する。

---

## Architecture

EgoGraphは「データ基盤」に集中し、エージェントランタイムは独立したリポジトリ [endo-ly/egopulse](https://github.com/endo-ly/egopulse) で開発している。それぞれ単独でも価値を提供するが、組み合わせることで「自分のデータに基づいたAI」が実現する。

### Data Foundation — EgoGraph (Personal Data Warehouse)

各種サービスからデータを定期収集し、一元管理するデータウェアハウス。

**Parquetという選択**がこのプロジェクトの特徴だ。収集したデータをParquet形式で保存する。Parquetは列指向のオープンなフォーマットで、DuckDBなどの分析エンジンから直接クエリできる。データベースサーバーを立てる必要がない。ファイルとして存在し、いつでもコピー・移動・削除ができる。Cloudflare R2（S3互換）に置いておけば、どこからでもHTTPで読み出せる。DuckDBの `httpfs` 拡張を使えば、R2上のParquetを直接SQLで叩ける。サーバーレスで、インフラコストほぼゼロで、分析用データ基盤が完成する。

一度Parquetに落ちたデータは、もとのサービスが終了しても残る。エクスポートして死蔵するのではなく、いつでも問い合わせ可能な状態で手元に置いておく。

### Agent Runtime — [EgoPulse](https://github.com/endo-ly/egopulse)

EgoPulseは、OpenClawにインスパイアされた**Rust製のセルフホストAIエージェントランタイム**だ。独立したリポジトリで開発している。

OpenClawは「Any OS gateway for AI agents」を掲げ、Discord / Telegram / WhatsApp / Slack などのチャットアプリを単一のGatewayで束ね、どこからでもAIエージェントにアクセスできるようにする。EgoPulseはこの思想をRustで実装し、TUI / Web UI / Discord / Telegram を単一バイナリで提供する。

AIエージェントランタイムは長時間稼働し、並行して複数チャネルを処理する。この用途には、Tokioの非同期ランタイムとRustのメモリ安全性が適している。単一バイナリで配布でき、Node.jsのランタイムも不要。`egopulse setup` で対話型セットアップ、`egopulse run` で全チャネル起動、`egopulse gateway install` でsystemdに登録。個人サーバーに置いておけば、24時間365日、いつでもどこからでも自分のAIエージェントに話しかけられる。

---

## Design Principles

### My Data First

データは自分で所有し、自分でコントロールする。外部サーバーに預けてAPIで借り受けるのではなく、自分の管理下（R2またはローカル）に置く。Parquetというポータブルなフォーマットを選ぶのは、特定のプラットフォームにロックインされないためだ。

### Serverless & Local-First

データベースサーバーを立てない。分析はDuckDBのインメモリモードで、リクエスト毎にR2から直接Parquetを読み込む。状態管理はSQLiteで十分。インフラコストを最小に抑え、個人で持続可能な運用を目指す。

### Loose Coupling

EgoGraph（Pipelines、Backend）とEgoPulseとFrontendは、それぞれ独立して動作する。EgoPulseがなくてもEgoGraphはデータを収集・分析できる。EgoGraphがなくてもEgoPulseはAIエージェントとして動く。Frontendはその両方にアクセスするUI。ゆるい結合で、必要なところだけを使える。

### ストレージ責務分離

SQLite と DuckDB / Parquet を責務で分離する。

- 更新系・会話履歴・運用メタデータ → SQLite
- 分析・集計・横断参照 → DuckDB
- 分析用データセット・長期保存 → Parquet

詳細は [data-strategy.md §1.1](./architecture/data-strategy.md#11-ストレージ責務分離) を参照。

---

## Roadmap

### 現在

- EgoGraph: Pipelines + Backend（Data API / MCP Server）運用中
- EgoPulse: TUI / Web UI / Discord / Telegram 対応済み
- Frontend: Android チャットUI 実装済み

### 今後

- **MCP 統合**: EgoGraphのデータアクセスツールをMCPサーバーとして公開し、[EgoPulse](https://github.com/endo-ly/egopulse)などから自由に呼び出せるようにする。これにより、EgoGraph は複数の外部エージェントやツールから利用できる共通の個人データ基盤になる
- **データ可視化**: 個人データのグラフ・チャート表示（Frontend）
- **ベクトル検索**: Qdrantによる意味的検索の追加

---

## Repository Structure

```
egograph/
├── egograph/           # Data Foundation (Python / uv workspace)
│   ├── pipelines/      #   常駐ETLサービス — データ収集・変換・保存
│   └── backend/        #   Data API / MCP Server — 個人データの提供
├── frontend/           # Mobile App (Kotlin Multiplatform)
└── browser-extension/  # ブラウザ履歴収集 (Chromium)

endo-ly/egopulse        # Agent Runtime (Rust) — 独立リポジトリ
```

Pythonでデータ処理を、KotlinでモバイルUIを。各領域に最適な技術を選び、モノレポで一括管理する。エージェントランタイムは独立リポジトリで開発する。
