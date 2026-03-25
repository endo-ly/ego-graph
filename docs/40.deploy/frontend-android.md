# Frontend Deploy (Android)

本番フロントエンドを Android アプリ（KMP）としてビルド・デプロイする手順。
Kotlin Multiplatform + Compose Multiplatform を使用し、Android ネイティブアプリとして配布する。

## 1. 前提条件

- **JDK**: 17 以上（推奨: JDK 21）
- **Android SDK**: API 34（コマンドラインツール）
- **Gradle**: 8.8+ (Wrapper 同梱)

### 1.1 Android SDK セットアップ

Android Studio を使わずに CLI で開発する場合:

```bash
# Android SDK Command-line Tools をダウンロード
# https://developer.android.com/studio#command-tools

# SDK マネージャーで必要なパッケージをインストール
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

# 環境変数設定
export ANDROID_HOME=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools
```

## 2. ビルド手順

### 2.1 デバッグビルド

```bash
cd frontend
./gradlew :androidApp:assembleDebug
# 成果物: androidApp/build/outputs/apk/debug/androidApp-debug.apk
```

### 2.2 リリースビルド

署名付きリリースビルドを作成するには、キーストアが必要です。

#### A. キーストア作成（初回のみ）

```bash
keytool -genkey -v \
  -keystore release.keystore \
  -alias egograph \
  -keyalg RSA -keysize 2048 -validity 10000
```

#### B. ビルド実行

環境変数を設定してビルドします。

```bash
export KEYSTORE_PASSWORD="your-password"
export KEY_PASSWORD="your-password"

./gradlew :androidApp:assembleRelease
# 成果物: androidApp/build/outputs/apk/release/androidApp-release.apk
```

## 3. インストール

### デバイスへのインストール

```bash
./gradlew :androidApp:installDebug
```

## 4. CI/CD

`ci-frontend.yml` ワークフローにより、GitHub Actions 上で自動テストとビルドが行われます。

## 5. 旧手順（Capacitor）

React + Capacitor 時代のデプロイ手順は、分離済み legacy repo を前提に以下を参照してください：

- [Legacy deploy doc](https://github.com/endo-ava/egograph-frontend-capacitor-legacy/blob/main/docs/40.deploy/frontend-android-capacitor.md)
- [Legacy Capacitor architecture doc](https://github.com/endo-ava/egograph-frontend-capacitor-legacy/blob/main/docs/40.deploy/capacitor.md)
- External repo: <https://github.com/endo-ava/egograph-frontend-capacitor-legacy>
