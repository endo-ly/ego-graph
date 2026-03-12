# Terminal Swipe Scroll 調査メモ / 解決版

## 結論

今回の問題は、単なる「感度調整」ではなく、次の 2 系統の責務が混ざっていたことが本質だった。

1. 通常スクロール
2. TUI 中スクロール

最終的には、次のように責務を分離することで解決した。

- Android 側:
  - タッチ操作を受け取り、ピクセル差分を WebView に渡すだけ
- `terminal.html` 側:
  - ピクセル差分を「通常 scroll 用の line delta」に変換するだけ
- gateway / tmux 側:
  - その scroll が「通常履歴スクロール」なのか「TUI へのホイール入力」なのかを決定する

重要なのは、**TUI 判定をフロントエンドで推測しない** ことだった。

## 解決後の挙動

### 通常状態

- 従来どおり tmux 履歴を自然にスクロールする
- Android / HTML 側の既存スクロール経路を維持
- gateway 側では感度調整しない

### TUI 状態

- tmux の pane 状態を見て TUI 用ホイール入力へ切り替える
- TUI の外側の履歴が見えない
- 感度調整は TUI 専用経路だけで行う

## 最終アーキテクチャ

### 全体フロー

```text
Android MotionEvent
  |
  | deltaY(px)
  v
TerminalWebView.android.kt
  |
  | TerminalAPI.scrollByPixels(pixelDelta)
  v
terminal.html
  |
  | pixel -> lines へ変換
  | sendScroll(lines)
  v
WebSocket
  |
  v
gateway/services/websocket_handler.py
  |
  | route_scroll(lines)
  v
gateway/services/pty_manager.py
  |
  | tmux の pane 状態を取得
  |
  +--> 通常状態        -> scroll_history(lines)
  +--> copy-mode       -> scroll_history(lines)
  +--> TUI + mouse on  -> SGR wheel を PTY へ送信
  \--> alt screen only -> no-op
```

### どこで何を判断するか

```text
[Android]
  ジェスチャーを取る
  何 px 動いたかだけ知っている
  TUI かどうかは知らない

[terminal.html]
  何行ぶんの scroll か計算する
  既存の通常スクロール経路を維持する
  TUI かどうかは判断しない

[gateway/websocket_handler]
  WebSocket transport
  scroll を pty_manager に渡すだけ

[pty_manager + tmux]
  pane_in_mode / alternate_on / mouse_any_flag を見られる
  端末意味論を知っている
  ここだけが TUI 切り替えの責務を持つ
```

## 何が問題だったか

以前は、`terminal.html` で次のようなことをやろうとしていた。

- escape sequence を自前で読む
- xterm の `mouseTrackingMode` を使う
- alternate screen を自前で読む
- TUI 中だけ別送信経路に分岐する

これらは一見自然だが、実際には危険だった。

### 理由 1. フロントエンドは TUI 判定の権威ではない

Android / WebView / xterm は、あくまで表示と入力の中継である。

- Android はタッチ情報しか持たない
- `terminal.html` は表示済みの文字列しか見えない
- xterm の mode は tmux の pane 状態と完全一致する保証がない

つまり、クライアント側では「今の scroll をどこへ流すべきか」を安全に断定できない。

### 理由 2. escape sequence 自前判定はチャンク分割に弱い

WebSocket の output はチャンク単位で届くため、escape sequence が途中で切れる可能性がある。

そのため、

- ある瞬間だけ誤判定する
- 接続またぎで状態が漏れる
- 通常状態なのに TUI 扱いになる

といった不安定さが出やすい。

### 理由 3. 通常経路を壊しやすい

今回の最重要要件は、最初から最後まで一貫してこれだった。

- 通常スワイプを壊さないこと

しかし TUI 判定を `terminal.html` に入れると、通常スクロールの本線に条件分岐が混ざる。
これが、何度も回帰を起こした原因だった。

## 最終的にどう直したか

### 1. Android 側の責務を固定した

`TerminalWebView.android.kt` は、縦スワイプを検出して `scrollByPixels(...)` を呼ぶだけにした。

Android 側の責務:

- タップ / 縦スワイプ / 横スワイプの切り分け
- `pixelDelta` を JavaScript に渡す

Android 側でやらないこと:

- TUI 判定
- 履歴スクロールかホイールかの分岐
- tmux 状態の推測

この時点で Android は「入力の正規化担当」と割り切る。

### 2. `terminal.html` の責務を「pixel -> lines 変換」に限定した

`terminal.html` は従来の正常動作を持っていたため、これを極力守った。

現在の責務:

- `scrollTerminalByPixels(pixelDelta)`
- `touchScrollRemainder += pixelDelta * SCROLL_DAMPING_FACTOR`
- `cellHeight` で line delta を計算
- `sendScroll(lines)` を WebSocket に送る

`terminal.html` でやらないこと:

- TUI 自動判定
- mouse mode 判定
- alternate screen 判定
- TUI 専用 wheel 送信

これにより、通常スクロールの既存経路を守れた。

### 3. gateway の責務を「transport only」に戻した

`websocket_handler.py` では、以前のような通常スクロール感度調整をやめた。

やることは単純で、

- `scroll` メッセージを受ける
- `message.lines` をそのまま `pty_manager.route_scroll()` に渡す

だけにした。

ここは判断ロジックを持ちすぎない方が読みやすい。

### 4. tmux 状態に基づいて scroll の行き先を決めるようにした

一番大きな変更点はここ。

