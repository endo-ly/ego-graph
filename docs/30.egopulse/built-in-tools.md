# EgoPulse Built-in Tools

現在の `egopulse` に実装されている built-in tools の一覧と仕様。  

## 参考元

- `pi-mono` repository
  - https://github.com/badlogic/pi-mono
- `coding-agent` README
  - https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/README.md
- built-in tools 実装ディレクトリ
  - https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/src/core/tools

## 前提

- 実装本体: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs)
- workspace ルート: `~/.egopulse/workspace`
- skills ルート: `~/.egopulse/workspace/skills`
- path 解決は workspace 配下に制限される
- tool 実行結果は turn loop で `{"tool":"...","status":"success|error","result":"..."}` の JSON に包まれて LLM に返る

## Tool Registry

現在 registry に登録されている tool は次の 8 つ。

- `read`
- `bash`
- `edit`
- `write`
- `grep`
- `find`
- `ls`
- `activate_skill`

登録箇所: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:64)

## `read`

- 目的: ファイル内容を読む
- 入力:
  - `path: string` 必須
  - `offset: integer` 任意。1-indexed
  - `limit: integer` 任意。最大行数
- 挙動:
  - workspace 配下の path のみ読める
  - UTF-8 テキストのみ対応
  - 出力は最大 `2000` 行または `50KB`
  - 続きがある場合は `offset=...` の continuation hint を返す
- 主な失敗:
  - `Missing required parameter: path`
  - `File not found: ...`
  - `Offset ... is beyond end of file`
  - `Only UTF-8 text files are supported by read in egopulse right now.`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:219)

## `write`

- 目的: ファイルを新規作成または上書きする
- 入力:
  - `path: string` 必須
  - `content: string` 必須
- 挙動:
  - workspace 配下の path のみ書ける
  - 親ディレクトリは自動作成
  - 既存ファイルは上書き
- 成功時:
  - `Successfully wrote <path>`
- 主な失敗:
  - `Missing required parameter: path`
  - `Missing required parameter: content`
  - `Failed to create directories: ...`
  - `Failed to write file: ...`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:361)

## `edit`

- 目的: 既存ファイルの exact text replacement
- 入力:
  - `path: string` 必須
  - `edits: array` 必須
  - 各 edit は:
    - `oldText: string`
    - `newText: string`
- 挙動:
  - すべて original file に対してマッチする
  - `oldText` は各 edit ごとに 1 回だけ一致する必要がある
  - overlapping edit は拒否
  - BOM と CRLF を保存する
- 成功時:
  - `Successfully replaced N block(s) in <path>.`
- 主な失敗:
  - `Missing required parameter: path`
  - `Edit tool input is invalid. edits must contain at least one replacement.`
  - `Each edit must include oldText`
  - `Each edit must include newText`
  - `File not found: ...`
  - `oldText not found in file. Make sure it matches exactly.`
  - `oldText found N times in file. It must be unique.`
  - `Edit ranges overlap. Merge nearby changes into one edit instead.`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:433)

## `bash`

- 目的: workspace を cwd にして bash command を実行する
- 入力:
  - `command: string` 必須
  - `timeout: integer` 任意。秒
- 挙動:
  - `bash -lc <command>` で実行
  - stdout / stderr を結合して返す
  - 出力は末尾側を最大 `2000` 行または `50KB` に truncation
  - 終了コードが非 0 の場合は error 扱い
- 成功時:
  - command output
  - output が空なら `(no output)`
- 主な失敗:
  - `Missing required parameter: command`
  - `Failed to execute bash command: ...`
  - `Command timed out after N seconds`
  - `Command exited with code N`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:549)

## `grep`

- 目的: file contents を検索する
- 入力:
  - `pattern: string` 必須
  - `path: string` 任意。既定値 `.`
  - `glob: string` 任意
  - `ignoreCase: boolean` 任意
  - `literal: boolean` 任意
  - `context: integer` 任意
  - `limit: integer` 任意。既定値 `100`
- 挙動:
  - `rg` を使用
  - workspace 配下の path のみ検索
  - 1 行は最大 `500` 文字に短縮
  - 結果全体は `50KB` で truncation
  - マッチ 0 件は success 扱いで `No matches found.`
- 主な失敗:
  - `Missing required parameter: pattern`
  - `Path not found: ...`
  - `ripgrep (rg) is not available. Install rg to use grep.`
  - `Search failed: ...`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:644)

## `find`

- 目的: glob pattern でファイルを探す
- 入力:
  - `pattern: string` 必須
  - `path: string` 任意。既定値 `.`
  - `limit: integer` 任意。既定値 `1000`
- 挙動:
  - `fd` を使用
  - workspace 配下の path のみ検索
  - 結果が空なら `No files found matching pattern`
  - 結果全体は `50KB` で truncation
- 主な失敗:
  - `Missing required parameter: pattern`
  - `Path not found: ...`
  - `fd is not available. Install fd to use find.`
  - `Search failed: ...`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:786)

## `ls`

- 目的: directory contents を一覧する
- 入力:
  - `path: string` 任意。既定値 `.`
  - `limit: integer` 任意。既定値 `500`
- 挙動:
  - workspace 配下の path のみ一覧
  - ディレクトリは `/` suffix を付ける
  - dotfiles を含む
  - 空 directory は `(empty directory)`
  - 結果全体は `50KB` で truncation
- 主な失敗:
  - `Path not found: ...`
  - `Not a directory: ...`
  - `Cannot read directory: ...`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:905)

## `activate_skill`

- 目的: 発見済み skill の本文をロードする
- 入力:
  - `skill_name: string` 必須
- 挙動:
  - `SkillManager::load_skill_checked()` を呼ぶ
  - 返り値には skill name、description、skill directory、instructions 本文を含む
- 主な失敗:
  - `Missing required parameter: skill_name`
  - `Skill '<name>' not found. ...`
  - `failed to read skill '<name>': ...`

実装: [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:1066)

## Skill Catalog

`activate_skill` とは別に、各 turn の system prompt には skill の概要一覧が入る。

- catalog 生成: [skills.rs](/root/workspace/ego-graph-issue106/egopulse/src/skills.rs:101) `build_skills_catalog()`
- prompt への埋め込み: [turn.rs](/root/workspace/ego-graph-issue106/egopulse/src/agent_loop/turn.rs:246)

つまり skill 本文は初期ロードされず、最初に入るのは概要一覧だけ。

## Path and Directory Rules

- workspace root:
  - [config.rs](/root/workspace/ego-graph-issue106/egopulse/src/config.rs:207)
  - `~/.egopulse/workspace`
- skills root:
  - [config.rs](/root/workspace/ego-graph-issue106/egopulse/src/config.rs:203)
  - `~/.egopulse/workspace/skills`
- path guard:
  - [tools.rs](/root/workspace/ego-graph-issue106/egopulse/src/tools.rs:1229)
  - `..` で workspace 外へ出る path は拒否する
