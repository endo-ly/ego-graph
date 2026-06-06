# フロントエンドアーキテクチャ

## 概要

EgoGraphプロジェクトのフロントエンド実装に関する設計書。Kotlin Multiplatform + Compose Multiplatform で実装されたモバイルアプリのアーキテクチャを記述する。

**対象範囲:**
- Kotlin Multiplatform Mobile (KMP) + Compose Multiplatform
- `frontend/shared/src/commonMain/kotlin/dev/egograph/shared/` 以下の共通コード
- Android プラットフォーム固有の実装は対象外

**主要機能:**

| 機能 | 説明 |
|------|------|
| Chat | LLMとのチャット、スレッド管理、モデル選択 |
| Terminal | Gateway経由のWebSocketターミナル接続 |
| Settings | API設定、テーマ設定 |
| SystemPrompt | ユーザー定義システムプロンプトの編集 |
| Sidebar | スレッド履歴、ナビゲーション |

---

## 技術スタック

| カテゴリ | 技術 | バージョン |
|----------|------|-----------|
| 言語 | Kotlin | 2.2.21 |
| UI | Compose Multiplatform | 1.9.0 |
| ナビゲーション | Voyager | 1.1.0-beta03 |
| DI | Koin | 4.0.0 |
| HTTP | Ktor | 3.3.3 |
| ロギング | Kermit | - |
| 非同期 | Kotlin Coroutines + Flow | - |

---

## 全体アーキテクチャ図

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Presentation Layer                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Screen (Compose UI)                                      │  │
│  │  - ChatScreen, TerminalScreen, SettingsScreen, etc.      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │ collectAsState()                  │
│                              ▼                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ScreenModel (Voyager ScreenModel)                        │  │
│  │  - StateFlow<State>                                       │  │
│  │  - Channel<Effect>                                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │ Repository
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Domain Layer                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Repository Interfaces                                    │  │
│  │  - ChatRepository, ThreadRepository, etc.                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Domain Models                                            │  │
│  │  - Thread, ThreadMessage, LLMModel, etc.                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  RepositoryImpl                                           │  │
│  │  - RepositoryClient (HTTP)                                │  │
│  │  - DiskCache / InMemoryCache                              │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## MVVMパターン

本プロジェクトでは `Screen` (View) → `ScreenModel` (ViewModel) → `Repository` (Model) のレイヤー構成を採用する。

### レイヤー責務

| レイヤー | 責務 | 技術要素 |
|----------|------|----------|
| Screen | UI描画、ユーザー操作の受付 | @Composable 関数 |
| ScreenModel | 状態管理、ビジネスロジック、リポジトリ呼び出し | StateFlow, Channel, coroutineScope |
| Repository | API通信、キャッシュ管理 | Ktor HttpClient, Cache |

### データフロー

```text
User Input → Screen → ScreenModel.func() → Repository → API
                ↓                                  ↓
        collectAsState()                    Result<T>
                ↓                                  ↓
            State ←───────────────────────── State.update()
```

---

## レイヤー構成

```text
frontend/shared/src/commonMain/kotlin/dev/egograph/shared/
├── core/
│   ├── domain/
│   │   ├── model/          # ドメインモデル
│   │   └── repository/     # Repositoryインターフェース
│   ├── data/
│   │   └── repository/     # Repository実装
│   ├── network/            # HTTPクライアント
│   ├── platform/           # プラットフォーム依存処理
│   ├── settings/           # 設定管理
│   └── ui/
│       ├── common/         # 共通UIコンポーネント
│       └── theme/          # テーマ設定
├── features/
│   ├── chat/               # チャット機能
│   ├── terminal/           # ターミナル機能
│   ├── settings/           # 設定機能
│   ├── systemprompt/       # システムプロンプト機能
│   ├── sidebar/            # サイドバー機能
│   └── navigation/         # ナビゲーション
└── di/                     # 依存性注入 (Koin)
```

---

## 状態管理パターン

### State/Effect パターン

本プロジェクトでは **StateFlow + Channel** の組み合わせで状態管理を行う。

#### State（継続的なUI状態）

- **不変**のdata classで定義
- `StateFlow<State>` で公開
- UIは `collectAsState()` で観測
- 更新は `_state.update { it.copy(...) }` で行う

```kotlin
// 定義例
data class ChatState(
    val threadList: ThreadListState = ThreadListState(),
    val messageList: MessageListState = MessageListState(),
    val composer: ComposerState = ComposerState(),
)

// 更新例
_state.update { state -> 
    state.copy(threadList = state.threadList.copy(isLoading = true))
}
```

#### Effect（One-shotイベント）

- **一度だけ消費される**イベント（Snackbar表示、画面遷移など）
- `Channel<Effect>` で公開
- UIは `LaunchedEffect` で収集

```kotlin
// 定義例
sealed class ChatEffect {
    data class ShowMessage(val message: String) : ChatEffect()
}

// 消費例
LaunchedEffect(Unit) {
    screenModel.effect.collect { effect ->
        when (effect) {
            is ChatEffect.ShowMessage -> snackbarHostState.showSnackbar(effect.message)
        }
    }
}
```

### なぜこのパターンか

- **StateFlow**: 初期値を持ち、複数のObserverに現在値を配信できる
- **Channel**: One-shotイベントに最適（Snackbarを2回表示させない等）
- **Voyager ScreenModel**: 画面ライフサイクルに紐づくViewModelとして機能

---

## ナビゲーション

### MainView（画面切り替え）

SidebarScreen内で `MainView` 列挙型によって画面を管理：

| 値 | 画面 |
|----|------|
| Chat | チャット |
| Terminal | セッション一覧 |
| TerminalSession | ターミナル（セッション接続済） |
| Settings | 設定 |
| SystemPrompt | システムプロンプト編集 |
| GatewaySettings | Gateway接続設定 |

### スワイプナビゲーション

Chat ↔ Terminal/TerminalSession 間は**左右スワイプ**で遷移可能：

- Chat画面: ←右スワイプ → Drawer開く、←左スワイプ → Terminal
- Terminal/TerminalSession: ←右スワイプ → Chat

その他の遷移はDrawer内のボタンまたはジェスチャーなし。

---

## 画面一覧

| 画面ID | 画面名 | Screenクラス | ScreenModel | 説明 |
|--------|--------|--------------|-------------|------|
| Chat | チャット | ChatScreen | ChatScreenModel | LLMチャット、スレッド管理 |
| Terminal | ターミナル一覧 | AgentListScreen | AgentListScreenModel | セッション一覧 |
| TerminalSession | ターミナル | TerminalScreen | - | WebSocketターミナル |
| Settings | 設定 | SettingsScreen | - | API設定、テーマ |
| SystemPrompt | システムプロンプト | SystemPromptEditorScreen | - | プロンプト編集 |
| GatewaySettings | Gateway設定 | GatewaySettingsScreen | - | Gateway接続設定 |
| Sidebar | サイドバー | SidebarScreen | - | ナビゲーション、履歴 |
