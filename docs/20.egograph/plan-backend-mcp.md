# Plan: Backend MCP Server 化

EgoGraph Backend の既存ツール（ToolBase 9個）を MCP Server として公開する。新規に `data_query` ツールを追加し、`mcp` Python SDK (FastMCP) で Streamable HTTP / stdio トランスポートを提供する。

> **Note**: 以下の具体的なコード例・API 設計・構成（How）はあくまで参考である。実装時によりよい設計方針があれば積極的に採用すること。

## 設計方針

- **既存DDD構造を変更しない**: `domain/`, `usecases/`, `infrastructure/` は一切変更せず、薄いMCPラッパー層を追加するのみ
- **FastMCP + 低レベルServer API のハイブリッド**: FastMCP で transport/lifecycle を管理し、低レベル `Server` の `list_tools`/`call_tool` ハンドラで ToolBase の既存 JSON Schema をそのまま使用する。これにより既存コードの input_schema 定義を再利用し、ラッパー関数の型注釈メンテナンスを不要にする
- **MCP SDK v1.27.0**: `mcp` パッケージ（PyPI）。SSE は非推奨化のため Streamable HTTP を主トランスポートとし、ローカル用途で stdio もサポート
- **段階的移行**: 既存 FastAPI REST API は残存。`--mcp` CLIフラグでモード切替。別Issue で段階的に REST → MCP へ完全移行

## Plan スコープ

実装(TDD) → コミット(意味ごとに分離) → PR作成

> WT作成は済み（`feat/backend-mcp` ブランチで作業中）

## 対象一覧

| 対象 | 既存/新規 | 内容 |
|---|---|---|
| `mcp` 依存関係 | 新規 | pyproject.toml に `mcp>=1.27.0` 追加 |
| `DataQueryTool` | 新規 | DuckDB生SQL実行ツール（SELECTのみ許可） |
| `mcp_server.py` | 新規 | FastMCP サーバーエントリーポイント |
| `main.py` | 変更 | `--mcp` CLIフラグによるモード切替追加 |
| `factory.py` | 変更 | `DataQueryTool` のツールレジストリ登録 |
| `test_data_query.py` | 新規 | DataQueryTool テスト |
| `test_mcp_server.py` | 新規 | MCP Server テスト |

---

## Step 1: MCP SDK 依存関係追加

### GREEN: 実装

`egograph/backend/pyproject.toml` の `dependencies` に `mcp>=1.27.0` を追加。

```toml
# MCP Server
"mcp>=1.27.0",
```

`uv sync` でインストール確認。

### コミット

`build: add mcp python sdk dependency`

---

## Step 2: DataQueryTool (TDD)

### 前提: Step 1 完了（mcp パッケージ利用可能）

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_execute_select_returns_results` | SELECT文でDuckDBクエリ結果が返ること |
| `test_execute_select_with_params` | プレースホルダ付きSELECTが実行できること |
| `test_execute_select_empty_result` | 結果0件時に空リストが返ること |
| `test_execute_rejects_drop_table` | DROP TABLEがValueErrorで拒否されること |
| `test_execute_rejects_insert` | INSERTがValueErrorで拒否されること |
| `test_execute_rejects_delete` | DELETEがValueErrorで拒否されること |
| `test_execute_rejects_update` | UPDATEがValueErrorで拒否されること |
| `test_execute_rejects_alter` | ALTERがValueErrorで拒否されること |
| `test_execute_rejects_create` | CREATEがValueErrorで拒否されること |
| `test_execute_case_insensitive_rejection` | 小文字の `drop table` も拒否されること |
| `test_execute_limit_enforced` | 結果行数がMAX_ROWSを超える場合エラーになること |
| `test_name_and_schema` | name="data_query"、input_schema に sql プロパティが含まれること |

### GREEN: 実装

新規 `egograph/backend/domain/tools/data_query.py`:

- `DataQueryTool(ToolBase)` クラス
- `name` = `"data_query"`
- `description` = DuckDB生SQLクエリ実行ツール（SELECTのみ）
- `input_schema` = `{ "sql": string (required), "params": array (optional) }`
- `execute(sql, params=None)` メソッド:
  - `_validate_sql()`: SQLがSELECT文で始まることを検証。DML/DDL（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE）を拒否
  - `DuckDBConnection` で `:memory:` 接続 → SQL実行
  - 結果を `list[dict]` に変換して返す
  - MAX_ROWS = 1000 で結果行数制限
- バリデーションは大文字小文字区別なし（`sql.strip().upper().startswith("SELECT")`）

### コミット

`feat: add data_query tool for raw SQL execution`

---

## Step 3: MCP Server エントリーポイント (TDD)

### 前提: Step 2 完了（DataQueryTool 利用可能）

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_create_mcp_server_returns_fastmcp` | `create_mcp_server()` が FastMCP インスタンスを返すこと |
| `test_list_tools_returns_all_tools` | `list_tools` ハンドラが10ツールを返すこと |
| `test_list_tools_tool_names` | 10ツールの名前が期待通りであること（get_top_tracks, get_commits 等 + data_query） |
| `test_list_tools_has_json_schema` | 各ツールの inputSchema が有効なJSON Schemaであること |
| `test_call_tool_spotify_stats` | `call_tool("get_top_tracks", {...})` が repository 経由で結果を返すこと（mock） |
| `test_call_tool_data_query` | `call_tool("data_query", {"sql": "SELECT 1"})` が結果を返すこと（mock） |
| `test_call_tool_unknown_raises` | 存在しないツール名でCallToolErrorが発生すること |
| `test_call_tool_execution_error` | ツール実行エラー時にCallToolErrorが返ること（mock） |

