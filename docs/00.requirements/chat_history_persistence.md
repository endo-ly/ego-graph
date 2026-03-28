# 要件定義: チャット履歴の永続化

## 1. Summary

- やりたいこと：チャットUIの会話履歴を永続化し、スレッド一覧から過去の会話に戻れるようにする
- 理由：現状はセッションクリアで会話が消え、過去の会話を参照できない
- 対象：Backend API（DuckDB永続化）+ Frontend UI（スレッド一覧・履歴表示）
- 優先：MVP最小限（一覧・新規作成・履歴閲覧のみ、編集・削除・検索は次フェーズ）

## 2. Purpose (WHY)

- いま困っていること：
  - セッションをクリアすると会話履歴が消失する
  - 過去の会話を参照できない、質問の繰り返しが発生する
  - ChatGPTのような「スレッド一覧から戻る」体験ができない

- できるようになったら嬉しいこと：
  - 過去の分析結果や質問履歴をいつでも振り返れる
  - 複数のトピックを並行して管理できる（音楽分析、統計確認など）
  - データ分析の継続性が向上する

- 成功すると何が変わるか：
  - EgoGraphが「使い捨てチャット」から「知識ベース」に進化
  - ユーザー体験がChatGPTに近づき、直感的な操作が可能に
  - 将来的な分析機能（トレンド把握、よくある質問など）の基盤になる

## 3. Requirements (WHAT)

### 機能要件

#### Backend API
- スレッド管理
  - スレッドの自動作成（初回メッセージ送信時）
  - スレッド一覧の取得（ページネーション対応）
  - スレッド詳細の取得
  - メッセージ履歴の取得

- データ永続化
  - DuckDBローカルファイルに保存（`backend/data/chat.duckdb`）
  - threads テーブル（スレッドメタデータ）
  - messages テーブル（メッセージ本文）

#### Frontend UI
- **レイアウト**: ChatGPT風のスワイプ式サイドバー
  - サイドバー（スレッド一覧）+ メインエリア（チャット画面）
  - サイドバー幅: 320px固定
  - 表示方式: オーバーレイ（チャット画面の上に重なる）

- **サイドバー（スレッド一覧）**
  - 無限スクロールでスレッド表示（初期20件）
  - 表示内容: タイトル（太字、最大2行）のみ
  - 最終メッセージ時刻降順でソート
  - 「新規チャット」ボタンをサイドバー上部に配置

- **サイドバーの表示状態**
  - モバイル/タブレット（画面幅 < 768px）: デフォルト非表示
  - デスクトップ（画面幅 ≥ 768px）: 常時表示

- **サイドバーの開閉操作**
  - ハンバーガーメニューボタン（チャット画面左上）で開閉
  - 画面端から右スワイプで開く
  - 左スワイプで閉じる
  - サイドバー外タップで閉じる
  - スレッド選択時に自動で閉じる（モバイル）

- **チャット画面**
  - 常にスレッドに紐付けて動作
  - ヘッダーに「新規チャット」ボタンを配置
  - ヘッダー左上にハンバーガーメニューボタン
  - スレッド選択で過去の会話を再開

### 期待する挙動

#### スレッド作成フロー
1. ユーザーが「新規」ボタンをクリック
2. 空のチャット画面が表示される（スレッド未作成）
3. ユーザーが初回メッセージを送信
4. Backend APIが新規スレッドを自動作成し、メッセージを保存
5. Frontend が thread_id を受け取り、以降のメッセージはそのスレッドに紐付く

#### スレッド閲覧フロー
1. ユーザーがスレッド一覧から過去のスレッドを選択
2. Backend APIからメッセージ履歴を取得
3. チャット画面に履歴を表示
4. ユーザーは会話を継続できる（新しいメッセージを追加）

### 画面/入出力

#### API エンドポイント

**1. POST /v1/chat（既存を拡張）**
- リクエスト:
  ```json
  {
    "thread_id": "uuid-string" | null,  // オプショナル、nullまたは省略で新規作成
    "messages": [
      {"role": "user", "content": "先月のトップ5は？"}
    ]
  }
  ```
- レスポンス:
  ```json
  {
    "thread_id": "uuid-string",  // 新規作成時は生成されたID、既存時は指定されたID
    "id": "message-id",
    "message": {
      "role": "assistant",
      "content": "トップ5は..."
    },
    "usage": {...}
  }
  ```

**2. GET /v1/threads**
- クエリパラメータ:
  - `limit`: 取得件数（デフォルト20）
  - `offset`: オフセット（デフォルト0）
