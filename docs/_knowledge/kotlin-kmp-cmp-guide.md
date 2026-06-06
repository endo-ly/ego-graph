# Kotlin / KMP / CMP 開発ガイド

このドキュメントは、EgoGraph フロントエンドで採用している Kotlin Multiplatform (KMP) と Compose Multiplatform (CMP) に関する知識をまとめたものです。

---

## 1. Kotlin Multiplatform (KMP) とは

**KMP** は、1つのコードベースで複数のプラットフォーム（Android, iOS, Web, Desktop）に対応できる仕組みです。

### 基本構成

```
commonMain (共通コード)
    ├── UI (Compose)
    ├── ビジネスロジック
    ├── データモデル
    └── Repository
         ├── androidMain (Android固有処理)
         └── iosMain (iOS固有処理)
```

### ソースセットの役割

| ソースセット   | 役割                                                            |
| :------------- | :-------------------------------------------------------------- |
| `commonMain/`  | 全プラットフォーム共通のコード（UI, ロジック, DTO, Repository） |
| `androidMain/` | Android固有の処理                                               |
| `commonTest/`  | 共通テスト                                                      |

### プラットフォーム固有処理の実装方法

KMPでは `expect` / `actual` キーワードを使って、共通コードからプラットフォーム固有の実装を呼び出します。

```kotlin
// commonMain
expect fun getPlatformName(): String

// androidMain
actual fun getPlatformName(): String = "Android"

// iosMain
actual fun getPlatformName(): String = "iOS"
```

---

## 2. Compose Multiplatform (CMP) とは

**CMP** は、宣言的UIフレームワーク「Jetpack Compose」をマルチプラットフォームに展開したものです。

### 宣言的UIの基本

状態（State）に基づいてUIを自動的に再構築する仕組みです。

```kotlin
@Composable
fun ChatScreen(messages: List<Message>) {
    LazyColumn {
        items(messages) { message ->
            MessageItem(message)
        }
    }
}
```

---

## 3. アーキテクチャ

### アプリ起動の順序

```
① EgoGraphApplication.onCreate()
   └─ startKoin { modules(appModule, androidModule) }
      └─ DIコンテナ初期化

② MainActivity.onCreate()
   └─ setContent { MaterialTheme { SidebarScreen().Content() } }

③ SidebarScreen.Content()
   └─ 各画面へのナビゲーション（Voyager）

④ 各画面のContent()
   ├─ ChatScreen.Content() → ChatScreenModel（ViewModel）
   └─ ThreadList
```

### レイヤーの呼び出し順序（ユーザー操作時）

```
ユーザー操作（ボタンクリックなど）
    │
    ▼
UI Layer (Compose)
  Button onClick → screenModel.sendMessage(text)
    │
    ▼ 関数呼び出し
ViewModel (ChatScreenModel)
  fun sendMessage(content: String)
    → Repository呼び出し（非同期処理）
    → State更新
    │
    ▼
Repository (Data Layer)
  ChatRepository.sendMessage()
    → Ktor HttpClientでAPIリクエスト
    → Flow<Result<StreamChunk>>でストリーミング
    │
    ▼ Result
ViewModel (State更新)
  _state.update { it.copy(messages = newMessages) }
    → Stateが更新され、UIが再Composeされる
```

### MVVMアーキテクチャ

**MVVM** は **Model-View-ViewModel** の略で、UIの状態管理とビジネスロジックを分離するアーキテクチャパターンです。

#### 3つの要素

| 要素        | 役割                                           | 実装                   |
| :---------- | :--------------------------------------------- | :--------------------- |
| **Model**   | データアクセス、ビジネスロジック               | Repository、DTO        |
| **View**    | UI描画、ユーザー操作の受付                     | `@Composable`関数     |
| **ViewModel** | 状態管理、ViewとModelの仲介                   | `ChatScreenModel`      |

#### 追加要素

| 要素    | 役割                           | 実装             |
| :------ | :----------------------------- | :--------------- |
| **State** | 不変の状態データ               | `ChatState`      |
| **Effect** | One-shotイベント（通知）       | `ChatEffect`     |

#### データフロー

```
ユーザー操作
    │
    ▼
UI  (Compose) ──→ ViewModel ──→ Repository/API
    ◀──────────────◀── Result     │
         ▲                      │
         └──────────────────────┘
              State / Effect
```

### Repositoryパターン

**バックエンドのRepositoryと基本的に同じ概念**です。データアクセスの抽象化レイヤーとして機能します。

