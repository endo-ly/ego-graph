# Chromium History Extension

Chromium MV3 拡張機能。Edge / Brave / Chrome のブラウザ履歴を EgoGraph Pipelines Service に同期します。

## 概要

このブラウザ拡張機能は、Chromium 系ブラウザの閲覧履歴を収集し、EgoGraph Pipelines Service に送信して個人データを一元管理します。ネットワーク障害時のデータ損失を防ぐため、カーソルベースの増分同期を実装しています。

## 機能

- **増分同期**: 前回の成功時以降の新しい履歴のみを送信
- **カーソル永続化**: 同期状況をローカルストレージに保存。`200 OK` のみカーソルを進める
- **起動時自動同期**: ブラウザ起動時に自動的に同期を実行
- **手動同期**: オプションページの「Sync now」ボタンで即時同期
- **バッチ処理**: 大量の履歴は 1000 件単位で分割して送信
- **マルチブラウザ対応**: Edge、Brave、Chrome に対応

## 対応ブラウザ

| ブラウザ | ステータス |
| -------- | ---------- |
| Chrome   | ✅         |
| Edge     | ✅         |
| Brave    | ✅         |

## アーキテクチャ

```text
┌─────────────────────────────────────────────────────────────────┐
│                      Browser Extension                           │
├─────────────────────────────────────────────────────────────────┤
│  Options Page                    │  Background Service Worker   │
│  ┌─────────────────────┐         │  ┌─────────────────────────┐ │
│  │ 設定フォーム         │         │  │ 起動時: 自動同期        │ │
│  │ - Server URL        │         │  │ メッセージ受信: 手動同期│ │
│  │ - X-API-Key         │◄────────┤  └─────────────────────────┘ │
│  │ - Browser ID        │         │              │               │
│  │ - Device ID         │         │              ▼               │
│  │ - Profile           │         │  ┌─────────────────────────┐ │
│  │ [Save] [Sync now]   │         │  │ 同期パイプライン        │ │
│  └─────────────────────┘         │  │ 1. 設定を読み込み       │ │
│                                  │  │ 2. 前回のカーソルを取得  │ │
│                                  │  │ 3. 履歴を収集           │ │
│                                  │  │ 4. ペイロードを構築     │ │
│                                  │  │ 5. Pipelines へ POST    │ │
│                                  │  │ 6. カーソルを更新       │ │
│                                  │  └─────────────────────────┘ │
└──────────────────────────────────┼──────────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ EgoGraph Pipelines  │
                        │  POST /v1/ingest/   │
                        │  browser-history    │
                        └─────────────────────┘
```

## インストール

### 前提条件

- Chromium 系ブラウザ（Chrome、Edge、Brave）
- 起動中の EgoGraph Pipelines Service

### 方法 1: GitHub Actions の Artifact からダウンロード（推奨）

CI でビルド済みの拡張機能をダウンロードできます。ローカルビルド不要です。

1. GitHub リポジトリの **Actions** タブを開く
2. 最新の成功した **Test Browser Extension** ワークフローをクリック
3. ページ下部の **Artifacts** セクションから `chromium-history-extension-dist` をダウンロード
4. ダウンロードした ZIP ファイルを展開（これが `dist/` ディレクトリです）

### 方法 2: ローカルでビルド

Node.js 18+ が必要です。

```bash
# 1. 依存関係をインストール
npm install

# 2. 拡張機能をビルド
npm run build

# 出力: dist/ ディレクトリに拡張機能ファイルが生成されます
```

### 拡張機能の読み込み

1. ブラウザの拡張機能管理ページを開く:
   - **Chrome**: `chrome://extensions/`
   - **Edge**: `edge://extensions/`
   - **Brave**: `brave://extensions/`

2. **デベロッパーモード**を有効にする（右上のトグル）

3. **パッケージ化されていない拡張機能を読み込む**をクリック

4. このプロジェクトの `dist/` ディレクトリを選択

5. 拡張機能をピン留めして、オプションページにアクセスしやすくする

## 設定

拡張機能のオプションページを開き、以下のフィールドを設定してください:

| フィールド  | 説明                                    | 例                              |
| ----------- | --------------------------------------- | ------------------------------- |
| Pipelines Service URL | EgoGraph Pipelines Service のベース URL | `http://localhost:8001`         |
| X-API-Key   | Pipelines Service 認証用の API キー     | `your-api-key-here`             |
| Browser ID  | ブラウザタイプ（ドロップダウンから選択）| `chrome`, `edge`, `brave`       |
| Device ID   | このデバイスを識別するユニークな ID     | `laptop-main`, `work-pc`        |
| Profile     | ブラウザプロファイル名                  | `default`, `work`, `personal`   |

### Device ID と Profile の推奨事項

- **Device ID**: 同期全体で一貫した識別可能な名前を使用してください
- **Profile**: 複数のブラウザプロファイル（例: 仕事用/個人用）を使用している場合に便利です

## 同期の動作

### 初回同期

- **直近 50,000 件**に制限されます
- 完全な訪問詳細（URL、タイトル、訪問時刻、遷移タイプなど）を収集します

### 増分同期

- `lastSuccessfulSyncAt` 以降のアイテムを取得
- 履歴を **10,000 件単位**でページネーション
- 同期ウィンドウ内の新しい訪問のみをフィルタリング

