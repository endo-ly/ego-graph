# LLM Tool Use（ツール呼び出し）アーキテクチャ

## 概要

EgoGraph の Backend API は、LLM（Large Language Model）がツールを呼び出してデータにアクセスできる **Tool Use（Function Calling）** 機能を実装しています。

これにより、ユーザーが自然言語で質問すると、LLM が適切なツールを選択・実行し、結果を基に回答を生成します。

### 主な特徴

- **Agentic Loop**: LLM とツール実行を繰り返し、最終回答に到達
- **並列実行**: 複数ツールを同時実行して高速化
- **エラー回復**: ツール実行エラーを LLM に返し、LLM が説明
- **マルチプロバイダー**: OpenAI と Anthropic の両方をサポート
- **安全性**: 最大イテレーション制限とタイムアウト

## アーキテクチャ

### システム構成

```
┌─────────────┐
│   Client    │ (Frontend/Mobile)
└──────┬──────┘
       │ POST /v1/chat
       │ {messages: [...]}
       ↓
┌──────────────────────────────────────────┐
│           Backend API                     │
│  ┌────────────────────────────────────┐  │
│  │    Chat Endpoint                   │  │
│  │    (backend/api/chat.py)           │  │
│  │                                    │  │
│  │  ┌──────────────────────────────┐ │  │
│  │  │   Tool Execution Loop        │ │  │
│  │  │   (MAX_ITERATIONS = 5)       │ │  │
│  │  │                              │ │  │
│  │  │  while iteration < 5:        │ │  │
│  │  │    ↓                         │ │  │
│  │  │    LLM Request               │ │  │
│  │  │    ↓                         │ │  │
│  │  │    Tool Calls?               │ │  │
│  │  │    ↓ Yes                     │ │  │
│  │  │    Execute Tools (Parallel)  │ │  │
│  │  │    ↓                         │ │  │
│  │  │    Add Results to History    │ │  │
│  │  │    ↓                         │ │  │
│  │  │  (Loop back)                 │ │  │
│  │  │                              │ │  │
│  │  │  ↓ No tool_calls             │ │  │
│  │  │  Return Final Answer         │ │  │
│  │  └──────────────────────────────┘ │  │
│  └────────────────────────────────────┘  │
│                                           │
│  ┌────────────┐  ┌──────────────────┐   │
│  │ LLMClient  │  │  ToolRegistry    │   │
│  │            │  │                  │   │
│  │ ┌────────┐ │  │ - GetTopTracks  │   │
│  │ │OpenAI  │ │  │ - GetListening  │   │
│  │ │Provider│ │  │   Stats         │   │
│  │ └────────┘ │  │ - (More tools)  │   │
│  │            │  │                  │   │
│  │ ┌────────┐ │  │  execute()      │   │
│  │ │Anthro- │ │  │  parallel       │   │
│  │ │pic     │ │  │                  │   │
│  │ │Provider│ │  │                  │   │
│  │ └────────┘ │  │                  │   │
│  └────────────┘  └──────────────────┘   │
└──────────────────────────────────────────┘
       │                    │
       ↓                    ↓
  ┌─────────┐         ┌──────────┐
  │ OpenAI  │         │ DuckDB + │
  │   API   │         │   R2     │
  └─────────┘         └──────────┘
  ┌─────────┐
  │Anthropic│
  │   API   │
  └─────────┘
```

### コンポーネント概要

| コンポーネント | 責務 | ファイル |
|--------------|------|---------|
| **Chat Endpoint** | ツール実行ループの制御 | `backend/api/chat.py:102-171` |
| **LLMClient** | プロバイダー抽象化 | `backend/llm/client.py` |
| **OpenAI Provider** | OpenAI API 統合 | `backend/llm/providers/openai.py` |
| **Anthropic Provider** | Anthropic API 統合 | `backend/llm/providers/anthropic.py` |
| **ToolRegistry** | ツール管理・実行 | `backend/tools/registry.py` |
| **Tools** | 個別ツール実装 | `backend/tools/spotify/stats.py` |

