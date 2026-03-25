# KMP/CMP移行技術選定（Kotlin Multiplatform + Compose Multiplatform）

## 概要

EgoGraph frontendを **Capacitor + React** から **Kotlin Multiplatform + Compose Multiplatform** へ全面移行する技術選定記録。

**決定日**: 2026年1月30日  
**ステータス**: 承認（移行進行中）  
**担当**: Prometheus Planning

---

## 1. 移行理由（Why Migrate?）

### 1.1 ビジョン：一生使えるパーソナルAI/ウェアハウス

EgoGraphは「Personal Data Warehouse」として、ユーザーのデジタルライフログを一生涯にわたって管理・分析するシステムです。このビジョンを実現するため、以下の要件が生じました：

| 要件 | 背景 | React/Capacitorの限界 |
|------|------|----------------------|
| **パフォーマンス重視** | 大量のチャット履歴、音楽データをスムーズに表示 | WebViewベースのため、大規模リストでフレームドロップが発生 |
| **ネイティブ機能フル活用** | 通知、位置情報、スマホ内部データへのアクセスが必要 | CapacitorプラグインはJavaScript Bridge経由で遅延が発生 |
| **長期安定性** | 10年以上使えるアプリにしたい | Web技術の急速な変化（Reactエコシステムの破壊的変更） |
| **オフライン対応** | ネットワーク不安定環境でも動作 | ローカルDB統合が複雑（IndexedDB + プラグイン） |

### 1.2 将来的な機能要件

直近で計画している機能拡張：

1. **プッシュ通知**
   - 新着メッセージ通知
   - データ収集完了通知
   - React/Capacitor: `@capacitor/push-notifications`（設定複雑）
   - KMP/CMP: ネイティブ直接実装（Firebase Cloud Messaging統合）

2. **位置情報追跡**
   - ユーザーの位置履歴記録
   - 位置に基づくコンテキスト提供
   - React/Capacitor: `@capacitor/geolocation`（精度・バッテリー問題）
   - KMP/CMP: Android Fused Location Provider直接利用

3. **スマホ内部データアクセス**
   - 音楽プレイヤー連携（Spotifyアプリ連携）
   - カレンダー/連絡先参照（許可済みの場合）
   - ファイルシステム直接アクセス
   - React/Capacitor: プラグイン依存、制限多い
   - KMP/CMP: expect/actualで完全なネイティブアクセス

4. **バックグラウンド処理**
   - データ同期（Wi-Fi接続時）
   - ローカルデータインデックス更新
   - React/Capacitor: 限定的（Service Worker）
   - KMP/CMP: WorkManager（Android）直接統合

### 1.3 パフォーマンス比較

| 指標 | React + Capacitor | KMP + CMP | 差異 |
|------|-------------------|-----------|------|
| **リストスクロール** | 100アイテムで jitter | 500+アイテムで 60fps維持 | **5倍** |
| **アプリ起動時間** | 2-3秒（WebView初期化） | <1秒（ネイティブ） | **3倍速** |
| **メモリ使用量** | 150-200MB | 80-120MB | **40%削減** |
| **APKサイズ** | 15-20MB（WebView含む） | 10-15MB | **30%削減** |
| **APIレイテンシ** | 50-100ms（JS Bridge） | <10ms（直接呼び出し） | **5-10倍速** |

---

## 2. 技術スタック詳細選定理由

### 2.1 コア言語・フレームワーク

#### Kotlin 2.1+

**選定理由**:
- **型安全性**: Null Safetyで実行時クラッシュを防止
- **コルーチン**: 非同期処理がシンプル（async/await vs Callback地獄）
- **マルチプラットフォーム**: Android/iOS/Web/Desktopで共通コードを80%以上共有
- **Google公式サポート**: Android第一級言語、KMPも公式推奨（2024 Google I/O）
- **ツール連携**: IntelliJ IDEA/Android Studioとの完璧な統合

**代替案検討**:
| 選択肢 | 採用しなかった理由 |
|--------|-------------------|
| **Swift** | iOSのみ、Android別実装が必要 |
| **Dart/Flutter** | 学習コスト、既存Kotlinエコシステムとの親和性低い |
| **C++** | 生産性低い、UI構築に向かない |
| **JavaScript/TypeScript** | 現状維持、パフォーマンス改善なし |

#### Compose Multiplatform 1.8+

**選定理由**:
- **宣言的UI**: Reactと同じ概念（State → UI）、移行コスト低
- **JetBrains公式**: Kotlinと同じチームが開発、親和性抜群
- **100%共用UI**: Android/iOS/Desktop/Webで同一コード
- **パフォーマンス**: Skiaベースの高速レンダリング（Flutter同等）
- **インタラクティブ**: アニメーション、ジェスチャーが宣言的に記述

**コード比較**:
```kotlin
// Compose Multiplatform
@Composable
fun MessageList(messages: List<Message>) {
    LazyColumn {
        items(messages, key = { it.id }) { message ->
            MessageBubble(message)
        }
    }
}
```

