# MVVMアーキテクチャガイド（React開発者向け）

このドキュメントは、EgoGraph フロントエンドで採用している MVVM (Model-View-ViewModel) アーキテクチャについて、React 開発者の視点から解説したものです。

---

## 1. MVVM とは

**MVVM** は、UI アプリケーションを3つのレイヤーに分割する設計パターンです。

```
┌─────────────────────────────────────────────────────────────────┐
│                        MVVM アーキテクチャ                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │     View        │───▶│  ViewModel      │───▶│   Model     │  │
│  │   (UI層)       │    │  (ロジック層)    │    │  (データ層)  │  │
│  │                 │◀───│                 │◀───│             │  │
│  │  • UI描画       │    │  • 状態管理     │    │  • データ   │  │
│  │  • ユーザー操作 │    │  • ビジネスロジック│  │  • API通信  │  │
│  └─────────────────┘    └─────────────────┘    └─────────────┘  │
│         │                      │                                  │
│         │ observe             │ update                           │
│         ▼                      ▼                                  │
│    ┌─────────┐           ┌─────────┐                             │
│    │  State  │           │ Effect  │                             │
│    │ (状態)   │           │ (イベント)│                            │
│    └─────────┘           └─────────┘                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. React との用語対応

| 概念 | React | Kotlin (Compose Multiplatform) |
|------|-------|-------------------------------|
| **コンポーネント** | コンポーネント関数 | `@Composable` 関数 |
| **状態** | `useState` | `StateFlow` / `MutableStateFlow` |
| **副作用** | `useEffect` | `LaunchedEffect` |
| ** Props** | 関数引数 | `@Composable` 関数引数 |
| **イベントハンドラ** | `onClick={...}` | `onClick = { ... }` |
| **状態ホイスティング** | 親コンポーネントで管理 | ViewModelで管理 |
| **コンテキスト** | `useContext` | Koin (DIコンテナ) |

---

## 3. 各レイヤーの詳細

### 3.1 Model（データ層）

**担当**: データの永続化、API通信、ビジネスロジック

```kotlin
// Repositoryインターフェース
interface ThreadRepository {
    fun getThreads(limit: Int, offset: Int): Flow<Result<ThreadListResponse>>
    fun getThread(threadId: String): Flow<Result<Thread>>
}
```

**React での相当概念**:
- Redux の `thunk` / `async thunks`
- React Query (`useQuery`)
- SWR

**主な違い**:
- Kotlin は `Flow` (ストリーム) でデータを扱う
- `Result<T>` で成功/失敗を表現（`try-catch` 不要）

---

### 3.2 ViewModel（ロジック層）

**担当**: 状態管理、ビジネスロジック、Repositoryとの連携

```kotlin
class ChatScreenModel(
    private val threadRepository: ThreadRepository,
    private val messageRepository: MessageRepository,
    private val chatRepository: ChatRepository,
) : ScreenModel {
    // 状態: StateFlowでUIに公開
    private val _state = MutableStateFlow(ChatState())
    val state: StateFlow<ChatState> = _state.asStateFlow()

    // One-shotイベント: ChannelでUIに公開
    private val _effect = Channel<ChatEffect>()
    val effect: Flow<ChatEffect> = _effect.receiveAsFlow()

    // ユーザーアクション
    fun sendMessage(content: String) {
        screenModelScope.launch {
            // ビジネスロジック
            // ...
        }
    }
}
```

**React での相当概念**:
- Redux の `reducer` + `actions`
- Custom Hooks (`useChat`, `useThreads`)
- `useState` + `useReducer`

**主な違い**:

| Kotlin | React | 説明 |
|--------|-------|------|
| `StateFlow` | `useState` | 常に最新の値を持つストリーム |
| `Channel` | イベントハンドラ | 消費するとなくなるOne-shotイベント |
| `screenModelScope` | コンポーネントスコープ | 画面生存期間中の Coroutine スコープ |

---

### 3.3 View（UI層）

**担当**: UI描画、ユーザー操作の受付

```kotlin
@Composable
fun ChatScreen() {
    // 1. ViewModelの取得（DI: Koin）
    val screenModel = koinScreenModel<ChatScreenModel>()

    // 2. 状態の購読
    val state by screenModel.state.collectAsState()

    // 3. Effectの処理
    LaunchedEffect(Unit) {
        screenModel.effect.collect { effect ->
            when (effect) {
                is ChatEffect.ShowMessage -> {
                    // Snackbar表示
                }
            }
        }
    }

    // 4. UI構築
    Scaffold(
        bottomBar = {
            ChatComposer(
                models = state.composer.models,
                onSendMessage = { text ->
                    screenModel.sendMessage(text)
                },
                isLoading = state.composer.isSending,
            )
        },
    ) { /* ... */ }
}
```

**React での相当概念**:
```tsx
function ChatScreen() {
    // 1. 状態の購読
    const { threads, messages, isSending } = useChatState();

    // 2. One-shotイベントの処理
    const { showSnackbar } = useSnackbar();
    useEffect(() => {
        if (error) {
            showSnackbar(error.message);
        }
    }, [error]);

    // 3. UI構築
    return (
        <div>
            <ChatComposer
                models={models}
                onSendMessage={(text) => sendMessage(text)}
                isLoading={isSending}
            />
        </div>
    );
}
```

---

## 4. State と Effect

### 4.1 State（状態）

**担当**: UIの状態を表現する不変データクラス

```kotlin
data class ChatState(
    val threadList: ThreadListState = ThreadListState(),
    val messageList: MessageListState = MessageListState(),
    val composer: ComposerState = ComposerState(),
) {
    // 派生プロパティ
    val hasSelectedThread: Boolean
        get() = threadList.selectedThread != null

    val isLoading: Boolean
        get() = threadList.isLoading || messageList.isLoading || composer.isSending
}
```

**React での相当概念**:
```tsx
// Redux Selector に相当
const hasSelectedThread = useSelector(state => state.threadList.selectedThread != null);
const isLoading = useSelector(state =>
    state.threadList.isLoading || state.messageList.isLoading || state.composer.isSending
);
```

---

### 4.2 Effect（One-shotイベント）

**担当**: 状態として保持しない単発のイベント

```kotlin
sealed class ChatEffect {
    data class ShowMessage(val message: String) : ChatEffect()
    data class NavigateToThread(val threadId: String) : ChatEffect()
}
```

**React での相当概念**:
```tsx
// 直接イベントハンドラを呼ぶか、Custom Hookから返す
const { showSnackbar, navigate } = useAppEffects();
```

**なぜ State と Effect を分けるのか**:

| 特徴 | State | Effect |
|------|-------|--------|
| **保持期間** | 常に保持 | 消費すると削除 |
| **再生成時** | 自動で復元 | 再実行されない |
| **主な用途** | UI表示 | ナビゲーション、Snackbar |
| **データ構造** | 不変データクラス | `sealed class` |
| **React相当** | `useState` / Redux State | イベントハンドラ / Callback |

---

## 5. 状態更新のパターン

### Kotlin (Immutable State)

```kotlin
// 不変データクラスのコピーで状態更新
private fun updateThreadList(transform: (ThreadListState) -> ThreadListState) {
    _state.update { state ->
        state.copy(threadList = transform(state.threadList))
    }
}

