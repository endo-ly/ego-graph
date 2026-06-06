# 要件定義: LLMモデル選択機能

## 1. Summary

- **やりたいこと**: チャット画面でLLMモデルをフロントエンドから選択可能にする
- **理由**: いろんなモデルを試して比較したい。現在は環境変数で固定されており、変更に再起動が必要
- **対象**: フロントエンド（React）+ バックエンド（FastAPI）
- **優先**: 中（個人利用の利便性向上）

## 2. Purpose (WHY)

- **いま困っていること**:
  - LLMモデル（現在OpenRouter MIMO）が環境変数で固定
  - 変更には `.env` 編集→再起動が必要
  - モデルごとの回答品質を簡単に比較できない

- **できるようになったら嬉しいこと**:
  - チャット途中でも瞬時にモデル切り替え
  - 同じ質問を異なるモデルで試せる
  - コストを見ながらモデル選択できる

- **成功すると何が変わるか**:
  - モデル実験のサイクルが高速化
  - コスト意識した運用が可能
  - 将来的な複数ユーザー対応の基盤

## 3. Requirements (WHAT)

### 機能要件

1. **モデル選択UI**
   - 入力欄近くにドロップダウン配置
   - プリセットから選択（初期4モデル）
   - 各モデルにコスト情報表示（Input/Output単価）

2. **モデル切り替え**
   - チャット途中でも変更可能
   - 同一スレッド継続（履歴は新モデルに渡る）
   - 選択したモデルをlocalStorageに保存

3. **メッセージ表示**
   - 各アシスタントメッセージに使用モデル名を表示
   - モデルごとの回答を比較可能

4. **デフォルト動作**
   - 初回起動: 最初のプリセットモデル
   - 2回目以降: 最後に使ったモデルを記憶
   - スレッド復元時: そのスレッドで最後に使ったモデル

5. **API設計**
   - `ChatRequest` に `model_name` フィールド追加（optional）
   - `GET /v1/chat/models` エンドポイント追加（モデル一覧+コスト情報）
   - `ChatResponse` に使用モデル名を含める

### 期待する挙動

- モデル切り替え時、ページリロード不要
- localStorage が使えない場合もデフォルトモデルで動作
- 無効なモデル名でエラー表示＋送信失敗

### 画面/入出力

**モデル選択ドロップダウン（入力欄近く）**
```
┌─────────────────────────────────────────┐
│ DeepSeek R1T2 Chimera (Free)           │
│   Free                                  │
├─────────────────────────────────────────┤
│ MIMO v2 Flash (Free)                    │
│   Free                                  │
├─────────────────────────────────────────┤
│ Grok 4.1 Fast                           │
│   In: $0.2 / 1M  Out: $0.5 / 1M    │
├─────────────────────────────────────────┤
│ DeepSeek v3.2                           │
│   In: $0.25 / 1M  Out: $0.38 / 1M    │
└─────────────────────────────────────────┘
```

**メッセージ表示**
```
User: 質問内容

Assistant (DeepSeek R1T2 Chimera):
回答内容...

User: 同じ質問

Assistant (MIMO v2 Flash):
別の回答...
```

**API: GET /v1/chat/models レスポンス**
```json
{
  "models": [
    {
      "id": "tngtech/deepseek-r1t2-chimera:free",
      "name": "DeepSeek R1T2 Chimera",
      "provider": "openrouter",
      "input_cost_per_1m": 0.0,
      "output_cost_per_1m": 0.0,
      "is_free": true
    },
    ...
  ]
}
```

**API: POST /v1/chat リクエスト（拡張）**
```json
{
  "messages": [...],
  "model_name": "tngtech/deepseek-r1t2-chimera:free",
  "thread_id": "uuid-string"
}
```

## 4. Scope

### 今回やる（MVP）
- ✅ モデル選択UI（入力欄近く、ドロップダウン）
- ✅ プリセット4モデル（deepseek-r1t2-chimera, mimo-v2-flash, grok-4.1-fast, deepseek-v3.2）
- ✅ コスト表示（Input/Output分離）
- ✅ localStorage 保存（Capacitor対応）
- ✅ メッセージごとのモデル名表示
- ✅ 同一スレッドでのモデル切り替え
- ✅ ChatRequest に model_name 追加
- ✅ GET /v1/chat/models エンドポイント
- ✅ バックエンドでモデル情報管理（固定値）

### 今回やらない（Won't）
- ❌ temperature / max_tokens 調整
- ❌ カスタムモデル入力（自由入力欄）
- ❌ モデル使用量統計
- ❌ モデル廃止時の自動対応
- ❌ OpenRouter以外のプロバイダー（OpenAI, Anthropic直接）
- ❌ プリセット編集UI

### 次回以降（Nice to have）
- temperature / max_tokens UI
- モデル使用量ダッシュボード
- プリセットのカスタマイズ
- OpenRouter API経由のコスト自動取得

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| **チャット開始** | プリセットから選択<br>コスト表示<br>デフォルトモデル選択 | カスタム入力<br>お気に入り機能 |
| **メッセージ送信** | 選択モデルで送信<br>コスト確認<br>エラー表示 | temperature調整<br>コスト上限警告 |
| **モデル切替** | ドロップダウンで変更<br>即座に反映<br>localStorage保存 | プリセット編集<br>比較モード |
| **履歴確認** | モデル名表示<br>コスト確認 | 使用量統計<br>コスト集計 |

## 6. Acceptance Criteria

### AC1: モデル選択表示
```gherkin
Given ユーザーがチャット画面を開いた
When 入力欄近くのモデルドロップダウンを見る
Then 4つのプリセットモデルが表示される
And 各モデルにコスト情報（Input/Output単価）が表示される
And デフォルトで最後に使用したモデルが選択されている
```

