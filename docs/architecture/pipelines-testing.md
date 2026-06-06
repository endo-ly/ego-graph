# Pipelines テスト戦略

Pipelines Service のテスト実装に関する標準ガイドライン。

## 1. テスト層の責務

| 層 | ディレクトリ | 責務 | 外部依存 | CI |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | 単一コンポーネントのロジック正しさ・境界条件を検証。モックで外部依存を遮断。 | なし（全てモック） | ✅ |
| **Integration** | `tests/integration/` | パイプライン全体の契約・連携を検証。外部APIはモック、ストレージはインメモリS3で通す。 | モックAPI + インメモリS3 | ✅ |
| **E2E** | `tests/e2e/` | **サービス境界**を跨ぐオーケストレーションを検証。FastAPI → Dispatcher → Executor → Storage。 | in-memory S3 | ✅ |
| **Live** | `tests/live/` | 実外部APIとの接続を検証。認証情報が必要。CIからは除外。 | **実API** | ❌ |

### 各層の判断基準

- **Unit**: 「この関数は期待通りの値を返すか？」— 実装の正しさを保証
- **Integration**: 「パイプライン全体が正しく連携するか？」— Collector→Transform→Storage→Compaction のフローを保証
- **E2E**: 「サービス境界を跨いで動作するか？」— FastAPI API → Dispatcher → Executor のオーケストレーションを保証
- **Live**: 「実サービスは現在応答するか？」— 環境・認証・API互換性を保証

## 2. Integration テストの観点

各データソースの integration テストは以下の観点を網羅する:

| # | 観点 | 検証内容 |
|---|---|---|
| 1 | **Ingest全フロー** | `run_*_ingest()` が Collector→Transform→S3 Storage を通す |
| 2 | **Compaction** | `run_*_compact()` がS3読込→重複排除→書込 |
| 3 | **増分取得** | ingest_state → after指定 → 新規データのみ取得 |
| 4 | **べき等性** | 同一データを2回流しても重複しない |
| 5 | **Enrichment** | 新規IDのみマスター取得、既存はスキップ |
| 6 | **No-data早期リターン** | 新規データなしで保存処理を実行しない |

## 3. ディレクトリ構成

```
egograph/pipelines/tests/
├── unit/           # 単一コンポーネントのテスト
├── integration/    # パイプライン全体の結合テスト (観点1-6)
│   ├── spotify/
│   │   ├── test_ingest.py       # 観点1, 6
│   │   ├── test_compact.py      # 観点2, 4
│   │   ├── test_incremental.py  # 観点3
│   │   └── test_enrichment.py   # 観点5
│   ├── github/
│   └── browser_history/
├── e2e/           # サービス境界跨ぎ (FastAPI + Dispatcher + Executor)
│   └── test_browser_history_ingest.py
├── live/          # 実APIテスト（CI除外）
├── fixtures/      # 共有フィクスチャ・モックレスポンス
└── conftest.py    # 共有フィクスチャ定義
```

## 4. テスト実行コマンド

```bash
# CI用（unit + integration + e2e を明示的に指定）
uv run pytest egograph/pipelines/tests/unit \
              egograph/pipelines/tests/integration \
              egograph/pipelines/tests/e2e --cov=pipelines

# Unit のみ（高速）
uv run pytest egograph/pipelines/tests/unit -v

# 特定ソース
uv run pytest egograph/pipelines/tests/unit/spotify -v

# Live テスト（手動）
uv run pytest egograph/pipelines/tests/live -v -m live
```

## 5. 規約

- 全テストメソッドは AAA パターン（Arrange → Act → Assert）で記述
- Docstring は日本語でテストの目的を記述
- ファイル名は `test_{対象}.py`、メソッド名は `test_{条件}_{期待結果}`
- Integration テストはストレージにインメモリS3を使用し、本番と同じS3パス形式を検証する