`pty_manager.py` で tmux の pane 状態を取得し、scroll の行き先を分岐するようにした。

見ている情報:

- `#{pane_in_mode}`
- `#{alternate_on}`
- `#{mouse_any_flag}`
- `#{pane_width}`
- `#{pane_height}`

この情報は tmux 自身が持っているため、xterm の推測より信頼できる。

### scroll ルーティング規則

```text
if pane_in_mode:
    tmux copy-mode の履歴スクロール

elif mouse_any_flag:
    TUI が mouse input を受け取れる状態
    -> wheel を PTY へ送る

elif alternate_on:
    TUI だが mouse 非対応
    -> 外側履歴を見せないため no-op

else:
    通常履歴スクロール
```

## TUI 感度をどこで落としたか

今回追加した考え方は、**通常感度と TUI 感度を別ノブとして扱う** ことだった。

### 通常スクロール感度

通常スクロールは従来どおり `terminal.html` 側で持つ。

- `SCROLL_DAMPING_FACTOR`
- `MAX_SCROLL_LINES`

これは pixel -> lines 変換の責務なので、クライアント側にあるのが自然。

### TUI スクロール感度

TUI は gateway / tmux 側で only-one の責務として持つ。

- `TUI_WHEEL_SENSITIVITY_FACTOR`
- `_tui_wheel_remainder`

つまり、

- Android は TUI 感度を知らない
- `terminal.html` も TUI 感度を知らない
- TUI にだけ効く感度調整は `pty_manager.py` だけが持つ

これにより、通常スクロールへ影響を与えずに TUI だけ調整できるようになった。

### TUI 感度調整の仕組み

```text
lines from client
  |
  v
_tui_wheel_remainder += lines * TUI_WHEEL_SENSITIVITY_FACTOR
  |
  v
wheel_steps = trunc(_tui_wheel_remainder)
  |
  +--> 0 ならまだ送らない
  \--> 1 以上ならその回数だけ wheel を送る
```

今回の設定では、

- `TUI_WHEEL_SENSITIVITY_FACTOR = 0.5`

としており、以前より TUI だけ少し鈍くしている。

## なぜこの責務分離がよかったか

### 1. 通常経路を固定できた

通常スクロールは、次の一本に固定された。

```text
Android
  -> scrollByPixels(px)
  -> terminal.html が lines に変換
  -> sendScroll(lines)
  -> gateway
  -> tmux history scroll
```

この経路に TUI 判定を混ぜなくて済む。

### 2. TUI 判定を「推測」ではなく「tmux の事実」に寄せられた

以前は、

- escape sequence を読む
- xterm mode を読む

という「推測」ベースだった。

今は、

- tmux の pane 状態を直接見る

という「事実」ベースに変わった。

これが一番大きい。

### 3. 感度調整のノブが素直になった

今はノブがきれいに分かれている。

- 通常感度:
  - `terminal.html`
- TUI 感度:
  - `pty_manager.py`

この分離により、

- 通常だけ調整したい
- TUI だけ調整したい

の両方を安全にできる。

## 実装ファイル

今回の最終形で重要なのは次のファイル。

- `frontend/shared/src/androidMain/kotlin/dev/egograph/shared/core/platform/terminal/TerminalWebView.android.kt`
  - タッチ入力の正規化
- `frontend/shared/src/commonMain/resources/assets/xterm/terminal.html`
  - pixel -> lines 変換
- `gateway/services/websocket_handler.py`
  - WebSocket transport
- `gateway/services/pty_manager.py`
  - tmux 状態取得と scroll route の本体

## 実装イメージ

### Before

```text
Android
  -> HTML
       -> TUI かも?
       -> xterm mode かも?
       -> escape sequence かも?
       -> 通常 scroll or wheel をここで決める

問題:
  通常経路に判定が混ざる
  判定根拠が不安定
  回帰しやすい
```

### After

```text
Android
  -> pixel を送るだけ

HTML
  -> lines に変換するだけ

gateway
  -> 運ぶだけ

tmux / pty_manager
  -> pane 状態を見て最終判断する

結果:
  通常系を壊さない
  TUI だけ安全に分岐できる
  感度調整の責務が明確
```

## テスト観点

最低限、次を unit test で固定した。

- 通常時は `scroll_history()` に流れる
- copy-mode 中は `scroll_history()` に流れる
- `mouse_any_flag` が立っている TUI は wheel passthrough になる
- `alternate_on` だが mouse 非対応の TUI は no-op
- TUI 感度調整の端数が累積される
- TUI を抜けたら感度端数をリセットする

## 今後の調整ポイント

今後チューニングするときは、次の順で触るのが安全。

### 通常スクロールを調整したいとき

- `terminal.html` の `SCROLL_DAMPING_FACTOR`
- `terminal.html` の `MAX_SCROLL_LINES`

### TUI スクロールを調整したいとき

- `pty_manager.py` の `TUI_WHEEL_SENSITIVITY_FACTOR`

### 触ってはいけない方向

- `terminal.html` へ TUI 自動判定を戻す
- gateway transport 層に通常スクロール感度調整を戻す
- Android 側に TUI 判定を持たせる

## まとめ

今回うまくいった理由は、コードを複雑にしたからではなく、**責務の置き場所を正しくしたから** である。

要点を一言で言うと、

- 入力の量はクライアントが扱う
- terminal の意味は tmux 側が扱う

である。

この分離によって、

- 通常スクロールは守られた
- TUI 中に外側が見える問題も解消できた
- TUI 感度だけを独立して調整できるようになった

という状態になった。