| 役割         | バックエンド（DuckDB） | フロントエンド（KMP）    |
| :----------- | :--------------------- | :----------------------- |
| データソース | DBファイル             | HTTP API                 |
| 役割         | データアクセスの抽象化 | API通信の抽象化          |
| 利点         | 実装詳細を隠蔽         | テスト容易、差し替え可能 |

---

## 4. 技術スタック

| カテゴリ           | ライブラリ              | 役割                   |
| :----------------- | :--------------------- | :--------------------- |
| **UI**             | Compose Multiplatform   | 宣言的UIフレームワーク |
| **ナビゲーション** | Voyager                 | 画面遷移、ScreenModel   |
| **状態管理**       | StateFlow + Channel     | MVVMアーキテクチャ     |
| **DI**             | Koin                    | 依存性注入コンテナ     |
| **HTTP**           | Ktor Client             | HTTPクライアント       |
| **非同期**         | Kotlinx Coroutines      | 非同期処理             |
| **シリアライズ**   | Kotlinx Serialization   | JSONシリアライズ       |
| **ロギング**       | Kermit                  | ロギング               |

---

## 5. 開発体験向上ツール

### Lint / 静的解析

| ツール     | 役割                                                           |
| :--------- | :------------------------------------------------------------- |
| **Detekt** | コードの「問題」を見つける（バグの可能性、複雑すぎる関数など） |
| **Ktlint** | コードの「見た目」を整える（インデント、スペース、改行位置）   |

**違い**: Detektは「問題」を見つける医者、Ktlintは「見た目」を整える理容師

### テストフレームワーク

| ツール              | 役割                                                     |
| :------------------ | :------------------------------------------------------- |
| **kotlin-test**     | 標準テストフレームワーク（基本アサーション）             |
| **Kotest**          | 記述的なテストDSL（`shouldBe`, `context`, `test`）       |
| **Turbine**         | Flowのテストを簡単に（`awaitItem()`, `awaitComplete()`） |
| **MockK**           | モックライブラリ（Repositoryテストで必須）               |
| **Ktor MockEngine** | HTTPモック（既にKtor導入済み）                           |

### 推奨ツールセット

```
必須
├─ Detekt      静的解析
├─ Ktlint      フォーマット
└─ Kotest      テストDSL

追加推奨
├─ MockK       モックライブラリ
└─ Ktor MockEngine  HTTPモック

既に導入済み
└─ Turbine     Flowテスト
```

---

## 6. プロジェクト構成

```
frontend/
├── androidApp/           # Androidアプリモジュール
│   ├── src/main/kotlin/dev/egograph/
│   │   ├── app/MainActivity.kt
│   │   └── android/EgoGraphApplication.kt
│   └── build.gradle.kts
│
├── shared/               # KMP共有モジュール
│   ├── src/
│   │   ├── commonMain/  # 共通コード
│   │   │   ├── kotlin/dev/egograph/shared/
│   │   │   │   ├── features/     # 機能モジュール（MVVM）
│   │   │   │   │   └── chat/     # チャット機能
│   │   │   │   │       ├── ChatScreen.kt       # View
│   │   │   │   │       ├── ChatScreenModel.kt  # ViewModel
│   │   │   │   │       ├── ChatState.kt        # State
│   │   │   │   │       └── ChatEffect.kt       # Effect
│   │   │   │   ├── core/         # コア機能
│   │   │   │   │   ├── domain/     # ドメインモデル
│   │   │   │   │   ├── data/       # Repository実装
│   │   │   │   │   ├── network/    # Ktor HTTPクライアント
│   │   │   │   │   └── platform/   # プラットフォーム固有処理
│   │   │   │   └── di/           # Koin DI
│   │   │   └── ...
│   │   ├── androidMain/  # Android固有処理
│   │   └── commonTest/   # 共通テスト
│   └── build.gradle.kts
│
├── gradle/
│   └── libs.versions.toml  # バージョン管理
└── build.gradle.kts
```

---

## 7. 参考リンク

- [Kotlin Multiplatform](https://kotlinlang.org/docs/multiplatform.html)
- [Compose Multiplatform](https://compose-multiplatform-org.github.io/compose-multiplatform/)
- [Voyager](https://voyager.adriel.cafe/) - ナビゲーション & ScreenModel
- [Koin](https://insert-koin.io/) - DIコンテナ
- [Ktor](https://ktor.io/) - HTTPクライアント
- [Detekt](https://detekt.dev/) - 静的解析
- [Ktlint](https://pinterest.github.io/ktlint/) - フォーマット
- [Kotest](https://kotest.io/) - テストDSL

### MVVM関連

詳しいMVVMアーキテクチャについては、以下のドキュメントを参照してください：
- [MVVMアーキテクチャガイド（React開発者向け）](./mvvm-architecture-guide.md)
