# 要件定義: モバイル端末からの LXC tmux 接続（Terminal Gateway）

## 1. Summary

- やりたいこと：Android アプリから、Tailscale 経由で LXC 上の tmux に接続し、複数コーディングエージェントの並行運用、通知受信、音声入力を行えるようにする
- 理由：外出時や離席時でも、進行中タスクの確認・追加入力・再接続・割り込み対応をスマホで継続したい
- 対象：独立 Mobile Gateway サービス（Session API + WebSocket Gateway + Push API）+ Frontend Terminal 画面（Agent一覧/切替 + 音声入力）+ FCM連携
- 優先：高

## 初期稼働環境

- `dev` LXC（初期導入先）

## 2. Purpose (WHY)

- いま困っていること：
  - LXC 上で進行中の作業をスマホから継続できない
  - 複数エージェントを同時稼働する際に、操作対象の切替が難しい
  - 接続断時の復帰に手間がかかる
  - エージェントの完了・入力要求に気づけない
  - 音声で素早く指示を入れられない
- できるようになったら嬉しいこと：
  - 複数エージェントをモバイルから選択・接続・再接続できる
  - 通知で必要なタイミングだけ介入できる
  - 音声で入力して送信前に確認できる
- 成功すると何が変わるか：
  - エージェント運用の継続性と同時並行性が上がる
  - 作業待ち時間の活用効率が上がる
  - モバイル単体での実運用が成立する

## 3. Requirements (WHAT)

### 機能要件

- 接続対象
  - 接続先は初期稼働環境に準ずる
- Agent Session（内部概念）
  - 並列エージェントごとに tmux セッションを1つ持つ
  - ユーザーは Agent 一覧から操作対象を選択して接続できる
  - 接続切断後も LXC 側のセッション状態は保持される
  - MVP では gateway 側でセッション作成しない（作成導線はMVP対象外）
  - 一覧は `tmux list-sessions` を真実ソースとし、`^agent-[0-9]{4}$` のみ対象にする
  - セッションIDはユーザー編集不可（表示名はMVPでは session_id と同一）
- Agent 一覧状態定義（MVP）
  - 接続中: 当該 `session_id` に対するWS接続が1本以上ある
  - 切断: tmux セッションは存在するがWS接続が0本
  - 失敗: 直近の接続試行が失敗した
  - 状態キャッシュはプロセス内メモリとし、gateway再起動時にリセットされる
- 入出力
  - 端末入力を送信できる
  - 端末出力をリアルタイム受信・表示できる
  - 画面サイズ変更時に `resize` が反映される
- 認証
  - API/WS 接続時に認証トークンを必須とする
  - 認証失敗時は一覧取得・接続・通知登録とも不可とする
  - MVP は固定 Bearer token 方式（環境変数照合）を採用する
  - webhook は `X-Webhook-Secret` の一致検証を必須とする
  - 環境変数例: `GATEWAY_BEARER_TOKEN`, `GATEWAY_WEBHOOK_SECRET`（各32bytes以上）
- 再接続
  - 接続断時は自動再接続を行う
  - ユーザーが明示的に再接続を実行できる
- 通知（FCM）
  - アプリは FCM トークンを gateway サービスに登録できる
  - gateway サービスは webhook を受けて「タスク完了」「入力要求」を通知種別として送信できる
  - MVP は単一ユーザー運用（`default_user`）として通知先を解決する
  - `session_id` は通知タップ時の遷移先特定に使う
  - 通知タップで該当 Agent の Terminal 画面に遷移できる
- PTY ライフサイクル
  - WS 接続時に tmux へ attach するプロセスを起動する
  - MVP では WS 1本ごとに attach プロセスを1つ起動する
  - WS 切断時は attach プロセスを終了してよい
  - tmux セッション自体は終了しない
- 音声入力
  - Terminal 画面で音声入力を開始/停止できる
  - 認識結果は即送信せず、入力欄プレビューに反映する
  - ユーザー確定後にのみ端末へ送信する
- 可観測性
  - 接続成功/切断/失敗理由と、通知送信結果を識別できるログが残る

### 期待する挙動

- ユーザーは Agent 一覧から目的のエージェントを選んで接続できる
- 複数 Agent Session は相互に状態が混線しない
- 接続が落ちても自動再接続し、必要なら手動再接続で復帰できる
- 通知から該当 Agent の画面に直接戻れる
- 音声認識結果は送信前に必ず目視確認できる
- 未認証または不正トークンでは接続できない

### 画面要件

- 画面遷移
  - 既存チャット画面から「サイドバーを開く操作の逆方向スワイプ」で Terminal 導線へ遷移できる