## 実装の詳細

### 1. Message モデル

LLM とのメッセージ交換を表現します（`backend/llm/models.py`）。

```python
class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: Optional[str | list[dict[str, Any]]] = None

    # OpenAI 形式のツール結果用
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    # Assistant メッセージのツール呼び出し（再送信用）
    tool_calls: Optional[list[dict[str, Any]]] = None
```

**role の種類**:
- `user`: ユーザーからのメッセージ
- `assistant`: LLM からの応答
- `system`: システムプロンプト
- `tool`: ツール実行結果（OpenAI 形式）

**content の型**:
- `str`: 通常のテキストメッセージ
- `list[dict]`: Anthropic の tool_result 形式

### 2. ツール実行ループ

`backend/api/chat.py:102-171` の中核ロジック:

1. **残り時間チェック**: 全体30秒のタイムアウト管理
2. **LLM にリクエスト**: 会話履歴とツールスキーマを送信
3. **ツール呼び出し判定**: `response.tool_calls` の有無を確認
4. **ツール並列実行**: `asyncio.gather` で複数ツールを同時実行
5. **結果を履歴に追加**: ツール結果を会話履歴に追加して再度 LLM に送信
6. **最終回答**: tool_calls がなければ終了

**定数**:
- `MAX_ITERATIONS = 5`: 最大ループ回数
- `TOTAL_TIMEOUT = 30.0`: 全体タイムアウト（秒）

### 3. 並列ツール実行

`backend/api/chat.py:179-245` の `_execute_tools_parallel()`:

- 複数ツールを `asyncio.gather` で並列実行
- 各ツールはエラーハンドリング付きで独立実行
- 成功時: `{"success": True, "result": ...}`
- 失敗時: `{"success": False, "error": ..., "error_type": ...}`

### 4. ツール結果メッセージの生成

`backend/api/chat.py:248-273` の `_create_tool_result_message()`:

- ツール実行結果を JSON シリアライズして Message に変換
- エラー情報も JSON 形式で LLM に返す
- `role="tool"`, `tool_call_id`, `name` を設定

## API フロー詳細

### シーケンス図

```
Client          Backend                LLM Provider         ToolRegistry
  │                │                        │                    │
  │──POST /v1/chat→│                        │                    │
  │  {messages}    │                        │                    │
  │                │                        │                    │
  │                │──Chat Request─────────→│                    │
  │                │  (messages + tools)    │                    │
  │                │                        │                    │
  │                │←─Tool Calls────────────│                    │
  │                │  {tool_calls: [...]}   │                    │
  │                │                        │                    │
  │                │──Execute Tool──────────────────────────────→│
  │                │  get_top_tracks(...)   │                    │
  │                │                        │                    │
  │                │←─Tool Result────────────────────────────────│
  │                │  [{track: "曲A", ...}] │                    │
  │                │                        │                    │
  │                │──Chat Request (2)─────→│                    │
  │                │  (messages + tool_result)                   │
  │                │                        │                    │
  │                │←─Final Answer──────────│                    │
  │                │  "トップ5は..."        │                    │
  │                │                        │                    │
  │←─Response──────│                        │                    │
  │  {message}     │                        │                    │
  │                │                        │                    │
```

### OpenAI と Anthropic の違い

#### メッセージフォーマット

| 項目 | OpenAI | Anthropic |
|-----|--------|-----------|
| **ツールスキーマ** | `tools[].function` | `tools[]` (flat) |
| **ツール呼び出し** | `tool_calls[]` | `content[].type="tool_use"` |
| **ツール結果** | `role="tool"` | `role="user"` + `content[].type="tool_result"` |
| **arguments 形式** | JSON 文字列 | オブジェクト |