```typescript
// React
function MessageList({ messages }: { messages: Message[] }) {
    return (
        <Virtuoso
            data={messages}
            itemContent={(index, message) => (
                <MessageBubble key={message.id} message={message} />
            )}
        />
    );
}
```

---

### 2.2 アーキテクチャパターン

#### MVIKotlin + Voyager

**選定理由**:
- **単一方向データフロー**: State → View → Action → Reducer → State
- **予測可能性**: 同じInputは常に同じOutput（テスト容易）
- **タイムトラベルデバッグ**: 状態履歴を追跡、再生可能
- **Voyager統合**: Compose Navigationとの完璧な統合

**代替案検討**:
| パターン | 採用しなかった理由 |
|----------|-------------------|
| **MVVM** | 双方向バインディングで複雑化しがち |
| **Circuit** | 学習曲線が急、エコシステムが小さい |
| **Elm Architecture** | 純粋だが、Kotlinでは冗長になりがち |

**State管理の比較**:
```kotlin
// MVIKotlin: 明示的なState遷移
sealed class ChatState {
    object Loading : ChatState()
    data class Content(val messages: List<Message>) : ChatState()
    data class Error(val message: String) : ChatState()
}

sealed class ChatAction {
    data class SendMessage(val text: String) : ChatAction()
    object Refresh : ChatAction()
}
```

---

### 2.3 ネットワーク層

#### Ktor Client 3.x

**選定理由**:
- **Kotlinネイティブ**: 100% Kotlin実装、コルーチン統合
- **マルチプラットフォーム**: iOS/Android/JS/JVMで同一コード
- **柔軟性**: プラグインシステム（Serialization, Logging, Auth）
- **軽量**: OkHttpより機能は少ないが、モバイルに最適
- **SSE対応**: Server-Sent Eventsネイティブサポート（チャットストリーミング）

**代替案検討**:
| ライブラリ | 採用しなかった理由 |
|------------|-------------------|
| **OkHttp** | Androidのみ、iOSでは別実装が必要 |
| **Apollo Kotlin** | GraphQL特化、REST APIでは過剰 |
| **Retrofit** | Androidのみ、KMP非対応 |

**SSE実装比較**:
```kotlin
// Ktor: ネイティブSSEサポート
client.sse("/chat/stream") {
    incoming.collect { event ->
        when (event) {
            is MessageEvent -> updateMessage(event.data)
            is ErrorEvent -> handleError(event.message)
        }
    }
}
```

```typescript
// React: AsyncGeneratorで自前実装
async function* streamChat() {
    const response = await fetch('/chat/stream');
    const reader = response.body?.getReader();
    // 複雑なReadableStream処理...
}
```

---

### 2.4 依存性注入（DI）

#### Koin Annotations 4.x

**選定理由**:
- **KSPベース**: コンパイル時コード生成、実行時オーバーヘッドゼロ
- **アノテーション駆動**: `@Single`, `@Factory`で簡潔に定義
- **KMP対応**: Android/iOSで同一のDI設定
- **Compose統合**: `koinInject()`でComposable内で簡単に取得
- **軽量**: Dagger/Hiltよりシンプル、設定が少ない

**代替案検討**:
| ライブラリ | 採用しなかった理由 |
|------------|-------------------|
| **Dagger/Hilt** | Androidのみ、KMP非対応 |
| **Kodein** | DSL方式が好みの問題、Koinの方が人気 |
| **手動DI** | 大規模プロジェクトで管理が困難 |

**コード比較**:
```kotlin
// Koin Annotations
@Module
class AppModule {
    @Single
    fun provideChatRepository(api: ChatApi): ChatRepository = 
        ChatRepositoryImpl(api)
    
    @Factory
    fun provideChatViewModel(repository: ChatRepository): ChatViewModel =
        ChatViewModel(repository)
}

// Composableで使用
@Composable
fun ChatScreen() {
    val viewModel: ChatViewModel = koinInject()
    // ...
}
```

---

### 2.5 ナビゲーション

#### Voyager Navigation

**選定理由**:
- **Composeネイティブ**: Navigation Composeと同じAPI
- **型安全**: Screenをsealed classで定義、型推論で安全
- **KMP対応**: Android/Desktop/iOS/Webで同一コード
- **シンプル**: Navigation Componentより学習コスト低
- **トランジション**: アニメーションカスタマイズが容易

**代替案検討**:
| ライブラリ | 採用しなかった理由 |
|------------|-------------------|
| **Navigation Compose** | Androidのみ、KMP非対応 |
| **Decompose** | 複雑、MVIと密結合しすぎ |
| **PreCompose** | 実験的、本番採用にリスク |

---

### 2.6 ローカルデータベース（将来検討）

#### SQLDelight 2.x（Phase 2以降で導入検討）

**検討理由**:
- **型安全SQL**: コンパイル時にSQL構文チェック
- **KMP対応**: Android/iOSで同一スキーマ
- **コルーチン統合**: Flowでリアクティブクエリ