// 使用例
updateThreadList { current ->
    current.copy(
        threads = newThreads,
        selectedThread = newSelectedThread,
        isLoading = false,
    )
}
```

**React での相当概念**:
```tsx
// useState + スプレッド演算子
setThreadList(current => ({
    ...current,
    threads: newThreads,
    selectedThread: newSelectedThread,
    isLoading: false,
}));

// または Redux Reducer
case 'LOAD_THREADS_SUCCESS':
    return {
        ...state,
        threadList: {
            ...state.threadList,
            threads: action.payload.threads,
            isLoading: false,
        }
    };
```

---

## 6. 非同期処理のパターン

### Kotlin (Coroutines + Flow)

```kotlin
fun sendMessage(content: String) {
    screenModelScope.launch {
        // 1. ローカルで即座にUI更新
        updateMessageList {
            it.copy(messages = it.messages + userMessage)
        }

        // 2. API呼び出し（ストリーミング）
        chatRepository.sendMessage(request).collect { result ->
            result.onSuccess { chunk ->
                // 3. ストリーミングレスポンスでUI更新
                updateMessageList { current ->
                    current.copy(messages = current.messages.map { msg ->
                        if (msg.id == streamingMessageId) {
                            msg.copy(content = msg.content + chunk.delta)
                        } else msg
                    })
                }
            }
            result.onFailure { error ->
                // 4. エラー処理
                _effect.send(ChatEffect.ShowMessage(error.message))
            }
        }
    }
}
```

**React での相当概念**:
```tsx
function sendMessage(content) {
    // 1. 即時UI更新
    setMessages(prev => [...prev, userMessage]);

    // 2. API呼び出し（SSEストリーミング）
    fetchEventSource('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ messages }),
        onmessage(msg) {
            const chunk = JSON.parse(msg.data);
            // 3. ストリーミングレスポンスでUI更新
            setMessages(prev => prev.map(msg =>
                msg.id === streamingMessageId
                    ? { ...msg, content: msg.content + chunk.delta }
                    : msg
            ));
        },
        onerror(error) {
            // 4. エラー処理
            showSnackbar(error.message);
        }
    });
}
```

---

## 7. DI（依存性注入）

### Kotlin (Koin)

```kotlin
// モジュール定義
val chatModule = module {
    // Repositoryの実装を注入
    single { ThreadRepositoryImpl(get(), get(), get()) }
    single { MessageRepositoryImpl(get(), get(), get()) }
    single { ChatRepositoryImpl(get(), get(), get()) }

    // ViewModelをFactoryスコープで注入
    factory { ChatScreenModel(get(), get(), get(), get()) }
}