- 画面A: Agent 一覧画面
  - 一覧項目は「表示名（MVPではsession_id）」「状態（接続中/切断/失敗）」「最終アクティブ時刻」を表示する
  - 空状態では「稼働中エージェントなし」を表示する
  - 一覧から Agent を選ぶと端末画面へ遷移する
- 画面B: Terminal 実行画面
  - xterm 端末領域を表示する
  - 接続中 Agent の表示名を表示する
  - 手動再接続ボタンを表示する
  - Agent 一覧へ戻る導線を表示する
  - 特殊キー列を常設する
  - 音声入力ボタン（開始/停止）を表示する
  - 音声認識プレビュー欄を表示する
- 画面C: 通知設定状態
  - 通知許可状態（許可/未許可）を表示する
  - 未許可時は許可導線を表示する
- 特殊キー列（必須セット）
  - `Ctrl` `Esc` `Tab` `/` `↑` `↓` `←` `→` `Shift+Tab` `Ctrl+O`

### 画面状態遷移

- チャット画面 -> 逆方向スワイプ -> Agent 一覧画面
- Agent 一覧画面 -> Agent 選択 -> Terminal 実行画面（Connected）
- Terminal 実行画面 -> 切断検知 -> Reconnecting 表示 -> 復帰 or 失敗表示
- Terminal 実行画面 -> 一覧へ戻る -> 別 Agent 選択で再接続
- 通知受信 -> 通知タップ -> 対象 Agent の Terminal 実行画面

### UIイメージ（ASCII）

```text
[Chat Screen]
  └─(サイドバー逆方向スワイプ)─> [Agent List]
                                 ├─ agent-0001  Connected  12:41
                                 ├─ agent-0002  Disconnected 12:03
                                 └─ agent-0003  Failed     11:52
                                      │
                                      └─ tap
                                         v
+---------------------------------------------------+
| Terminal Screen (agent-0001)                     |
| Status: Connected   [Reconnect]   [Back to List] |
|---------------------------------------------------|
| $ claude "fix test"                               |
| ...streaming output...                            |
|                                                   |
| [Ctrl][Esc][Tab][/][↑][↓][←][→][Shift+Tab][Ctrl+O] |
| [Mic Start/Stop]  Voice Preview: "..."            |
+---------------------------------------------------+
        │
        ├─ network lost -> Reconnecting -> Connected
        └─ push tap (input_required/task_completed) -> reopen this screen
```

### API 契約（MVP）

- `GET /v1/terminal/sessions`
  - Agent Session 一覧取得
- `WS /ws/terminal?session_id=<session_id>`
  - 端末入出力チャネル
- `PUT /v1/push/token`
  - FCM トークン登録/更新
  - リクエスト例: `{"platform":"android","token":"<fcm_token>","device_name":"pixel"}`
- `POST /v1/push/webhook`
  - 外部ジョブからの通知要求受付（gateway 内部で FCM 送信）
  - ヘッダ例: `X-Webhook-Secret: <secret>`
  - リクエスト例: `{"type":"task_completed|input_required","session_id":"agent-0001","title":"...","body":"..."}`

### 内部仕様（MVP固定）

- 一覧の取得方法
  - `GET /v1/terminal/sessions` は `tmux list-sessions -F '#{session_name}\t#{session_activity}\t#{session_created}'` を使用して機械的に取得する
  - 上記結果から `^agent-[0-9]{4}$` を列挙対象にする
  - 最終アクティブ時刻は tmux の `session_activity` を使用する（取得不可時は `session_created`）
- 通知トークン永続化（SQLite 1テーブル）
  - テーブル例: `push_devices`
  - 主な列: `user_id`, `device_token`, `platform`, `device_name`, `last_seen_at`, `enabled`
  - MVP では `user_id='default_user'` 固定で運用する
  - `PUT /v1/push/token` は `device_token` キーで upsert し、`enabled=true`, `last_seen_at=now` で更新する
  - FCM送信で無効トークン系エラーを受けた場合は `enabled=false` に更新する
- 通知ルーティング
  - `POST /v1/push/webhook` は `default_user` の `enabled=true` な token 全件へ送る
  - `session_id` は通知ペイロードに含め、アプリ遷移に使用する
  - `/v1/push/webhook` は Tailscale 経由からのみ到達可能とする（FW/ACL）

### WebSocket メッセージ（MVP）

- Client -> Server
  - `{"type":"input","data_b64":"..."}`
  - `{"type":"resize","cols":120,"rows":30}`
  - `{"type":"ping"}`
- Server -> Client
  - `{"type":"output","data_b64":"..."}`
  - `{"type":"status","state":"connected|reconnecting|closed"}`
  - `{"type":"error","code":"...","message":"..."}`
  - `{"type":"ping"}`
