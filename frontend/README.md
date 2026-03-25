# EgoGraph Android App (KMP)

**Kotlin Multiplatform + Compose Multiplatform** のネイティブ Android チャットアプリケーション。

## 概要

EgoGraph エージェントと対話するための ChatGPT ライクなインターフェースです。
React + Capacitor から Kotlin Multiplatform に移行し、ネイティブ Android 体験を提供します。

- **Native Android**: Compose Multiplatform によるネイティブ UI
- **MVVM**: 状態管理
- **SSE Streaming**: リアルタイムチャット応答
- **Offline First**: ローカルストレージとキャッシング

## アーキテクチャ

- **Framework**: Kotlin 2.3 + Compose Multiplatform
- **Architecture**: MVVM
- **State Management**: StateFlow + Channel ( Kotlin Coroutines )
- **Navigation**: Voyager
- **HTTP Client**: Ktor 3.4.0
- **DI**: Koin 4.0.0
- **Persistence**: Android SharedPreferences (expect/actual)

### プロジェクト構成

```text
frontend/
├── shared/                 # Kotlin Multiplatform モジュール
│   ├── src/commonMain/     # プラットフォーム共通コード
│   │   ├── core/           # コア機能（domain, platform, settings, ui, network）
│   │   │   ├── domain/         # DTOs, Repository インターフェース
│   │   │   │   ├── model/       # データモデル
│   │   │   │   └── repository/  # Repository インターフェース
│   │   │   ├── platform/        # プラットフォーム抽象化
│   │   │   ├── settings/        # テーマ設定
│   │   │   ├── ui/              # 共通UIコンポーネント
│   │   │   └── network/         # HTTPクライアント
│   │   ├── features/       # 機能モジュール（MVVM）
│   │   │   ├── chat/            # チャット機能
│   │   │   │   ├── ChatScreen.kt
│   │   │   │   ├── ChatScreenModel.kt
│   │   │   │   ├── ChatState.kt
│   │   │   │   ├── ChatEffect.kt
│   │   │   │   └── components/  # チャット専用コンポーネント
│   │   │   ├── terminal/        # ターミナル機能
│   │   │   ├── settings/        # 設定画面
│   │   │   ├── sidebar/         # サイドバー
│   │   │   ├── systemprompt/    # システムプロンプト編集
│   │   │   └── navigation/      # ナビゲーション
│   │   └── di/             # 依存性注入モジュール
│   ├── src/androidMain/    # Android 固有実装
│   └── src/commonTest/     # 共通テスト
└── androidApp/             # Android アプリエントリポイント
    └── src/main/           # AndroidManifest, MainActivity
```

### アーキテクチャ

本プロジェクトは **MVVM (StateFlow + Channel)** アーキテクチャを採用しています。

#### 画面構成（Screen + ScreenModel + State + Effect）

| レイヤー        | 役割                       | ファイル例           |
| --------------- | -------------------------- | -------------------- |
| **Screen**      | Compose UI 表示            | `ChatScreen.kt`      |
| **ScreenModel** | ビジネスロジック・状態更新 | `ChatScreenModel.kt` |
| **State**       | UI状態（データクラス）     | `ChatState.kt`       |
| **Effect**      | One-shotイベント           | `ChatEffect.kt`      |

#### シンプルな画面

設定画面など状態遷移が単純な画面はScreenのみとし、State/Effectを省略しています。
これはIntentionalな設計判断です。

## ビルド要件

### 必須ツール

- **JDK**: 17 以上（推奨: JDK 21）
- **Android SDK**: API 34（コマンドラインツール）
  - Build Tools 34.0.0
  - Platform Tools
- **Gradle**: 8.8+ (Wrapper 同梱)

### テストフレームワーク

- **kotlin-test**: Kotlin 標準テスト
- **Turbine**: Flowのテスト
- **MockK**: モックライブラリ
- **Ktor MockEngine**: HTTPモック

## リリース署名

本番リリースには独自の署名キーが必要です。

### 1. リリースキーストアの作成

```bash
keytool -genkey -v \
  -keystore release.keystore \
  -alias egograph \
  -keyalg RSA -keysize 2048 -validity 10000
```

### 2. 署名設定

`androidApp/build.gradle.kts` に署名設定を追加:

```kotlin
android {
    signingConfigs {
        create("release") {
            storeFile = file("../release.keystore")
            storePassword = System.getenv("KEYSTORE_PASSWORD")
            keyAlias = "egograph"
            keyPassword = System.getenv("KEY_PASSWORD")
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
        }
    }
}
```

### 3. 署名付きリリースビルド

```bash
export KEYSTORE_PASSWORD="your-password"
export KEY_PASSWORD="your-password"

./gradlew :androidApp:assembleRelease
```

## 旧バージョン（React + Capacitor）

React + Capacitor 版はモノレポから分離され、
[`endo-ava/egograph-frontend-capacitor-legacy`](https://github.com/endo-ava/egograph-frontend-capacitor-legacy)
で保守されています。新規開発はすべて KMP 版で行ってください。