### カーソル管理

```text
┌──────────────┐     成功        ┌──────────────────┐
│   同期実行   │ ─────────────► │ カーソル更新      │
│              │    200 OK      │ (lastSyncedAt)   │
└──────────────┘                └──────────────────┘
        │
        │ 失敗
        ▼
┌──────────────┐
│ カーソル維持 │  ← 次回の同期は同じ位置から再試行
│ (更新なし)   │
└──────────────┘
```

カーソル（`lastSuccessfulSyncAt`）は **同期成功時のみ進む** ため、以下を保証します:
- ネットワーク障害によるデータ損失がない
- 再試行は安全かつ冪等
- 部分的な失敗で重複データが発生しない

## API 仕様

### リクエスト

```http
POST {serverUrl}/v1/ingest/browser-history
Content-Type: application/json
X-API-Key: {xApiKey}
```

### ペイロードスキーマ

```json
{
  "sync_id": "uuid-v4",
  "source_device": "laptop-main",
  "browser": "chrome",
  "profile": "default",
  "synced_at": "2024-01-15T10:30:00.000Z",
  "items": [
    {
      "url": "https://example.com/page",
      "title": "ページタイトル",
      "visit_time": "2024-01-15T10:00:00.000Z",
      "visit_id": "12345",
      "referring_visit_id": "12344",
      "transition": "link"
    }
  ]
}
```

### データの解釈

- この拡張機能は `chrome.history` API が返す visit をそのまま近い形で収集します
- 同一 URL に対して短時間で複数の visit が発生することがあります。特に `link` と `reload` が短い間隔で並ぶケースは正常です
- Pipelines Service では受信 payload を raw JSON として保存しつつ、`events` には 2 秒以内の同一 URL 連続 visit を畳んだ `page view` を保存します

### レスポンス

```json
{
  "accepted": 42
}
```

## トラブルシューティング

### 起動時に同期が実行されない

- 拡張機能に `history` と `storage` の権限があるか確認
- 設定が完了しているか確認（すべてのフィールドが必須）
- Service Worker のブラウザコンソールでエラーを確認

### 「Incomplete settings」エラー

すべての設定フィールドが必須です。以下を確認してください:
- Server URL が有効な URL（`http://` または `https://` を含む）
- X-API-Key が空でない
- Browser ID がドロップダウンから選択されている
- Device ID と Profile が入力されている

### ネットワークエラー

- Pipelines Service が起動していてアクセス可能か確認
- `host_permissions` がサーバー URL を許可しているか確認
- ローカル開発の場合、Pipelines Service で CORS が設定されているか確認

### 同期状態のリセット

完全な再同期を強制するには、拡張機能のストレージをクリアしてください:

1. 拡張機能のオプションページを開く
2. ブラウザの DevTools → Application → Storage を開く
3. 拡張機能のローカルストレージをクリア
4. 設定を再保存

## 開発

### プロジェクト構成

```text
chromium-history/
├── manifest.json           # 拡張機能マニフェスト (MV3)
├── package.json            # npm スクリプトと依存関係
├── tsconfig.json           # TypeScript 設定
├── src/
│   ├── background/
│   │   ├── main.ts         # Service Worker エントリーポイント
│   │   ├── sync.ts         # 同期制御ロジック
│   │   ├── history.ts      # Chrome History API ラッパー
│   │   └── storage.ts      # Chrome Storage API ラッパー
│   ├── options/
│   │   ├── index.html      # オプションページ UI
│   │   └── main.ts         # オプションページロジック
│   └── shared/
│       ├── api.ts          # Pipelines Service API クライアント
│       └── types.ts        # TypeScript 型定義
└── tests/
    ├── history.test.ts     # 履歴収集テスト
    ├── sync.test.ts        # 同期ロジックテスト
    └── storage.test.ts     # ストレージテスト
```

### コマンド

```bash
# 拡張機能をビルド
npm run build

# テストを実行
npm run test

# ウォッチモードでテストを実行（利用可能な場合）
npm run test -- --watch
```

### テスト

Vitest を使用してユニットテストを実行します。テストでは Chrome API をモックし、ブラウザ依存なしで純粋なロジックをテストします。

```bash
npm run test
```

### 新機能の追加

1. `src/shared/types.ts` で型を更新
2. 適切なモジュールにロジックを実装
3. `tests/` ディレクトリにテストを追加
4. `npm run build` でコンパイルを確認

## セキュリティ考慮事項

- **API キーの保存**: X-API-Key は `chrome.storage.local` に保存され、拡張機能からのみアクセス可能です
- **履歴アクセス**: この拡張機能は閲覧履歴を読み取るために `history` 権限が必要です
- **データ送信**: すべてのデータは設定された Pipelines Service に送信されます。本番環境では HTTPS を使用してください
- **外部トラッキングなし**: この拡張機能はサードパーティサービスにデータを送信しません

## 権限

| 権限       | 目的                           |
| ---------- | ------------------------------ |
| `history`  | 同期のためのブラウザ履歴の読み取り |
| `storage`  | 設定と同期状態の保存            |
| `<all_urls>` | 任意の Pipelines Service URL へのリクエストを許可（設定可能） |

## ライセンス

EgoGraph プロジェクトの一部です。