- レスポンス:
  ```json
  {
    "threads": [
      {
        "thread_id": "uuid",
        "title": "先月のトップ5は？（初回メッセージの先頭50文字）",
        "preview": "次は2024年の..（最新メッセージの先頭50文字）",
        "message_count": 12,
        "created_at": "2024-01-15T10:30:00Z",
        "last_message_at": "2024-01-15T12:45:00Z"
      }
    ],
    "total": 45,
    "limit": 20,
    "offset": 0
  }
  ```
  - **注**: MVPのFrontend UIでは`title`のみ表示。`preview`, `message_count`, `last_message_at`はAPIに含めるが将来の拡張性のため（現時点では非表示）

**3. GET /v1/threads/{thread_id}**
- レスポンス: 単一スレッドのメタデータ（上記と同じ形式）

**4. GET /v1/threads/{thread_id}/messages**
- レスポンス:
  ```json
  {
    "thread_id": "uuid",
    "messages": [
      {
        "message_id": "uuid",
        "role": "user",
        "content": "先月のトップ5は？",
        "created_at": "2024-01-15T10:30:00Z"
      },
      {
        "message_id": "uuid",
        "role": "assistant",
        "content": "トップ5は...",
        "created_at": "2024-01-15T10:30:15Z"
      }
    ]
  }
  ```

#### データベーススキーマ

**threads テーブル**
```sql
CREATE TABLE threads (
  thread_id UUID PRIMARY KEY,
  user_id VARCHAR NOT NULL,  -- MVP: 固定値 'default_user'
  title VARCHAR(50) NOT NULL,  -- 初回メッセージの先頭50文字
  created_at TIMESTAMP NOT NULL,
  last_message_at TIMESTAMP NOT NULL,
  INDEX idx_user_last_message (user_id, last_message_at DESC)
);
```

**messages テーブル**
```sql
CREATE TABLE messages (
  message_id UUID PRIMARY KEY,
  thread_id UUID NOT NULL,
  user_id VARCHAR NOT NULL,  -- 将来の複数ユーザー対応用
  role VARCHAR NOT NULL,  -- 'user', 'assistant', 'system'
  content TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (thread_id) REFERENCES threads(thread_id),
  INDEX idx_thread_created (thread_id, created_at)
);
```

## 4. Scope

### 今回やる（MVP）
- Backend
  - DuckDBローカルファイルでの永続化
  - スレッド自動作成（初回メッセージ送信時）
  - スレッド一覧API（ページネーション対応）
  - メッセージ履歴取得API
  - 既存 `/v1/chat` の拡張（thread_id対応）

- Frontend
  - スレッド一覧画面（無限スクロール）
  - 「新規」ボタンによる新規チャット開始
  - スレッド選択による履歴閲覧
  - スレッドへのメッセージ追加

### 今回やらない（Won't）
- スレッドの手動タイトル編集
- スレッドの削除機能
- スレッド検索機能
- タグ・カテゴリ機能
- Parquetへのアーカイブ
- 複数ユーザー対応（user_id は固定値 'default_user'）
- メッセージの個別編集・削除
- ストリーミング対応（既存のstream: boolは将来用）

### 次回以降（検討）
- スレッド編集・削除
- 検索・フィルタ機能
- タグ付け・カテゴリ分類
- Parquetへの長期アーカイブ
- 複数ユーザー対応（Postgres移行検討）

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 1. チャット開始 | 「新規」ボタンで空画面表示 | タイトル入力オプション |
| 2. メッセージ送信 | 初回送信時に自動でスレッド作成、タイトル自動生成 | LLMで要約タイトル生成 |
| 3. 会話継続 | メッセージがスレッドに保存される | リアルタイムタイトル更新 |
| 4. スレッド一覧閲覧 | サイドバーで無限スクロール、タイトルのみ表示 | 検索・フィルタ、プレビュー・日時表示 |
| 5. 過去会話を開く | スレッド選択で履歴を全件表示 | ページング・遅延読み込み |
| 6. 会話再開 | 履歴を見ながら新しいメッセージを送信 | 途中から分岐（フォーク機能） |

## 6. Acceptance Criteria

1. **スレッド自動作成**
   - Given: ユーザーが「新規」ボタンをクリックし、空のチャット画面が表示されている
   - When: ユーザーが初回メッセージ「先月のトップ5は？」を送信
   - Then: Backend が新規スレッドを作成し、タイトル「先月のトップ5は？」（50文字制限）を設定し、thread_id をレスポンスに含める

2. **スレッド一覧表示**
   - Given: 過去に10個のスレッドが作成されている
   - When: ユーザーがサイドバーを開く（モバイル）またはデスクトップで画面を開く
   - Then: 最終メッセージ時刻降順で10件のスレッドが表示され、各スレッドにタイトル（太字、最大2行）のみ表示される

3. **履歴閲覧**
   - Given: スレッド一覧から特定のスレッドを選択
   - When: チャット画面が開く
   - Then: 過去のメッセージが時系列順（古い順）で全件表示される