// 使用側
@Composable
fun ChatScreen() {
    val screenModel = koinScreenModel<ChatScreenModel>()
    // ...
}
```

**React での相当概念**:
```tsx
// React Context + Custom Hooks
const ChatContext = createContext();

function ChatProvider({ children }) {
    const threadRepository = useMemo(() => new ThreadRepositoryImpl(), []);
    const messageRepository = useMemo(() => new MessageRepositoryImpl(), []);
    const chatRepository = useMemo(() => new ChatRepositoryImpl(), []);

    const screenModel = useMemo(() =>
        new ChatScreenModel(threadRepository, messageRepository, chatRepository),
        [threadRepository, messageRepository, chatRepository]
    );

    return (
        <ChatContext.Provider value={screenModel}>
            {children}
        </ChatContext.Provider>
    );
}

// 使用側
function ChatScreen() {
    const screenModel = useContext(ChatContext);
    // ...
}
```

---

## 8. 実装例：チャット画面

### 完全なデータフロー

```
┌─────────────────────────────────────────────────────────────────┐
│                   ユーザー操作: メッセージ送信                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ View (ChatScreen)                                               │
│   ChatComposer(                                                 │
│       onSendMessage = { text -> screenModel.sendMessage(text) } │
│   )                                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ 呼び出し
┌─────────────────────────────────────────────────────────────────┐
│ ViewModel (ChatScreenModel)                                     │
│   fun sendMessage(content: String) {                            │
│       1. _state.value にローカルメッセージを追加                 │
│       2. chatRepository.sendMessage() を呼び出し                 │
│       3. Flow<Result<StreamChunk>> を収集                        │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ ストリーミング
┌─────────────────────────────────────────────────────────────────┐
│ Repository (ChatRepository)                                     │
│   suspend fun sendMessage(): Flow<Result<StreamChunk>>         │
│   • HTTP POST /v1/chat                                         │
│   • SSE (Server-Sent Events) のパース                            │
│   • JSONデコード                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Flow<Result<StreamChunk>>
┌─────────────────────────────────────────────────────────────────┐
│ ViewModel                                                       │
│   chatRepository.sendMessage(request).collect { result ->       │
│       result.onSuccess { chunk ->                               │
│           // State更新（UIに自動反映）                            │
│           _state.update { /* deltaチャンクを追加 */ }            │
│       }                                                          │
│       result.onFailure { error ->                               │
│           // Effect送信（Snackbarなど）                           │
│           _effect.send(ChatEffect.ShowMessage(error.message))    │
│       }                                                          │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ StateFlow / Channel
┌─────────────────────────────────────────────────────────────────┐
│ View (ChatScreen)                                               │
│   val state by screenModel.state.collectAsState()               │
│   → stateが変更されるたびに再コンポーズ                            │
│                                                                  │
│   LaunchedEffect {                                              │
│       screenModel.effect.collect { effect ->                    │
│           when (effect) {                                        │
│               ShowMessage(msg) -> showSnackbar(msg)              │
│           }                                                      │
│       }                                                          │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. ベストプラクティス

### 9.1 状態は不変に

```kotlin
// ✅ 良い例: copy() で新しい状態を作成
updateThreadList { current ->
    current.copy(threads = newThreads)
}

// ❌ 悪い例: 可変状態（やるべきでない）
currentThreads.addAll(newThreads)
_state.value = _state.value.copy(threads = currentThreads)
```

### 9.2 ロジックは ViewModel に

```kotlin
// ✅ 良い例: ViewModelでロジックを実装
@Composable
fun ChatScreen() {
    val screenModel = koinScreenModel<ChatScreenModel>()
    val state by screenModel.state.collectAsState()

    ChatComposer(
        onSendMessage = { text -> screenModel.sendMessage(text) }
    )
}

// ❌ 悪い例: Composableでロジックを実装（避ける）
@Composable
fun ChatScreen() {
    val (messages, setMessages) = useState(emptyList())

    ChatComposer(
        onSendMessage = { text ->
            // 複雑なロジックがComposableに入り込む
            val request = ChatRequest(...)
            api.send(request).then(response => {
                setMessages(prev => [...prev, response])
            })
        }
    )
}
```

### 9.3 Effect は One-shot イベントのみ

```kotlin
// ✅ 良い例: EffectはSnackbar、ナビゲーションなど
sealed class ChatEffect {
    data class ShowMessage(val message: String) : ChatEffect()
    data class NavigateToThread(val threadId: String) : ChatEffect()
}

// ❌ 悪い例: 状態をEffectに入れる（Stateに入れるべき）
sealed class ChatEffect {
    data class MessagesUpdated(val messages: List<Message>) : ChatEffect()
}
```

---

## 10. React 開発者のためのチートシート

| やりたいこと | React | Kotlin (Compose) |
|-------------|-------|------------------|
| **状態宣言** | `const [count, setCount] = useState(0)` | `val count by countState.collectAsState()` |
| **状態更新** | `setCount(prev => prev + 1)` | `_state.update { it.copy(count = it.count + 1) }` |
| **副作用** | `useEffect(() => { ... }, [deps])` | `LaunchedEffect(deps) { ... }` |
| **非同期処理** | `useEffect` + `fetch` / `axios` | `LaunchedEffect` + `Coroutine` |
| **ストリーミング** | `fetchEventSource` / EventSource | `Flow.collect { ... }` |
| **エラーハンドリング** | `try-catch` / `.catch()` | `Result<T>` / `.onFailure { ... }` |
| **条件レンダリング** | `{condition && <Component />}` | `if (condition) { Component() }` |
| **リストレンダリング** | `{items.map(item => <Item key={item.id} />)}` | `items.forEach { item -> Item(item) }` |
| **DI** | Context / Custom Hooks | Koin (`koinScreenModel<T>()`) |
| **ルーティング** | React Router | Voyager (`Screen`) |

---

## 11. サンプルコード比較

### チャット画面の実装比較

**React + TypeScript**:
```tsx
import { useState, useEffect } from 'react';

interface Message {
    id: string;
    content: string;
    role: 'user' | 'assistant';
}

function ChatScreen() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [input, setInput] = useState('');

    const sendMessage = async (content: string) => {
        // ユーザーメッセージを追加
        const userMessage: Message = {
            id: `user-${Date.now()}`,
            content,
            role: 'user'
        };
        setMessages(prev => [...prev, userMessage]);

        // ストリーミングでレスポンスを受信
        setIsLoading(true);
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: [...messages, userMessage] })
        });

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();

        let assistantContent = '';
        while (true) {
            const { done, value } = await reader!.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n').filter(line => line.startsWith('data: '));

            for (const line of lines) {
                const data = JSON.parse(line.slice(6));
                if (data.delta) {
                    assistantContent += data.delta;
                    setMessages(prev => {
                        const last = prev[prev.length - 1];
                        if (last?.role === 'assistant') {
                            return [...prev.slice(0, -1), { ...last, content: assistantContent }];
                        }
                        return [...prev, {
                            id: `assistant-${Date.now()}`,
                            content: assistantContent,
                            role: 'assistant'
                        }];
                    });
                }
            }
        }
        setIsLoading(false);
    };

    return (
        <div>
            {messages.map(msg => (
                <div key={msg.id}>
                    <span>{msg.role}: </span>
                    <span>{msg.content}</span>
                </div>
            ))}
            <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyPress={e => {
                    if (e.key === 'Enter' && input.trim()) {
                        sendMessage(input);
                        setInput('');
                    }
                }}
            />
        </div>
    );
}
```

**Kotlin + Compose Multiplatform**:
```kotlin
@Composable
fun ChatScreen() {
    val screenModel = koinScreenModel<ChatScreenModel>()
    val state by screenModel.state.collectAsState()

    Scaffold(
        bottomBar = {
            ChatComposer(
                onSendMessage = { text -> screenModel.sendMessage(text) },
                isLoading = state.composer.isSending
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            items(state.messageList.messages) { msg ->
                MessageBubble(
                    role = msg.role,
                    content = msg.content
                )
            }
        }
    }
}

// ViewModel (ロジックはここに実装される)
class ChatScreenModel(
    private val chatRepository: ChatRepository,
) : ScreenModel {
    private val _state = MutableStateFlow(ChatState())
    val state: StateFlow<ChatState> = _state.asStateFlow()

    fun sendMessage(content: String) {
        screenModelScope.launch {
            val userMessage = /* ... */
            updateMessageList {
                it.copy(messages = it.messages + userMessage)
            }

            chatRepository.sendMessage(request).collect { result ->
                result.onSuccess { chunk ->
                    // State更新（自動的にUIに反映）
                    updateMessageList { current ->
                        current.copy(messages = /* ... */)
                    }
                }
            }
        }
    }
}
```

---

## 12. 参考資料

### プロジェクト内の関連ファイル

| ファイル | 説明 |
|---------|------|
| `ChatScreen.kt` | View（UI）の実装 |
| `ChatScreenModel.kt` | ViewModel（ロジック）の実装 |
| `ChatState.kt` | Stateの定義 |
| `ChatEffect.kt` | Effectの定義 |
| `*Repository.kt` | Model（データ層）の実装 |

### 外部リソース

- [Jetpack Compose State](https://developer.android.com/jetpack/compose/state)
- [Kotlin Flow](https://kotlinlang.org/docs/flow.html)
- [Voyager](https://voyager.adriel.cafe/)
- [Koin](https://insert-koin.io/)