- 補足
  - 制御系はJSONで扱う
  - `input.data_b64` はクライアントがUTF-8エンコードしたバイト列をBase64化したもの
  - `output.data_b64` はPTYから読んだ生バイト列をBase64化したもの
  - クライアントは一定時間 `output` / `ping` を受信しない場合、再接続へ遷移する

### セッション命名規則（内部）

- 形式：`agent-0001`（4桁ゼロ埋め連番）
- 正規表現：`^agent-[0-9]{4}$`
- 採番責任：エージェント起動側（gateway は既存セッションを列挙）
- 一意性：システム内で重複不可

## 4. Scope

### 今回やる（MVP）

- 独立 Mobile Gateway サービスとして運用（EgoGraph BE 非依存）
- 複数 Agent Session の一覧・選択
- 端末入力/出力の双方向通信
- 自動再接続 + 手動再接続
- API/WS の認証トークン必須化
- 特殊キー列（指定セット）
- 通知トークン登録 + 通知受信（完了/入力要求）
- 音声入力（送信前プレビュー必須）
- 接続ログと通知ログの記録

### 今回やらない（Won't）

- 危険コマンド確認ダイアログ
- 端末失効などの管理画面
- 音声入力の辞書カスタム

### 次回以降（あれば）

- 通知の優先度ルール詳細化
- 音声入力の精度改善（文脈補正）
- 端末紛失時の接続/通知停止運用

## 5. User Story Mapping

| Step | MVP（最低限） | Nice to have |
|---|---|---|
| 遷移 | チャット画面から逆方向スワイプで Agent 一覧へ移動できる | ボタン導線の併設 |
| 選択 | 一覧から Agent を選び端末接続できる | 一覧の検索・ソート |
| 操作 | 入力送信、出力表示、特殊キー操作ができる | カスタムキー配置 |
| 復帰 | 自動再接続し、必要時は手動再接続できる | バックオフ設定調整 |
| 通知 | 完了/入力要求通知を受け、タップで対象 Agent へ戻れる | 通知カテゴリ別の表示制御 |
| 音声 | 音声認識結果をプレビュー確認して送信できる | 句読点補正や定型文展開 |

## 6. Acceptance Criteria

- Given 正常な認証トークンを持つユーザー, When チャット画面で逆方向スワイプ操作を行う, Then Agent 一覧画面へ遷移できる
- Given 正常な認証トークンを持つユーザー, When 一覧 API を呼ぶ, Then Agent Session 一覧を取得できる
- Given `agent-0001` と `agent-0002` が存在する, When それぞれへ接続を切り替える, Then 出力と入力文脈が混線しない
- Given 接続中に一時的なネットワーク断が発生する, When 接続が回復する, Then 自動再接続し、失敗時は手動再接続で復帰を試行できる
- Given Terminal 実行画面を操作中, When 特殊キー列で `Ctrl` `Esc` `Tab` `/` `Shift+Tab` `Ctrl+O` と矢印キーを入力する, Then 対応する入力が端末へ送信される
- Given FCM トークンが登録済み, When webhook 経由で `input_required` 通知要求を送る, Then 端末に通知が表示され、タップで対象 Agent 画面へ遷移できる
- Given 音声入力を開始したユーザー, When 認識結果が返る, Then 入力欄にプレビュー表示され、ユーザー確定までは送信されない
- Given トークンが欠落または不正, When API/WS にアクセスする, Then 一覧取得・接続・通知登録とも拒否される
- Given gateway が再起動した, When 一覧 API を呼ぶ, Then セッション状態は再計算され、失敗状態のメモリキャッシュは引き継がれない

## 7. 例外・境界（必要なら）

- 失敗時（通信/保存/権限）：接続失敗理由と通知失敗理由を UI/ログで判別できる
- 空状態（データ0件）：Agent Session 0件時は空状態表示のみ（作成導線はMVP対象外）
- 上限（文字数/件数/サイズ）：同一ユーザーの最大セッション数は運用設定で制御する
- 既存データとの整合（互換/移行）：既存 tmux 運用を壊さず導入する
- 音声認識：認識失敗時は入力欄を変更せず、再試行導線を表示する

## 8. Non-Functional Requirements (FURPS)

- Performance：入力から表示までの遅延が体感上の操作を妨げない
- Reliability：接続断後もセッション文脈を失わない
- Usability：スマホ単体で一覧・接続・切替・再接続・通知対応・音声入力が完結する
- Security/Privacy：Tailscale 経路 + 認証トークン必須、通知トークンはユーザー紐付けで管理する
- Constraints（技術/期限/外部APIなど）：Android アプリ + FCM + OS 音声認識機能を対象とする

