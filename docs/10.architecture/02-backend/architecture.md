# Backend Architecture

Clean Architecture に準拠した4層構造で実装されています。

## 依存関係ルール

```
Presentation → Application → Domain ← Infrastructure
     |              |           |           |
   API層      UseCase層   Domain層   Infrastructure層
```

- **API層**: UseCase層のみに依存
- **UseCase層**: Domain層のインターフェースに依存
- **Domain層**: 外部に依存しない（純粋なビジネスロジック）
- **Infrastructure層**: Domain層のインターフェースを実装

## 各層の責務

### Presentation Layer (api/)

HTTPリクエストの受付とレスポンスの生成。各エンドポイントは15-30行程度の薄いハンドラーで構成。

**責務:**
- HTTPリクエストの受付とバリデーション
- UseCase層への処理委譲
- レスポンスの整形
- エラーの HTTP ステータスコードへの変換

**API スキーマの配置:**
- 全ての API スキーマは `api/schemas/` に統一的に配置
- リクエスト/レスポンスモデルのみを定義（ビジネスロジックは含まない）

### Application Layer (usecases/)

ビジネスロジックのオーケストレーション。

**主要クラス:**
- `ChatUseCase`: チャット会話全体の管理
- `ToolExecutor`: LLMツール実行ループの管理
- `SystemPromptBuilder`: システムプロンプトの構築
- `ToolRegistry`: ツールの登録・管理・実行
- `llm_model/service`: LLM モデル取得サービス

### Domain Layer (domain/)

純粋なビジネスルールとドメインモデル。

**主要クラス:**
- `models/`: ドメインエンティティ
  - `ConversationContext`: 会話状態
  - `Tool`, `ToolBase`: ツールの抽象定義
  - `LLMModel`: LLM モデル情報
  - `Thread`, `ThreadMessage`: スレッド関連
  - `Message`, `ToolCall`, `ChatResponse`: LLM 関連
- `tools/`: 具体的なツール実装（ビジネスロジック）
  - `spotify/stats.py`: Spotify 統計ツール

### Infrastructure Layer (infrastructure/)

外部システムとの統合（DBアクセス、LLM呼び出し）。

**主要クラス:**
- `repositories/`: データアクセス層
  - `DuckDBThreadRepository`: スレッド管理
  - `SpotifyRepository`: Spotify データ取得
- `database/`: データベース接続とクエリ
- `llm/`: LLM プロバイダー統合

## 実装パターン

### 薄いルーター

```python
@router.post("", response_model=ChatResponse)
async def endpoint(request: ChatRequest, deps = Depends(get_deps)):
    # 1. API スキーマでリクエスト受付
    # 2. UseCase 用の内部リクエストに変換
    # 3. UseCase呼び出し
    # 4. API スキーマでレスポンス返却
```

### 依存性注入

`dependencies.py` で全ての依存性を注入（レイヤー横断の配線）。

### Repository パターン

データアクセスを抽象化し、テスタビリティを向上。ツール実装も Repository に依存してデータ取得を行う。

```python
# ツールはビジネスロジック（バリデーション）のみを担当
class GetTopTracksTool(ToolBase):
    def __init__(self, repository: SpotifyRepository):
        self.repository = repository

    def execute(self, start_date: str, end_date: str, limit: int):
        # バリデーション（ビジネスロジック）
        start, end = validate_date_range(start_date, end_date)
        validated_limit = validate_limit(limit)

        # データ取得は repository に委譲
        return self.repository.get_top_tracks(start, end, validated_limit)
```

## ディレクトリ構造

```
backend/
├── main.py                  # FastAPI アプリケーション
├── config.py                # 設定管理（BackendConfig、環境変数ベース）
├── dependencies.py          # 依存性注入
├── api/                     # Presentation Layer
│   ├── schemas/             # API スキーマ（統一配置）
│   │   ├── chat.py          # ChatRequest, ChatResponse
│   │   ├── data.py          # TopTrackResponse, ListeningStatsResponse
│   │   ├── models.py        # ModelsResponse
│   │   └── thread.py        # ThreadListResponse, ThreadMessagesResponse
│   ├── chat.py              # チャット API エンドポイント
│   ├── data.py              # データ API エンドポイント
│   ├── health.py            # ヘルスチェック
│   └── threads.py           # スレッド管理 API
├── usecases/                # Application Layer
│   ├── chat/
│   │   ├── chat_usecase.py  # ChatUseCaseRequest, ChatUseCase
│   │   ├── system_prompt_builder.py
│   │   └── tool_executor.py
│   ├── llm_model/
│   │   └── service.py       # get_model(), get_all_models()
│   └── tools/
│       └── registry.py      # ToolRegistry
├── domain/                  # Domain Layer
│   ├── models/              # ドメインエンティティ
│   │   ├── tool.py          # Tool, ToolBase
│   │   ├── llm_model.py     # LLMModel, MODELS_CONFIG, DEFAULT_MODEL
│   │   ├── llm.py           # Message, ToolCall, ChatResponse
│   │   ├── chat.py          # ConversationContext
│   │   └── thread.py        # Thread, ThreadMessage
│   └── tools/               # 具体的なツール実装
│       └── spotify/
│           └── stats.py     # GetTopTracksTool, GetListeningStatsTool
├── infrastructure/          # Infrastructure Layer
│   ├── database/
│   │   ├── connection.py
│   │   ├── chat_connection.py
│   │   └── queries.py
│   ├── llm/
│   │   ├── client.py
│   │   └── providers/
│   │       ├── base.py
│   │       ├── openai.py
│   │       └── anthropic.py
│   └── repositories/
│       ├── thread_repository_impl.py  # DuckDBThreadRepository
│       └── spotify_repository.py      # SpotifyRepository
└── tests/
    ├── conftest.py
    ├── integration/
    └── unit/
```