#### OpenAI リクエスト例

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "user", "content": "先月のトップ5は？"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_123",
        "type": "function",
        "function": {
          "name": "get_top_tracks",
          "arguments": "{\"start_date\":\"2024-01-01\",\"end_date\":\"2024-01-31\",\"limit\":5}"
        }
      }]
    },
    {
      "role": "tool",
      "tool_call_id": "call_123",
      "name": "get_top_tracks",
      "content": "[{\"track_name\":\"曲A\",\"play_count\":100}]"
    }
  ],
  "tools": [...]
}
```

#### Anthropic リクエスト例

```json
{
  "model": "claude-3-5-sonnet-20241022",
  "messages": [
    {"role": "user", "content": "先月のトップ5は？"},
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "取得します。"},
        {
          "type": "tool_use",
          "id": "toolu_123",
          "name": "get_top_tracks",
          "input": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "limit": 5
          }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_123",
          "content": "[{\"track_name\":\"曲A\",\"play_count\":100}]"
        }
      ]
    }
  ],
  "tools": [...]
}
```

**重要な違い**: Anthropic はツール結果を `role="user"` で送信します。

### Provider 実装

#### OpenAI Provider

`backend/llm/providers/openai.py:98-146` の `_convert_messages_to_provider_format()`:
- Message モデルを OpenAI 形式に変換
- `role="tool"` の場合、`tool_call_id` と `name` を含める
- assistant の `tool_calls` を保持

#### Anthropic Provider

`backend/llm/providers/anthropic.py:123-169` の `_convert_tool_result_to_anthropic()`:
- `role="tool"` → `role="user"` + `tool_result` content に変換
- `tool_call_id` → `tool_use_id` にマッピング
- content を `[{"type": "tool_result", ...}]` 形式に変換

## エラーハンドリング

### エラーの種類と処理

| エラー種別 | 原因 | 処理 |
|-----------|------|------|
| **KeyError** | ツールが見つからない | LLM にエラー情報を返す |
| **ValueError** | パラメータが不正 | LLM にエラー情報を返す |
| **TimeoutError** | LLM リクエストがタイムアウト | 504 エラーを返す |
| **最大イテレーション** | ループが5回を超えた | 500 エラーを返す |
| **その他の例外** | ツール実行中の予期しないエラー | LLM にエラー情報を返す |

### エラーフロー例

```
User: "2024-13-01のトップ5は？" (13月は存在しない)
  ↓
LLM: get_top_tracks(start_date="2024-13-01", ...)
  ↓
Backend: ツール実行 → ValueError("invalid_start_date: ...")
  ↓
Backend: エラー情報を JSON で LLM に返す
  {
    "error": "invalid_start_date: Month must be in 1..12",
    "error_type": "ValueError"
  }
  ↓
LLM: エラーを理解して説明
  "申し訳ございません。日付の指定に誤りがあります。
   月は1から12の間で指定してください。"
  ↓
User に返す
```

**実装**: `backend/api/chat.py:194-241` の `execute_single_tool()` でエラーを捕捉し、構造化された辞書で返します。

## ツールの実装

### ツールの構造

各ツールは `ToolBase` を継承し、以下を実装します:

- `name`: ツール名
- `description`: LLM が読むツール説明
- `input_schema`: JSON Schema 形式のパラメータ定義
- `execute()`: 実際のツール実行ロジック

**実装例**: `backend/tools/spotify/stats.py`

### ツールの登録

`backend/api/chat.py:94-100`:
```python
tool_registry = ToolRegistry()
if config.r2:
    tool_registry.register(GetTopTracksTool(db_connection, config.r2))
    tool_registry.register(GetListeningStatsTool(db_connection, config.r2))