### GREEN: 実装

新規 `egograph/backend/mcp_server.py`:

```python
"""EgoGraph MCP Server - FastMCP エントリーポイント。"""

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, Tool as MCPTool

from backend.config import BackendConfig
from backend.usecases.tools.factory import build_tool_registry

logger = logging.getLogger(__name__)


def create_mcp_server(config: BackendConfig) -> FastMCP:
    """FastMCPサーバーを作成し、既存ToolBaseをMCPツールとして登録する。

    Args:
        config: Backend設定

    Returns:
        設定済みのFastMCPインスタンス
    """
    mcp = FastMCP(
        "EgoGraph",
        instructions="Personal data warehouse - access Spotify, GitHub, browser history data via tools.",
    )

    registry = build_tool_registry(config.r2)

    # 低レベルServerハンドラで既存ToolBaseのJSON Schemaをそのまま使用
    server = mcp._mcp_server

    @server.list_tools()
    async def list_tools() -> list[MCPTool]:
        return [
            MCPTool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
            )
            for tool in registry._tools.values()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        tool = registry._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        result = tool.execute(**arguments)
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, default=str),
            )]
        )

    return mcp
```

設計ポイント:
- `FastMCP._mcp_server` で低レベル `Server` にアクセスし、`list_tools`/`call_tool` ハンドラを直接登録
- ToolBase の既存 `input_schema` (JSON Schema) を MCP Tool の `inputSchema` にそのまま渡す
- 結果は JSON 文字列として `TextContent` で返す
- FastMCP の transport 管理（Streamable HTTP / stdio）はそのまま活用

### コミット

`feat: add MCP server entry point with dynamic tool registration`

---

## Step 4: factory.py へ DataQueryTool 登録

### 前提: Step 2, 3 完了

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_build_tool_registry_includes_data_query` | レジストリに data_query が含まれること |
| `test_build_tool_registry_total_count` | レジストリのツール数が10であること |

### GREEN: 実装

`egograph/backend/usecases/tools/factory.py` に `DataQueryTool` をインポート・登録:

```python
from backend.domain.tools.data_query import DataQueryTool
from backend.infrastructure.repositories import SpotifyRepository, ...
# ...
if r2_config:
    # 既存ツール登録...
    tool_registry.register(DataQueryTool(r2_config))
```

### コミット

`feat: register data_query tool in tool registry`

---

## Step 5: CLI モード切替 (TDD)

### 前提: Step 3 完了

### RED: テスト先行

| テストケース | 内容 |
|---|---|
| `test_main_mcp_stdio_mode` | `--mcp` フラグでMCPモードが起動すること |
| `test_main_rest_mode_default` | デフォルトでRESTモードが起動すること |

### GREEN: 実装

`egograph/backend/main.py` に `--mcp` / `--transport` 引数を追加:

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp", action="store_true", help="MCP Server mode")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http")
    args = parser.parse_args()

    if args.mcp:
        from backend.mcp_server import create_mcp_server
        config = BackendConfig.from_env()
        server = create_mcp_server(config)
        server.run(transport=args.transport)
    else:
        # 既存のFastAPI起動（変更なし）
        ...
```

### コミット

`feat: add --mcp CLI flag for MCP server mode`

---