### AC2: モデル切り替え
```gherkin
Given ユーザーがチャット途中でモデルを変更した
When 新しいモデルを選択してメッセージを送信
Then 新しいモデルで応答が返る
And 過去のメッセージ履歴も新モデルに渡される（同一スレッド）
And 選択したモデルがlocalStorageに保存される
```

### AC3: メッセージ表示
```gherkin
Given アシスタントがメッセージを返した
When メッセージリストを見る
Then 各メッセージに使用モデル名が表示される
And モデルごとに比較できる
```

### AC4: エラーハンドリング
```gherkin
Given 選択したモデルが存在しない
When メッセージを送信
Then エラーメッセージが表示される
And メッセージは送信されない
And ユーザーにモデル選択の再確認を促す
```

### AC5: スレッド復元
```gherkin
Given 過去のスレッドを開いた
When モデルドロップダウンを見る
Then スレッド内で最後に使用されたモデルが選択されている
And そのモデルでメッセージ送信できる
```

### AC6: モデル一覧API
```gherkin
Given バックエンドに GET /v1/chat/models エンドポイントがある
When フロントエンドが呼び出す
Then 利用可能なモデル一覧が返る
And 各モデルにid, name, provider, input_cost, output_costが含まれる
And レスポンスは200 OKである
```

### AC7: Capacitor対応
```gherkin
Given ユーザーがモバイルアプリ（Capacitor）を使用している
When モデルを選択してlocalStorageに保存
Then アプリ再起動後も選択が保持される
And Web版と同じ挙動をする
```

## 7. 例外・境界

### 失敗時（通信/保存/権限）
- **OpenRouter API障害**: エラーメッセージ表示、送信失敗（フォールバック不要）
- **localStorage読み込み失敗**: デフォルトモデル（deepseek-r1t2-chimera）を使用
- **localStorage書き込み失敗**: エラーログ出力、動作は継続（セッション内で保持）

### 空状態（データ0件）
- **スレッドなし**: デフォルトモデルが選択されている
- **モデル一覧取得失敗**: 固定プリセットをフォールバック表示

### 上限（文字数/件数/サイズ）
- モデル名長: 最大100文字（OpenRouterの仕様に準拠）
- プリセット数: 初期4個（将来的に拡張可能）

### 既存データとの整合（互換/移行）
- **既存スレッド**: model_nameが記録されていない場合はMIMO v2として扱う
- **ChatRequest互換性**: model_nameはoptional、未指定時は環境変数のデフォルトを使用

## 8. Non-Functional Requirements (FURPS)

### Performance
- モデル切り替えによる追加レイテンシ: 許容（モデル依存）
- localStorage読み書き: 無視できるレベル（<10ms）
- GET /v1/models: 初回ロード時のみ、キャッシュ可能

### Reliability
- OpenRouter API障害時: エラー表示（システム停止しない）
- localStorage読み込み失敗: デフォルトモデルにフォールバック

### Usability
- ドロップダウンは常に見える位置（入力欄近く）
- コスト情報は簡潔に表示（2行以内）
- モデル名は読みやすい表示名を使用（技術名は隠す）

### Security/Privacy
- model_nameはバックエンドでバリデーション必須（プリセット外は拒否）
- SQLインジェクション対策（プレースホルダ使用）
- API Keyは引き続き環境変数管理

### Constraints（技術/期限/外部APIなど）
- OpenRouter固有（他プロバイダーは未対応）
- Capacitor環境でもlocalStorage動作必須
- 既存のChatRequest互換性維持（後方互換）
- Python 3.13 + React 19 + DuckDB構成維持

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

### Risk
- **OpenRouterコスト変動**: BE固定値が陳腐化
  - **対策**: 手動更新で対応（MVP）、将来的にAPI自動取得
- **localStorage無効環境**: プライベートブラウジング、企業ポリシー
  - **対策**: デフォルトモデルで動作（セッション内では動作）
- **モデル廃止**: プリセットが使えなくなる
  - **対策**: MVP外、手動で別モデルに差し替え

### Assumption
- OpenRouterは引き続き利用可能
- 指定した4モデルは当面利用可能（無料モデル含む）
- ユーザーは個人利用（認証・マルチユーザー不要）
- localStorage容量は十分（数KB）

### Issue
- なし（既知の問題なし）

### Dependency
- **OpenRouter API**: モデル実行に必須
- **React + Zustand + TanStack Query**: 既存フロントエンド構成
- **Capacitor**: モバイル対応（localStorage互換性）
- **DuckDB + FastAPI**: 既存バックエンド構成

## 10. Reference

### 関連ファイル
- `backend/config.py`: 現在のLLM設定
- `backend/llm/client.py`: LLMClientクラス
- `backend/api/chat.py`: チャットAPI
- `frontend/src/lib/api.ts`: API呼び出し
- `frontend/src/lib/store.ts`: Zustandストア
- `frontend/src/components/chat/ChatInput.tsx`: 入力UI

### OpenRouter対象モデル
1. `tngtech/deepseek-r1t2-chimera:free` - DeepSeek R1T2 Chimera (Free)
2. `xiaomi/mimo-v2-flash:free` - MIMO v2 Flash (Free) ※現在使用中
3. `x-ai/grok-4.1-fast` - Grok 4.1 Fast (有料)
4. `deepseek/deepseek-v3.2` - DeepSeek v3.2 (有料)

### 参考リンク
- [OpenRouter Models](https://openrouter.ai/models)
- [OpenRouter API Docs](https://openrouter.ai/docs)
