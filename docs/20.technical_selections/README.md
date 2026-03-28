# 技術選定詳細

## 概要

EgoGraphの各コンポーネントにおける技術選定の詳細と比較検討。

---

## ドキュメント一覧

| ドキュメント | 内容 |
|---|---|
| [embedding](./embedding.md) | Embedding戦略の詳細（Nomic Embed選定理由、比較） |
| [chat-history-storage](./chat-history-storage.md) | チャット履歴の永続化（DuckDBローカル保存の選定理由） |
| [youtube-history-collection](./youtube-history-collection.md) | YouTube視聴履歴収集（Playwright + MyActivity スクレイピング選定理由） |
| [kmp-cmp-migration](./kmp-cmp-migration.md) | Kotlin Multiplatform / Compose Multiplatform 移行記録 |

---

## 今後追加予定

- Vector Database選定（Qdrantを選んだ理由）
- LLM選定（DeepSeek vs その他）
- Backend Framework選定

---

## 関連ドキュメント

- [技術スタック概要](../10.architecture/01-overview/tech-stack.md)
- [システムアーキテクチャ](../10.architecture/)