## Step 6: 動作確認

- `uv run pytest egograph/backend/tests --cov=backend -v`
- `uv run ruff check egograph/backend/`
- `uv run ruff format --check egograph/backend/`
- MCP Server 起動確認（環境変数設定後）:
  - `uv run python -m egograph.backend.main --mcp --transport stdio`
  - `uv run python -m egograph.backend.main --mcp --transport streamable-http`

---

## Step 7: PR 作成

```bash
gh pr create --title "feat: Backend MCP Server 化" --body "..."
```

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `egograph/backend/pyproject.toml` | 変更 | `mcp>=1.27.0` 依存追加 |
| `egograph/backend/domain/tools/data_query.py` | **新規** | DataQueryTool (SELECTのみ生SQL) |
| `egograph/backend/domain/tools/__init__.py` | 変更 | data_query モジュールのエクスポート追加 |
| `egograph/backend/mcp_server.py` | **新規** | FastMCP サーバーエントリーポイント |
| `egograph/backend/main.py` | 変更 | `--mcp` / `--transport` CLI引数追加 |
| `egograph/backend/usecases/tools/factory.py` | 変更 | DataQueryTool 登録追加 |
| `egograph/backend/tests/test_data_query.py` | **新規** | DataQueryTool テスト |
| `egograph/backend/tests/test_mcp_server.py` | **新規** | MCP Server テスト |

---

## コミット分割

1. `build: add mcp python sdk dependency` — `pyproject.toml`, `uv.lock`
2. `feat: add data_query tool for raw SQL execution` — `domain/tools/data_query.py`, `domain/tools/__init__.py`, `tests/test_data_query.py`
3. `feat: add MCP server entry point with dynamic tool registration` — `mcp_server.py`, `tests/test_mcp_server.py`
4. `feat: register data_query tool in tool registry` — `usecases/tools/factory.py`, 該当テスト
5. `feat: add --mcp CLI flag for MCP server mode` — `main.py`, 該当テスト

---

## テストケース一覧（全 24 件）

### DataQueryTool (12)
1. `test_execute_select_returns_results` — SELECT文で結果が返る
2. `test_execute_select_with_params` — プレースホルダ付きSELECTが実行できる
3. `test_execute_select_empty_result` — 結果0件時に空リストが返る
4. `test_execute_rejects_drop_table` — DROP TABLE が拒否される
5. `test_execute_rejects_insert` — INSERT が拒否される
6. `test_execute_rejects_delete` — DELETE が拒否される
7. `test_execute_rejects_update` — UPDATE が拒否される
8. `test_execute_rejects_alter` — ALTER が拒否される
9. `test_execute_rejects_create` — CREATE が拒否される
10. `test_execute_case_insensitive_rejection` — 小文字の DML/DDL も拒否される
11. `test_execute_limit_enforced` — 結果行数MAX_ROWS制限
12. `test_name_and_schema` — name, input_schema の構造検証

### MCP Server (8)
13. `test_create_mcp_server_returns_fastmcp` — FastMCP インスタンス生成
14. `test_list_tools_returns_all_tools` — 10ツール返却
15. `test_list_tools_tool_names` — ツール名一覧の一致
16. `test_list_tools_has_json_schema` — inputSchema が有効
17. `test_call_tool_spotify_stats` — get_top_tracks 実行（mock）
18. `test_call_tool_data_query` — data_query 実行（mock）
19. `test_call_tool_unknown_raises` — 不明ツールでエラー
20. `test_call_tool_execution_error` — 実行エラー時のエラーハンドリング

### Tool Registry (2)
21. `test_build_tool_registry_includes_data_query` — data_query が登録済み
22. `test_build_tool_registry_total_count` — ツール総数10

### CLI モード切替 (2)
23. `test_main_mcp_stdio_mode` — `--mcp` でMCPモード起動
24. `test_main_rest_mode_default` — デフォルトでRESTモード起動

---

## 工数見積もり

| Step | 内容 | 見積もり |
|---|---|---|
| Step 1 | 依存関係追加 | ~5 行 |
| Step 2 | DataQueryTool + テスト | ~120 行（実装 60 + テスト 60） |
| Step 3 | MCP Server + テスト | ~150 行（実装 60 + テスト 90） |
| Step 4 | factory.py 変更 + テスト | ~25 行（実装 5 + テスト 20） |
| Step 5 | CLI モード切替 + テスト | ~45 行（実装 15 + テスト 30） |
| **合計** | | **~345 行** |