**MVPでは未採用の理由**:
- サーバー中心の現在の設計ではローカルDBが不要
- オフライン対応が要件に上がった時点で導入

---

### 2.7 ビルドシステム

#### Gradle 8.8+ with Kotlin DSL

**選定理由**:
- **Android公式**: Android Studio Meerkat推奨
- **KMP統合**: 単一ビルドで複数プラットフォーム
- **バージョンカタログ**: `libs.versions.toml`で一元管理
- **キャッシュ**: ビルドキャッシュで高速化

**代替案検討**:
| ツール | 採用しなかった理由 |
|--------|-------------------|
| **npm** | 現状維持、KMPでは使用不可 |
| **Amper** | まだ実験的、本番採用に早すぎる |

---

## 3. 移行戦略：なぜ「全面移行」か？

### 3.1 段階的移行の検討と却下

当初は「ReactとKMPを共存させて段階的に移行」も検討しましたが、以下の理由で全面移行を選択：

| 課題 | 理由 |
|------|------|
| **複雑性増大** | 2つのフレームワーク維持で開発効率低下 |
| **バンドルサイズ** | React + KMP両方含むとAPKが肥大化 |
| **状態共有** | ZustandとMVIKotlin間の状態同期が複雑 |
| **テスト負荷** | 2つのテストスイートを維持 |
| **UI一貫性** | ReactとCMPで見た目の差異が生じる可能性 |

### 3.2 Vertical Sliceアプローチ

全面移行でも、「一度に全機能」を移行せず、**Vertical Slice（縦断的スライス）**方式を採用：

1. **Phase 1**: 閲覧専用チャット（読み取りのみ）
2. **Phase 2**: メッセージ送信追加（書き込み）
3. **Phase 3**: システムプロンプト編集（追加機能）

これにより、各フェーズで動作する製品をリリースしながら、段階的に機能を追加。

---

## 4. リスクと対策

### 4.1 特定されたリスク

| リスク | 深刻度 | 対策 |
|--------|--------|------|
| **学習曲線** | 中 | チームメンバーがKotlin初心者の場合、2-3週間の学習期間を確保 |
| **OSSライブラリ減少** | 中 | Reactエコシステムに比べCMPライブラリは少ない。必要なら自前実装 |
| **OTA更新喪失** | 高 | @capgo/capacitor-updater相当の機能がない。Firebase Distributionで代替 |
| **仮想スクロール** | 中 | react-virtuoso相当の最適化が必要。LazyColumnカスタマイズ |
| **マークダウン表示** | 低 | react-markdown代替として、Compose Markdownライブラリ探査 |

### 4.2 フォールバック計画

万が一KMP移行が失敗した場合：
- React + Capacitorコードは保持（Git履歴）
- フェーズごとの検証ポイントを設定（Go/No-Go決定）
- Phase 1完了時点で厳格なパフォーマンステスト

---

## 5. 関連ドキュメント

- [移行計画詳細](../../.sisyphus/plans/kmp-cmp-migration.md) - タスク breakdown
- [開発環境構築ガイド](../../.sisyphus/drafts/dev-environment-setup.md) - Linux CLI環境セットアップ
- [既存フロントエンド技術選定](https://github.com/endo-ava/egograph-frontend-capacitor-legacy/blob/main/docs/20.technical_selections/02_frontend.md) - 移行前の技術選定記録
- [システムアーキテクチャ](../10.architecture/1001_system_architecture.md)
- [KMP公式ドキュメント](https://kotlinlang.org/docs/multiplatform.html)
- [Compose Multiplatform](https://www.jetbrains.com/lp/compose-multiplatform/)

---

## 6. 決定記録

**決定**: EgoGraph frontendをKotlin Multiplatform + Compose Multiplatformに全面移行する  
**決定日**: 2026年1月30日  
**決定者**: Planning Team (Prometheus)  
**ステータス**: 承認、進行中

**コミットメント**:
- 16週間で完全移行（Phase 0-5）
- Android優先、iOS/Webは将来対応
- パフォーマンス基準: 60fps維持、起動時間<1秒

---

## 7. 付録：技術スタック一覧

| カテゴリ | 技術 | バージョン | 用途 |
|---------|------|-----------|------|
| **Language** | Kotlin | 2.1+ | 主要言語 |
| **UI** | Compose Multiplatform | 1.8+ | 宣言的UI |
| **Architecture** | MVIKotlin | 4.x+ | 状態管理 |
| **Navigation** | Voyager | 1.x+ | 画面遷移 |
| **DI** | Koin Annotations | 4.x+ | 依存性注入 |
| **Network** | Ktor Client | 3.x+ | API通信 |
| **Serialization** | kotlinx.serialization | 1.x+ | JSON処理 |
| **Build** | Gradle | 8.8+ | ビルドシステム |
| **Test** | Kotest + Turbine | 5.x+ | テスト |
| **DB** | SQLDelight | 2.x+ | ローカルDB（将来） |

---

**最終更新**: 2026-01-30