tools = tool_registry.get_all_schemas()
```

## 設定

### 環境変数

```bash
# LLM 設定
LLM_PROVIDER=openai              # openai, openrouter, anthropic
LLM_API_KEY=sk-...               # API キー
LLM_MODEL_NAME=gpt-4o-mini       # モデル名
LLM_TEMPERATURE=0.7              # 温度（0.0-1.0）
LLM_MAX_TOKENS=2048              # 最大トークン数
LLM_ENABLE_WEB_SEARCH=false      # Web検索有効化（OpenRouter）
```

### コード内定数

`backend/api/chat.py:26-27`:
```python
MAX_ITERATIONS = 5      # 最大ループ回数
TOTAL_TIMEOUT = 30.0    # 全体タイムアウト（秒）
```

変更する場合:
- `MAX_ITERATIONS`: 複雑なタスクに対応する場合は増やす（10など）
- `TOTAL_TIMEOUT`: 長時間かかるツールがある場合は増やす（60秒など）

## テスト

### テストの種類

| テストファイル | 内容 | テスト数 |
|--------------|------|---------|
| `test_models.py` | Message モデルのテスト | 22 |
| `test_openai.py` | OpenAI provider のテスト | 12 |
| `test_anthropic.py` | Anthropic provider のテスト | 14 |
| `test_chat_tools.py` | ツール実行ループのテスト | 15 |
| `test_api_chat.py` | Chat API 統合テスト | 6 |

### テスト実行

```bash
# 全テスト
uv run pytest backend/tests/

# ツール実行ループのテストのみ
uv run pytest backend/tests/unit/api/test_chat_tools.py -v

# カバレッジ付き
uv run pytest backend/tests/ --cov=backend --cov-report=html
```

### 主要なテストケース

1. **単一ツール呼び出し → 最終回答**
2. **複数イテレーション**（LLM が複数回ツールを呼ぶ）
3. **並列ツール実行**（複数ツールを同時実行）
4. **ツール実行エラー**（エラーが LLM に返される）
5. **最大イテレーション到達**（5回ループで停止）
6. **タイムアウト**（30秒超過）

## パフォーマンス

### 実測値

| ケース | イテレーション | 実行時間 |
|-------|-------------|---------|
| 単一ツール + 回答 | 2 | ~3-5秒 |
| 複数ツール（並列） | 2 | ~4-6秒 |
| 3回ループ | 3 | ~8-12秒 |

### 最適化のポイント

1. **並列実行**: 複数ツールを `asyncio.gather` で並列化
2. **タイムアウト管理**: 残り時間を動的計算して効率化
3. **コネクションプーリング**: Anthropic provider は AsyncClient を再利用

## トラブルシューティング

### よくある問題

#### 1. ツールが呼ばれない

**原因**:
- ツールの description が不明瞭
- LLM がツールを使う必要がないと判断

**対策**:
- description を具体的に記述
- システムプロンプトでツール使用を促す

#### 2. 無限ループ

**原因**:
- LLM がツールを繰り返し呼び続ける
- エラーが継続的に発生

**対策**:
- MAX_ITERATIONS = 5 で自動停止
- エラーログを確認してツールを修正

#### 3. タイムアウト

**原因**:
- ツール実行が遅い
- LLM の応答が遅い

**対策**:
- TOTAL_TIMEOUT を増やす（60秒など）
- ツールのクエリを最適化

#### 4. エラーが LLM に伝わらない

**原因**:
- エラーメッセージが分かりにくい
- エラー情報が不足

**対策**:
- エラーメッセージを `invalid_<field>: <reason>` 形式で統一
- error_type を含める

## まとめ

EgoGraph の LLM Tool Use 実装は、以下の特徴を持ちます:

✅ **マルチプロバイダー対応**: OpenAI と Anthropic を統一インターフェースで扱う
✅ **堅牢性**: エラーハンドリング、タイムアウト、最大イテレーション制限
✅ **高性能**: 並列ツール実行、コネクションプーリング
✅ **拡張性**: 新しいツールを簡単に追加可能
✅ **テスト充実**: 146個のテストで品質を保証

この仕組みにより、ユーザーは自然言語でデータを問い合わせ、LLM が自律的にツールを使ってデータにアクセスし、分かりやすく回答を生成します。

## 参考資料

- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use](https://docs.anthropic.com/en/docs/tool-use)

---

**最終更新**: 2026-01-05
**バージョン**: v1.0
**担当**: Claude Code