4. **会話継続**
   - Given: 過去のスレッドを開いて履歴が表示されている
   - When: ユーザーが新しいメッセージ「次は？」を送信
   - Then: メッセージが同じスレッドに追加され、last_message_at が更新され、プレビューが「次は？」に更新される

5. **空状態の表示**
   - Given: まだスレッドが1つも作成されていない
   - When: ユーザーがスレッド一覧画面を開く
   - Then: 「まだ会話がありません。新規チャットを始めましょう」のような案内が表示される

6. **サイドバー操作（モバイル）**
   - Given: モバイル画面（< 768px）でチャット画面を表示している
   - When: ハンバーガーメニューボタンをタップ、または画面端から右スワイプ
   - Then: サイドバーがオーバーレイで表示される

7. **サイドバー閉じる（モバイル）**
   - Given: サイドバーが開いている状態
   - When: 左スワイプ、またはサイドバー外をタップ、またはスレッドを選択
   - Then: サイドバーが閉じ、チャット画面が全面表示される

8. **レスポンシブ表示（デスクトップ）**
   - Given: デスクトップ画面（≥ 768px）で画面を開く
   - When: 初回表示時
   - Then: サイドバーが常時表示され、チャット画面と並んで表示される

## 7. 例外・境界

### 失敗時（通信/保存/権限）
- DB接続失敗: 500 Internal Server Error を返し、エラーログに詳細を記録
- API認証失敗: 既存の verify_api_key による 401 Unauthorized
- スレッド未発見: 404 Not Found（削除済みまたは存在しないthread_id）
- 不正なリクエスト: 422 Unprocessable Entity（バリデーションエラー）

### 空状態（データ0件）
- スレッド一覧が空: Frontend で「まだ会話がありません」を表示
- メッセージ履歴が空: 通常は起こらない（スレッド作成時に必ず1メッセージ存在）

### 上限（文字数/件数/サイズ）
- タイトル: 50文字（初回メッセージから自動生成）
- プレビュー: 50文字（最新メッセージから自動生成）
- メッセージ content: 制限なし（既存のLLM API制限に従う）
- スレッド数: 制限なし（個人用途前提）
- ページネーション: limit最大100件（デフォルト20件）

### 既存データとの整合（互換/移行）
- 既存の `/v1/chat` APIは後方互換を維持（thread_id省略可能）
- thread_id省略時は新規スレッド作成として動作
- 既存のMessage構造は変更なし（tool_callsは保存しない）

## 8. Non-Functional Requirements (FURPS)

- **Performance**:
  - スレッド一覧取得: 100ms以内（ローカルDuckDB、インデックス使用）
  - メッセージ履歴取得: 200ms以内（100件程度想定）
  - 無限スクロール: 追加読み込み時のラグを最小化

- **Reliability**:
  - DB書き込み失敗時はトランザクションをロールバック
  - エラー時は詳細なログを記録（機密情報を除く）

- **Usability**:
  - スレッド一覧は直感的に操作可能（スクロール、タップで開く）
  - 空状態では適切なガイダンスを表示
  - ローディング状態を明確に表示

- **Security/Privacy**:
  - user_id は固定値 'default_user'（MVP）
  - 既存のAPI Key認証を継承
  - ログに個人の会話内容を出力しない（DEBUG時を除く）

- **Constraints（技術/期限/外部APIなど）**:
  - 技術: DuckDBローカルファイル（backend/data/chat.duckdb）
  - 言語: Python 3.13（Backend）、React 19（Frontend）
  - 認証: 既存のAPI Key認証を使用
  - 単一ユーザー前提（将来的に複数ユーザー化の可能性）

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

- **Risk**:
  - DuckDBの同時書き込み競合（個人用途では低リスク）
  - スレッド数増加時のパフォーマンス低下（インデックスで対応）
  - Frontend の無限スクロール実装の複雑さ

- **Assumption**:
  - 単一ユーザーでの利用（user_id = 'default_user'）
  - スレッド数は数百〜数千件程度（個人用途）
  - メッセージ数は1スレッドあたり数十〜数百件
  - tool_calls は保存不要（MVP）

- **Issue**:
  - 既存の `/v1/chat` エンドポイントの後方互換性を保つ必要がある
  - タイムゾーンはUTCで統一（Frontend でローカル変換）

- **Dependency**:
  - Backend: DuckDB、FastAPI、Pydantic
  - Frontend: React 19、既存のチャットUI実装
  - 既存の `/v1/chat` API実装
  - 既存のMessage/ChatRequest モデル

## 10. Reference

- 技術選定ドキュメント: `docs/20.technical_selections/03_chat_history_storage.md`
- 既存API実装: `backend/api/chat.py`
- 既存モデル: `backend/llm/models.py`
- システムアーキテクチャ: `docs/10.architecture/1001_system_architecture.md`
