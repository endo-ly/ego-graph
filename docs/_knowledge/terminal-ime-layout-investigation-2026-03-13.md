# Terminal IME Issues (2026-03-13)

## 1. terminal が潰れる問題

### 症状

- terminal 表示領域が小さいときに見た目が崩れる
- 履歴が大量にあるときは問題が出にくい
- 履歴が少ないときに悪化しやすい

### 今回やったこと

- `MIN_ROWS` を `12` から `1` に下げた
- terminal 全体の `translateY` による持ち上げを試した
- viewport 末尾の scroll 逃がしを試した
- `xterm-scroll-area` に下 padding を入れて scroll range を増やす方式を試した

### まだ直っていない理由の仮説

- 本命は `MIN_ROWS` ではなく、履歴が少ないときに「末尾を上へ逃がすための scroll range」が足りないこと
- `scrollToBottom()` だけでは履歴が少ないケースで逃がし量を作れない
- `xterm-scroll-area` / `xterm-viewport` のどちらに、どのタイミングで余白を入れるべきかがまだ合っていない可能性が高い
- edge-to-edge + WebView + IME の組み合わせで、見えている高さと xterm が計算している高さがずれている可能性がある

## 2. terminal 末尾フォーカスが足りない問題

### 症状

- キーボード表示時に terminal の末尾へ十分にフォーカスされない
- `special keys` が出る前提で見ると、末尾がまだ下すぎる
- 実質的には「末尾にフォーカス」ではなく、「末尾付近がまだ隠れる」状態

### 今回やったこと

- keyboard 表示時に `focusInputAtBottom()` を呼ぶ実装を複数回調整した
- `scrollToBottom()` のあとに offset 分だけ戻す実装を試した
- `special keys` の実測高さと keyboard 高さを足して、terminal 側へ下余白を渡す実装を試した

### まだ直っていない理由の仮説

- `scrollToBottom()` 後に少し戻す方式は、本当の意味での「末尾フォーカス」ではなかった
- 末尾を上へ逃がすための scroll range 自体が足りないと、どれだけ focus を呼んでも十分上へ来ない
- `special keys` の高さを考慮する方向自体は合っているが、terminal 側でその余白が実際の scroll 余地として効いていない可能性が高い
- `rememberKeyboardState()` の可視判定が粗く、IME 状態と terminal 側の処理タイミングがずれている可能性がある

## 次に見るべき点

- `xterm-viewport.clientHeight`
- `xterm-viewport.scrollHeight`
- `xterm-viewport.scrollTop`
- `xterm-scroll-area` への padding が実際に効いているか
- 履歴が少ないケースと多いケースでの差分