## 9. RAID (Risks, Assumptions, Issues, Dependencies)

- Risk：モバイル回線品質と音声認識精度により体験が不安定になる可能性
- Assumption：初期稼働環境は Tailscale 経由で常時到達可能、Android で通知と音声権限を取得可能
- Issue：セッション数上限の初期値が未確定
- Dependency：Android 側 terminal UI/通知受信/音声入力、独立 Gateway サービス、FCM、Tailscale

## 10. Reference

- 旧草案（フェーズ 0-8 の会話メモ版）
- `docs/00.project/requirements/` 既存要件フォーマット

## 11. フェーズ整理（実施順）

- フェーズA（今回）：複数 Agent Session + 通知 + 音声入力 MVP
- フェーズB（次回）：通知/音声の高度化、安全装置、端末管理

## 12. 実現方針（HOW の方向性）

- Gateway サービス方針
  - EgoGraph の既存 BE には追加せず、LXC 全体で使う独立サービスとして配置する
  - 実装は Starlette + Uvicorn を基本とし、FastAPI は必須にしない
  - API は4本のみ（`GET /v1/terminal/sessions`, `WS /ws/terminal`, `PUT /v1/push/token`, `POST /v1/push/webhook`）に固定する
  - `GET /v1/terminal/sessions` は tmux を真実ソースとして列挙する
  - 接続時は `tmux attach -t <session_id>` を基本とし、存在しない session_id はエラーで返す
  - WS は `input/resize/ping` と `output/status/error` のイベント駆動で統一する
  - 入出力 payload は `data_b64` で運ぶ
  - Push token の永続化は最小構成（例: SQLite 1テーブル）とする
  - `POST /v1/push/webhook` は secret 検証後に FCM へ種別付き通知を送る
  - `/v1/push/webhook` は Tailscale 内ネットワークからのみ受け付ける
  - Bearer token は環境変数の固定ランダム文字列（32bytes以上）で検証する
  - WS切断時は attach プロセスを終了し、tmux セッションは保持する
  - ログは `session_id`, `user_id`, `event`, `reason` を構造化で残す
- Frontend 方針
  - 「Agent 一覧画面」と「Terminal 実行画面」の2画面構成とする
  - チャット画面から逆方向スワイプで Agent 一覧へ遷移する
  - 端末描画は WebView + xterm.js を利用し、サイズ変更時に `resize` を必ず送る
  - 切断時は自動再接続を試みつつ、手動再接続導線を常に表示する
  - 特殊キー列は固定セットを常設する
  - 音声入力は OS 標準認識を利用し、結果は入力欄プレビュー後に送信する
- 運用方針
  - 接続先は初期稼働環境に準ずる
  - 並列稼働時の操作対象切替は必須機能として扱う
  - 複数クライアント運用では「スマホ用window / PC用window」を分ける
  - tmux 側で複数クライアント前提設定（例: `aggressive-resize`）を有効化する

## 13. 追加依存ライブラリ（確定）

### Gateway サービス（Python）

- 必須（MVP）
  - `starlette`（Web API + WebSocket）
  - `uvicorn`（ASGIサーバー）
  - `firebase-admin`（FCM送信用）
- 追加しない（MVP）
  - SQLite は Python 標準 `sqlite3` を使うため、追加ライブラリなし
  - JWTライブラリは追加せず、Bearer token + `X-Webhook-Secret` で運用

### Android / Frontend

- 必須（MVP）
  - `xterm.js`（端末描画のコア）
  - `xterm-addon-fit`（表示領域に合わせた cols/rows 再計算）
  - `com.google.firebase:firebase-messaging`（FCM 受信と token 取得）
  - WebSocket は WebView 内の標準 `WebSocket` を利用
  - 音声入力は Android 標準 `SpeechRecognizer` を利用
  - Android 権限（Manifest）：`INTERNET`, `POST_NOTIFICATIONS`, `RECORD_AUDIO`

### 依存運用の初期選定（確定）

- xterm.js 配布方式
  - JS資産をアプリ assets に同梱する
- xterm.js アドオン構成
  - `xterm-addon-fit` のみ採用する
- 描画バックエンド
  - xterm.js 既定描画を採用する（`xterm-addon-webgl` はMVPで導入しない）

### 将来拡張の依存候補（現時点では未導入）

- 音声入力高度化（ローカル推論）
  - Whisper 量子化モデル（例: `whisper.cpp` 系）を将来候補として考慮する
  - 導入時は APK サイズ、端末性能、推論遅延、モデル配布方式を別途評価する