## 命名規約

| レイヤー | クラス名 | 例 |
|---------|---------|---|
| **API スキーマ** | `*Request`, `*Response` | `ChatRequest`, `ChatResponse` |
| **Domain モデル** | エンティティ名 | `Thread`, `Message`, `LLMModel` |
| **UseCase 内部** | `*UseCaseRequest`, `*Result` | `ChatUseCaseRequest`, `ChatResult` |

## レイヤー間の責務分離

### API スキーマ vs Domain モデル

- **API スキーマ** (`api/schemas/`): 外部との境界。HTTP リクエスト/レスポンスの形式を定義
- **Domain モデル** (`domain/models/`): 内部のビジネスロジック。純粋なドメイン概念を表現
  - エンティティ定義（例: `LLMModel`）とドメインデータ（例: `MODELS_CONFIG`）を統合管理

### 設定管理

- **環境変数設定** (`config.py`): 実行時に環境変数から読み込む動的設定（例: `BackendConfig`, `LLMConfig`）
- **ドメインデータ** (`domain/models/`): アプリケーション定義のマスターデータ（例: `MODELS_CONFIG`）

### ツール実装の責務分離

- **Domain Tools** (`domain/tools/`): バリデーションとビジネスルール
- **Repository** (`infrastructure/repositories/`): データ取得とDB接続

## エラーハンドリング

| UseCase例外 | HTTPステータス | 説明 |
|------------|---------------|------|
| `NoUserMessageError` | 400 | ユーザーメッセージなし |
| `ValueError` (invalid_model_name) | 400 | 無効なモデル名 |
| `ThreadNotFoundError` | 404 | スレッド未検出 |
| `MaxIterationsExceeded` | 500 | 最大イテレーション到達 |
| LLM設定なし | 501 | LLM未設定 |
| `Exception` (LLMエラー) | 502 | LLM APIエラー |
| `asyncio.TimeoutError` | 504 | タイムアウト |

## テスト戦略

### Unit Tests
- UseCase層: ドメインロジックのテスト
- Infrastructure層: DB操作のテスト
- Domain Tools: Repository をモックしてビジネスロジックをテスト

### Integration Tests
- エンドポイントの動作確認
- エラーレスポンスの検証

### Mock境界
- `LLMClient`: LLM API呼び出し
- `ToolRegistry`: ツール実行
- `ThreadRepository`: データアクセス
- `SpotifyRepository`: Spotify データアクセス

## 開発ガイド

### 新機能追加の順序

1. **Domain層**: エンティティとツールの抽象定義を追加
2. **Infrastructure層**: Repository 実装、外部システム統合
3. **Domain Tools**: ビジネスロジック（バリデーション）を実装
4. **UseCase層**: ツール登録とオーケストレーション
5. **API層**: 薄いハンドラーでリクエスト/レスポンス処理
6. **テスト**: Integration testで全体の動作を検証

### 新規ツール追加の例

```python
# 1. Repository を作成 (infrastructure/repositories/)
class NewDataRepository:
    def get_data(self, params): ...

# 2. Tool を作成 (domain/tools/)
class GetDataTool(ToolBase):
    def __init__(self, repository: NewDataRepository):
        self.repository = repository

    def execute(self, **params):
        # バリデーション
        validated_params = validate(params)
        # Repository に委譲
        return self.repository.get_data(validated_params)

# 3. UseCase で登録 (usecases/)
repository = NewDataRepository(config)
tool_registry.register(GetDataTool(repository))
```

### 今後の拡張方針

- **認証**: JWT/OAuth導入時は `api/auth.py` に分離
- **新規データソース**: `infrastructure/repositories/` に Repository 追加
- **新規ツール**: `domain/tools/` にビジネスロジック実装
- **複雑なドメインロジック**: `domain/services/` に追加
