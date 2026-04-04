---
title: EgoGraph Pipelines Service 設計メモ
aliases:
  - Pipelines Service Design
  - Issue 72 Pipelines Design
tags:
  - pipelines
  - ingest
  - compaction
  - local-mirror
  - apscheduler
  - sqlite
status: draft
version: 0.1.0
created: 2026-04-04
updated: 2026-04-04
issue: https://github.com/endo-ava/ego-graph/issues/72
---

# EgoGraph Pipelines Service 設計メモ

## 1. Summary

Issue #72 の目的は、`ingest / compact / local mirror sync` の定期実行責務を
`backend` や GitHub Actions から切り離し、常駐 `pipelines` サービスへ
一元化することである。

このドキュメントでは、まず **ASIS の実装事実** をコード・運用ファイル単位で
整理し、その上で **TOBE の `egograph/pipelines` 設計** を提案する。

---

## 2. Design Goals

### 2.1 Goal

- 収集・加工・保存・compaction・local mirror sync の実行管理を
  1つの常駐サービス境界で扱えるようにする
- `egograph/ingest` を独立コンポーネントとして残さず、
  収集・変換・保存・compaction の実装も `egograph/pipelines` に集約する
- データソースごとに異なるスケジュールを持ちながら、
  実行履歴・失敗理由・リトライ状況・次回起動予定を
  `pipelines` の管理API/CLIで一元的に観測できるようにする
- `backend` の API 可用性と `pipelines` のジョブ実行障害を分離する
- GitHub Actions の `schedule` と `systemd timer` に分散した定期実行責務を
  `pipelines` 内のスケジューリングへ寄せる

### 2.2 Non-Goal

- 汎用ワークフロー基盤や巨大な orchestration platform を作ること
- `backend` と `pipelines` のコード共通化層を新設すること
- すべての data source を1本の巨大 DAG に統合すること
- 初期リリースで分散ワーカーやマルチノード実行を実現すること
- ingest cursor や data lake の正本状態を SQLite に全面移行すること
- `egograph/ingest` を恒久的な第3コンポーネントとして温存すること
- 初期統合スコープに Google Activity / YouTube ingest を含めること

---

## 3. ASIS 実装

この節では、現行実装を **推測ではなく確認できた事実** として整理する。
ファイルパスは観測元を示す。

### 3.1 全体構成 ASIS

```text
[GitHub Actions]
  |- job-ingest-spotify.yml
  |   \- schedule -> spotify ingest -> spotify compact -> verify
  |
  \- job-ingest-github.yml
      \- schedule -> github ingest -> github compact -> verify

[Backend FastAPI]
  |- /v1/ingest/browser-history
  |   \- browser-history ingest -> BackgroundTasks で compact 起動
  |
  \- read APIs
      \- local compacted parquet があれば local mirror を読む
      \- なければ R2 compacted parquet へ fallback

[systemd]
  |- egograph-backend.service
  |   \- ExecStartPre で sync_compacted_parquet を1回実行
  |
  |- egograph-parquet-sync.service
  |   \- sync_compacted_parquet を one-shot 実行
  |
  \- egograph-parquet-sync.timer
      \- 上記 sync service を 6時間ごとに起動

[R2]
  |- raw/
  |- events/
  |- master/
  |- compacted/
  \- state/
```

### 3.2 Spotify ingest / compact ASIS

#### 実行経路

- `.github/workflows/job-ingest-spotify.yml`
  - `schedule` と `workflow_dispatch` を持つ
  - 1つの workflow の中で以下を直列実行する
    1. `uv run python -m egograph.ingest.spotify.main`
    2. `uv run python -m egograph.ingest.spotify.compact`
    3. DuckDB で `compacted/events/spotify/plays`、
       `compacted/master/spotify/tracks`、
       `compacted/master/spotify/artists` を検証
  - 失敗時は `actions/upload-artifact` でログを artifact として保存する

#### スケジュール

- `.github/workflows/job-ingest-spotify.yml`
  - 22:00, 02:00, 06:00, 10:00, 14:00 UTC の5回/day
  - コメント上は JST 07:00, 11:00, 15:00, 19:00, 23:00 に対応
  - 深夜帯を薄くし、日中帯を細かく収集する意図が workflow コメントにある

#### ingest 実装本体

- `egograph/ingest/spotify/main.py`
  - `IngestSettings.load()` で設定を読み、
    `ingest.spotify.pipeline.run_pipeline(config)` を呼ぶ
  - 例外時は `logger.exception("Pipeline failed")` の後 `sys.exit(1)`
- `egograph/ingest/spotify/pipeline.py`
  - Spotify API から recently played を取得
  - Raw JSON を `raw/spotify/recently_played/...` に保存
  - events parquet を `events/spotify/plays/year=YYYY/month=MM/...` に保存
  - track / artist master を `master/spotify/...` に保存
  - ingest cursor は `state/spotify_ingest_state.json` で管理する

#### compact 実装本体

- `egograph/ingest/spotify/compact.py`
  - `--year` と `--month` が指定されない場合は
    `ingest.compaction.resolve_target_months()` の既定範囲で compact 対象月を決める
  - `events/spotify/plays`, `master/spotify/tracks`,
    `master/spotify/artists` の各 dataset について
    `SpotifyStorage.compact_month(...)` を順に呼ぶ
  - 一部 dataset/month が失敗しても最後まで試行し、
    最後に `RuntimeError` で失敗対象をまとめて返す
- `egograph/ingest/spotify/storage.py`
  - `compact_month()` は source parquet 群を読み、
    `ingest.compaction.compact_records()` で dedupe/sort し、
    `compacted/.../year=YYYY/month=MM/data.parquet` に保存する

### 3.3 GitHub ingest / compact ASIS

#### 実行経路

- `.github/workflows/job-ingest-github.yml`
  - `schedule` と `workflow_dispatch` を持つ
  - 1つの workflow の中で以下を直列実行する
    1. `uv run python -m egograph.ingest.github.main`
    2. `uv run python -m egograph.ingest.github.compact`
    3. DuckDB で `compacted/events/github/commits` と
       `compacted/events/github/pull_requests` を検証
  - `GITHUB_PAT` と `GITHUB_LOGIN` が空なら shell で即失敗させる
  - 失敗時は `actions/upload-artifact` でログを artifact として保存する

#### スケジュール

- `.github/workflows/job-ingest-github.yml`
  - 15:00 UTC の1回/day
  - workflow コメント上は JST 00:00

#### ingest 実装本体

- `egograph/ingest/github/main.py`
  - `IngestSettings.load()` で設定を読み、
    `ingest.github.pipeline.run_pipeline(config)` を呼ぶ
  - 例外時は `logger.exception("Pipeline failed")` の後 `sys.exit(1)`
- `egograph/ingest/github/pipeline.py`
  - personal repo の repository / pull request / commit worklog を収集する
  - Raw JSON、events parquet、master parquet を R2 に保存する
  - ingest cursor は `state/github_worklog_ingest_state.json` で管理する

#### compact 実装本体

- `egograph/ingest/github/compact.py`
  - `github/commits` と `github/pull_requests` を対象に月次 compact を行う
  - 一部 dataset/month が失敗しても最後まで試行し、
    最後に `RuntimeError` で失敗対象をまとめて返す
- `egograph/ingest/github/storage.py`
  - `compact_month()` は source parquet 群を読み、
    `compacted/events/github/<dataset>/year=YYYY/month=MM/data.parquet`
    を生成する

### 3.4 Browser History ingest / compact ASIS

Spotify / GitHub と異なり、Browser History は **GitHub Actions ではなく
backend API 経由** で取り込まれる。

#### 実行経路

- `egograph/backend/api/browser_history.py`
  - `POST /v1/ingest/browser-history` で payload を受ける
  - `backend.usecases.browser_history.ingest_browser_history()` を同期実行する
  - ingest 結果に `compaction_targets` があれば、
    FastAPI `BackgroundTasks` で `_trigger_browser_history_compaction()` を
    非同期起動する
- `egograph/backend/usecases/browser_history/ingest_browser_history.py`
  - backend の `R2Config` から `BrowserHistoryStorage` を生成し、
    `ingest.browser_history.pipeline.run_browser_history_pipeline()` を呼ぶ
  - compact は `ingest.browser_history.compaction.compact_browser_history_targets()`
    を呼ぶ

#### ingest 実装本体

- `egograph/ingest/browser_history/pipeline.py`
  - payload を raw JSON と events parquet に保存する
  - `collect_compaction_targets(rows)` で保存行から compact 対象月を計算する
  - `state` は `BrowserHistoryStorage.save_state(...)` で R2 に保存する
  - 戻り値 `BrowserHistoryPipelineResult` に
    `compaction_targets` を含める

#### compact 実装本体

- `egograph/ingest/browser_history/compact.py`
  - CLI から手動 compact できる
  - `--year` と `--month` がない場合は既定対象月を compact する
- `egograph/ingest/browser_history/compaction.py`
  - 同一月の重複 target を除去しながら全 target を試行する
  - 失敗月があれば最後にまとめて例外化する

#### ASIS 上の注意点

- Browser History は `backend` プロセス内から ingest/compact が呼ばれるため、
  Spotify/GitHub と違って **ジョブ障害と API プロセス責務が近い**
- `_trigger_browser_history_compaction()` は例外をログに出すが、
  BackgroundTasks 実行なので **実行履歴・再試行状態の永続管理はない**

### 3.5 Local mirror sync ASIS

#### 実行経路

- `docs/40.deploy/backend.md`
  - `egograph-backend.service` の `ExecStartPre` で
    `uv run python -m backend.scripts.sync_compacted_parquet --root ...`
    を起動前に1回実行する
  - `egograph-parquet-sync.service` が同じ sync script を one-shot 実行する
  - `egograph-parquet-sync.timer` が sync service を6時間ごとに起動する
  - `flock -n /tmp/egograph-sync.lock` で同時 sync を防ぐ

#### sync 実装本体

- `egograph/backend/scripts/sync_compacted_parquet.py`
  - `BackendConfig.from_env()` で R2 設定を読む
  - `COMPACTED_ROOT = "compacted/"` 配下の全 object を list し、
    ローカル `--root` 配下へ同一相対パスで download する
  - 一時ファイル `*.tmp` に落とした後 `os.replace()` で原子的に置換する
  - 個別 object の download に失敗しても `logger.exception(...)` を出して
    次の object へ進む
  - 最後に download 件数を info log 出力する

### 3.6 Backend read path ASIS

- `egograph/backend/infrastructure/database/parquet_paths.py`
  - `LOCAL_PARQUET_ROOT` が設定され、対象 local parquet が存在する場合は
    local mirror の `compacted/...` を読む
  - local file がなければ R2 の `s3://.../compacted/...` を読む
  - dataset 全体 glob も同様に local mirror 優先、存在しなければ R2 fallback
- `docs/40.deploy/backend.md`
  - 「compacted mirror 未同期時に R2 compacted parquet へフォールバックできる」
    という運用前提が明記されている

### 3.7 Google Activity / YouTube ASIS

- `.github/workflows/job-ingest-google-youtube.yml`
  - workflow 全体がコメントアウトされており、現時点で scheduled 実行対象ではない
  - ファイル名と Git history 上も deprecated 扱いである
- `egograph/ingest/google_activity/main.py`
  - ingest 実装は存在するが、Issue #72 の即時移行対象としては
    Spotify/GitHub/local mirror sync ほど運用経路が固まっていない
- TOBE の初期統合対象からは外し、Spotify/GitHub/Browser History/local mirror sync を
  先に `pipelines` へ統合する

### 3.8 ASIS の問題点

#### 1. 定期実行の control plane が分裂している

- Spotify/GitHub ingest+compact は GitHub Actions
- local mirror sync は systemd timer と backend `ExecStartPre`
- Browser History compaction は FastAPI BackgroundTasks

結果として、「いつ、どの順序で、どこが、何を起動したか」を
1つの場所で追いにくい。

#### 2. 実行履歴・再試行・次回予定の永続モデルがない

- GitHub Actions には workflow run history があるが、
  local mirror sync や Browser History BackgroundTasks と統合されていない
- sync script や browser history background compaction は
  SQLite 等の run history を持たない
- 「最後に成功したのはいつか」「次にいつ走るか」
  「どの step が何回 retry されたか」を横断的に API 取得できない

#### 3. ジョブ失敗と API 運用の責務境界が一部混ざっている

- Browser History compaction が `backend` プロセス内 BackgroundTasks で動く
- backend 起動前 sync が `ExecStartPre` に入っており、
  local mirror sync の遅延・失敗が backend 起動シーケンスに影響しうる

#### 4. Workflow 定義が YAML / Python / systemd に分散している

- GitHub Actions YAML に schedule・順序・verify が埋まっている
- ingest CLI は実処理を持つが、workflow 状態や run model を持たない
- sync は backend script + systemd unit/timer に閉じている

#### 5. 観測 API がない

- ジョブの最終成否・実行中 step・失敗ログ・次回予定を
  1か所で確認する pipelines 管理API/CLI が現状ない
- そのため、各実行基盤を個別に見に行く必要がある

---

## 4. TOBE: Pipelines Service 設計

## 4.1 採用方針

`egograph/pipelines` を **backend とは別プロセスの常駐サービス** として新設し、
現行 `egograph/ingest` の収集・変換・保存・compaction 実装を
段階的に `pipelines` 内部へ移管する。

内部は以下の6要素で構成する。

- **Schedule Trigger**
  - APScheduler で cron / interval 発火を管理する
- **Run Dispatcher**
  - `queued` run を SQLite から lease 付きで取得し、
    workflow 定義に沿って実行対象として dispatch する
  - 手動実行、retry、misfire 補正、startup reconcile の run も
    同じ queue から扱う
- **Step Executor**
  - workflow 定義に沿って step を順序実行する
- **Pipeline Modules**
  - provider ごとの collector / transform / storage / compaction を
    `pipelines` 内部モジュールとして持つ
- **State Store**
  - SQLite に workflow 定義、run 履歴、step 履歴、schedule 状態、
    concurrency lock を保存する
- **Management API**
  - FastAPI で状態参照、手動実行、retry、enable/disable を提供する

`pipelines` の運用状態は `pipelines` 自身の Management API と CLI で
直接確認する。`backend` は pipelines 状態参照の責務を持たない。

### 4.2 なぜ APScheduler を使うか

APScheduler は **時刻発火の責務だけ** を任せるために使う。

任せるもの:

- cron / interval trigger
- 次回実行時刻の計算
- プロセス常駐中のジョブ発火
- 発火時に `workflow_runs` を `queued` として enqueue すること

任せないもの:

- workflow DAG / step 依存解決
- step 単位の状態管理
- stdout/stderr ログ保存
- run history API
- 手動 retry / backfill の domain logic
- `queued` run を拾って実行する dispatch / execution loop

この分離により、APScheduler を採用しつつも、
GitHub Actions 的な「workflow run を観測・再実行できる実行モデル」は
`pipelines` 自前の SQLite domain として保持する。
また、Schedule Trigger を enqueue 専用に寄せることで、
manual run / retry / misfire / startup reconcile を
同じ queue 処理で扱えるようにする。

### 4.2.1 再起動・misfire・reconcile 方針

常駐 `pipelines` はプロセス再起動や LXC 再起動がありうるため、
「APScheduler が発火を忘れた/二重発火した」ときの収束ルールを
最初から決めておく。

推奨方針:

- workflow 定義の正本は `pipelines/workflows/registry.py`
- schedule の次回予定や最終発火時刻は SQLite に保存する
- APScheduler は起動時に registry + SQLite から job を再登録する
- APScheduler の発火ハンドラは step を直接実行せず、
  `workflow_runs` を `queued` で追加するだけにする
- 起動直後に `workflow_schedules.next_run_at` と現在時刻を比較し、
  missed run をどう扱うかを workflow 単位の policy で決める
  - `coalesce_latest`: 未実行分を1回に畳んで即時 enqueue
  - `skip_misfire`: 遅れた run を捨てて次回予定だけ更新
- 同一 workflow の二重起動は APScheduler だけに頼らず、
  SQLite の `workflow_locks` で必ず排他する
- `workflow_locks` は単なる固定 TTL ではなく、
  dispatcher / executor が `heartbeat_at` を更新する
  **lease + heartbeat** 方式にする
- stale lock 判定は `lease_expires_at < now()` を基準にし、
  startup reconcile で lock 回収と run/step の収束を行う
- `pipelines` 自身が落ちて再起動した場合、`running` のまま残った
  run/step は startup reconcile で `failed` または `unknown` に
  収束させる

初期 MVP では、Spotify/GitHub/local sync は `coalesce_latest`、
Browser History compact は `skip_misfire` を既定にするのが扱いやすい。

### 4.3 全体構成 TOBE

```text
[Pipelines Service: egograph/pipelines]
  |- APScheduler
  |- Workflow Registry
  |- Run Dispatcher
  |- Step Executor
  |- SQLite
  \- FastAPI Management API

      | dispatch queued runs
      v

  [step execution]
      | run subprocess / call adapters
      v

  [ingest/compact/sync modules]
    |- egograph.pipelines.sources.spotify
    |- egograph.pipelines.sources.github
    |- egograph.pipelines.sources.browser_history
    \- egograph.pipelines.sources.local_mirror_sync

[Backend FastAPI]
  \- read/query/chat APIs

[R2]
  |- raw/events/master/compacted/state

[Local mirror]
  \- compacted/*
```

### 4.4 Service Boundary

#### pipelines が持つ責務

- workflow schedule の管理
- schedule/manual/retry/reconcile/event 由来の run enqueue
- `queued` run の dispatch と lease 管理
- workflow run / step run の生成と状態遷移
- 実行中排他、timeout、retry policy の適用
- step stdout/stderr と終了コードの保存
- 最終成功時刻・次回予定時刻・失敗理由の提供
- 手動 trigger / retry / enable-disable API
- local mirror sync の定期実行

#### backend が持つ責務

- データ読み取り・チャット向け API
- R2/local mirror からの読み取りクエリ

#### 現行 ingest 実装の扱い

- TOBE では `egograph/ingest` を独立コンポーネントとして残さない
- provider API からの収集、変換、R2 保存、compaction、
  R2 上の ingest cursor/state 更新は `pipelines` の内部責務へ移す
- ただし一括移行で壊さないため、初期 Phase では
  現行 `egograph/ingest/*` 実装を `pipelines` から呼び出し、
  その後 `pipelines/sources/*` へ物理移動して `egograph/ingest` を廃止する

#### systemd が持つ責務

- `egograph-pipelines.service` と `egograph-backend.service` の
  プロセス起動・自動再起動
- **timer によるジョブスケジューリングは原則持たない**

#### systemd unit の依存関係ルール

- `backend` は `pipelines` 停止中でも API として起動できる必要があるため、
  `egograph-backend.service` から `egograph-pipelines.service` への
  hard dependency は張らない
- `pipelines` はネットワークと R2/API への疎通が必要なので、
  `After=network-online.target` を付ける

### 4.5 Workflow Design

ASIS のデータソースごとの実行時刻がバラバラでも問題ないため、
TOBE でも **ソース別 workflow** を基本単位にする。

#### 4.5.1 Workflow examples

```text
spotify_ingest_workflow
  schedule:
    cron:
      - "0 22 * * *"
      - "0 2 * * *"
      - "0 6 * * *"
      - "0 10 * * *"
      - "0 14 * * *"
  steps:
    - run_spotify_ingest
    - run_spotify_compact

github_ingest_workflow
  schedule:
    cron:
      - "0 15 * * *"
  steps:
    - run_github_ingest
    - run_github_compact

local_mirror_sync_workflow
  schedule:
    interval: "6h"
  steps:
    - run_local_mirror_sync
```

#### 4.5.2 なぜ巨大 DAG にしないか

- Spotify / GitHub / Browser History は収集タイミングが一致しなくてよい
- 1つの巨大 workflow にすると、
  どれか1ソースの遅延・失敗が他ソースの運用観測を巻き込みやすい
- local mirror sync も「各 compact 完了直後に必ず同期」より、
  ASIS の 6h timer 相当をまず維持した独立 workflow の方が
  移行リスクが低い

ただし将来、必要なら `local_mirror_sync_workflow` を
特定 workflow 成功後に event-driven trigger する拡張は可能にしておく。

#### 4.5.3 event enqueue の扱い

Browser History 受信直後の compact や、将来の workflow 成功後 trigger は、
APScheduler と同じ `workflow_runs` queue に **event enqueue** として積む。
これにより、「いつ起動したか」だけでなく
「なぜ queue に積まれたか」を run 履歴から追えるようにする。

### 4.6 Workflow Definition Source

`shared` 層を増やさない前提のため、workflow 定義は
**`egograph/pipelines` 内の Python registry** として持つ方針を推奨する。

例:

```python
WORKFLOWS = [
    WorkflowDefinition(
        id="spotify_ingest_workflow",
        triggers=[CronTriggerSpec("0 22 * * *"), ...],
        steps=[
            StepDefinition(id="run_spotify_ingest", command=[...]),
            StepDefinition(id="run_spotify_compact", command=[...]),
        ],
        concurrency_key="spotify_ingest_workflow",
        timeout_seconds=1800,
    ),
]
```

この方式の利点:

- YAML と domain model の二重管理を避けやすい
- workflow 定義を Git 管理できる
- 「cron は SQLite に直書き」よりレビューしやすい
- DB には workflow run-time state だけを置き、
  workflow 定義の正本は Python registry に固定できる

### 4.7 Execution Model

#### 推奨: 初期は subprocess 実行、移管後は in-process 実行へ寄せる

移行初期の各 step はまず `uv run python -m ...` 相当を
**subprocess** として実行する。

理由:

- 既存の ingest / compact CLI を壊さず再利用しやすい
- step ごとに exit code / stdout / stderr を明確に分離できる
- Python 関数直呼びより、ジョブ失敗が pipelines プロセスへ
  波及しにくい
- 将来、一部 step を別言語 CLI や外部バイナリへ置き換えやすい

ただし `egograph/ingest` を廃止して `pipelines` へ統合する最終形では、
同一プロセス内の pipeline 関数を直接呼ぶ **in-process step** を
第一候補にする。これにより「ジョブ実行基盤」と「データ処理実装」が
1コンポーネント内で完結し、パッケージ境界が増えない。

#### subprocess から in-process へ切り替える条件

provider ごとの step を in-process 化するのは、
単にコード移動が終わった時点ではなく、以下を満たした段階に限定する。

- 対象 provider の ingest / compact 実装が
  `egograph.pipelines.sources.<provider>` に物理移動済み
- CLI entrypoint だけでなく、workflow step から直接呼べる
  明示的な Python 関数 API がある
- step の戻り値、例外、timeout、ログ出力の扱いが
  `subprocess_executor` と同等に観測できる
- その provider の integration test が subprocess 実行と
  in-process 実行の両方で通っている

この条件を満たすまでは、無理に in-process 化せず subprocess を維持する。

#### Browser History 受信 API も pipelines に移す

Browser History は ASIS で backend API が受信入口になっているが、
TOBE では **受信 API も `pipelines` に移し、書き込み系入口を pipelines に統一する**。

移行方式は **Browser History 受信 API を `pipelines` に新設し、
拡張機能/クライアントは `pipelines` を直接叩く** 方式に固定する。
`backend` 側の既存 `/v1/ingest/browser-history` は移行完了後に削除する。

レビュー提案として「移行期間だけ backend proxy 互換を許容する」案もあるが、
この設計では採用しない。
後方互換のためだけに proxy 層を挟むと、
書き込み責務を `pipelines` に寄せる境界がまた曖昧になるためである。

### 4.8 SQLite State Model

SQLite は **運用管理メタデータ** を保存し、
R2 は **データ処理チェックポイントと成果物** を保持する。

つまり ASIS の `state/spotify_ingest_state.json` や
`state/github_worklog_ingest_state.json` は当面 R2 のまま維持し、
SQLite には workflow 実行管理だけを置く。

#### 4.8.0 Secrets 方針

- R2 access key、Spotify refresh token、GitHub PAT などの secrets は
  **SQLite に保存しない**
- `pipelines` プロセスの環境変数または systemd `EnvironmentFile` から
  実行時に読む
- step command や API response に secret 値を含めない
- `step_runs.command` には secret 展開前の論理コマンドか、
  secret をマスクした表示用 command を保存する

#### 4.8.1 Tables

```text
workflow_definitions
  - workflow_id
  - name
  - description
  - enabled
  - definition_version
  - created_at
  - updated_at

workflow_schedules
  - schedule_id
  - workflow_id
  - trigger_type        # cron / interval
  - trigger_expr
  - timezone
  - next_run_at
  - last_scheduled_at

workflow_runs
  - run_id
  - workflow_id
  - trigger_type        # schedule / manual / retry / event / reconcile
  - queued_reason       # schedule_tick / manual_request / retry_request / startup_reconcile / event_enqueue
  - status              # queued / running / succeeded / failed / canceled
  - scheduled_at
  - queued_at
  - started_at
  - finished_at
  - last_error_message
  - requested_by        # system / api
  - parent_run_id       # retry 元
  - result_summary_json

step_runs
  - step_run_id
  - run_id
  - step_id
  - step_name
  - sequence_no
  - attempt_no
  - command
  - status              # queued / running / succeeded / failed / skipped
  - started_at
  - finished_at
  - exit_code
  - stdout_tail
  - stderr_tail
  - log_path
  - result_summary_json

workflow_locks
  - lock_key
  - run_id
  - lease_owner
  - acquired_at
  - heartbeat_at
  - lease_expires_at
```

`trigger_type` は schedule/manual/retry/event/reconcile のような
**run の起動経路の大分類** を表し、
`queued_reason` は `event_enqueue` や `startup_reconcile` のような
**なぜその run が queue に積まれたかの詳細理由** を表す。

#### 4.8.2 状態遷移

workflow run:

```text
queued -> running -> succeeded
                  -> failed
                  -> canceled
```

step run:

```text
queued -> running -> succeeded
                  -> failed
                  -> skipped
```

初期版では step は **直列実行** を前提にし、
前 step が failed になったら後続 step は skipped にする。
将来 DAG を入れる場合も、まず `sequence_no` と直列前提を明示した上で、
`depends_on_step_ids` を後から追加できる形にする。

### 4.9 Retry / Concurrency / Timeout

#### Retry

- schedule 発火 run が失敗したら、自動 retry 回数と delay を
  workflow 単位または step 単位で持つ
- 手動 retry API では `parent_run_id` を埋めた新規 run を作る
- step 単位 retry を観測できるように、
  `step_runs.attempt_no` を 1 始まりで記録する
  - 同一 run 内で同じ step を再試行する場合は `attempt_no` を増やす
  - workflow 全体の手動 retry は新規 `workflow_runs` を作り、
    `parent_run_id` で元 run と紐づける
- ingest cursor は R2 にあるため、同じ workflow を再実行しても
  各 ingest 実装の冪等性に乗せて再開する

#### Concurrency

- 同一 workflow の多重起動は `concurrency_key` と `workflow_locks` で防ぐ
- `local_mirror_sync_workflow` も ASIS の `flock` 相当を
  DB lock + 必要なら process lock で表現する
- `workflow_locks` は lease + heartbeat 方式にし、
  lock を取った dispatcher / executor が周期的に heartbeat を更新する
- heartbeat が止まって `lease_expires_at` を超えた lock は stale とみなし、
  startup reconcile または maintenance reconcile で回収する

#### Timeout

- workflow 全体 timeout と step timeout を分けて持つ
- subprocess 実行が timeout したら process group を kill し、
  step/run を failed にする

### 4.10 Logging / Observability

#### 保存するもの

- workflow run の開始・終了・trigger種別・`queued_reason`・最終ステータス
- step run の command・exit code・開始終了時刻・`stdout_tail` / `stderr_tail`
- ログ本文はローカルファイルに保存し、SQLite には `log_path` と tail だけ持つ
- step が構造化した実行結果を持てる場合は
  `result_summary_json` に軽量 summary を保存する

#### ログ保存方針

- 保存先:
  - ローカルファイル例:
    `data/pipelines/logs/{workflow_id}/{run_id}/{step_id}.log`
  - SQLite の `step_runs` には `log_path`, `stdout_tail`, `stderr_tail` を保存する
- API/CLI の見せ方:
  - run 一覧/詳細は SQLite のメタデータと tail で即確認できるようにする
  - 必要なときだけ `log_path` の本文を読むログ本文取得 API/CLI を用意する
- ローテーション:
  - log file retention と run metadata retention は分けて扱う
  - 古い run log / run metadata を整理する
    pipelines maintenance workflow を別途持つ
  - 初期値の第一候補:
    - log files: 30日より古いものを削除
    - step_runs: 90日保持
    - workflow_runs: 180日保持
  - もし workflow_runs を長期に残したくなった場合は、
    全量ログではなく summary 行だけを残す方向で圧縮保持を検討する
- 非採用:
  - MVP ではログ本文を SQLite に全量保存しない
  - MVP ではログ本文の R2 退避も持たない

#### 管理API案

```text
GET  /v1/workflows
GET  /v1/workflows/{workflow_id}
GET  /v1/workflows/{workflow_id}/runs
POST /v1/workflows/{workflow_id}/runs

GET  /v1/runs
GET  /v1/runs/{run_id}
GET  /v1/runs/{run_id}/steps/{step_id}/log
POST /v1/runs/{run_id}/retry
POST /v1/runs/{run_id}/cancel

GET  /v1/health
```

#### CLI 案

```text
uv run python -m pipelines.main serve
uv run python -m pipelines.main workflow list [--json]
uv run python -m pipelines.main workflow run <workflow_id> [--json]
uv run python -m pipelines.main run list [--json]
uv run python -m pipelines.main run show <run_id> [--json]
uv run python -m pipelines.main run log <run_id> <step_id>
uv run python -m pipelines.main run retry <run_id> [--json]
uv run python -m pipelines.main run cancel <run_id> [--json]
```

運用確認は **CLI 主導** とし、エージェントが直接状態取得・失敗調査・
手動再実行を行えるように、主要コマンドは `--json` 出力を必須対応する。
Management API は同じ usecase を HTTP でも呼べる薄い公開面として持つが、
MVP の主導線は CLI とする。
`backend` 経由の監視UI/APIは MVP に含めない。

### 4.11 Local Mirror Sync の TOBE

ASIS の `backend/scripts/sync_compacted_parquet.py` は
`pipelines` 管轄へ移す。

推奨方針:

- 実体コマンドを `egograph.pipelines.sources.local_mirror_sync` などへ移す
- `local_mirror_sync_workflow` の1 step として schedule 実行する
- backend 起動前 `ExecStartPre` からは sync を外し、
  backend は local mirror が無ければ従来どおり R2 fallback で起動する
- どうしても起動直後の local mirror warmup が欲しい場合は、
  `pipelines` 起動時に `local_mirror_sync_workflow` を一度 enqueue する
- `run_local_mirror_sync` step の `result_summary_json` には、
  最低限以下を保存する
  - `target_prefix`: 同期対象 prefix。まずは `compacted/`
  - `downloaded_count`: ダウンロード件数
  - `skipped_count`: 変更なし等でスキップした件数
  - `failed_count`: 失敗件数
  - `failed_keys_sample`: 調査用の失敗 object key サンプル
  - `last_success_at`: 直近成功時刻

この summary を `run show --json` や run detail API で返せるようにしておくと、
「同期されているはずなのに backend から読まれていない」系の調査を
`pipelines` 側だけでかなり絞り込める。

### 4.12 Browser History Compaction の TOBE

ASIS の `backend` 受信 API と `BackgroundTasks` compaction は
どちらも `pipelines` に移す。

推奨案:

- `pipelines` が `POST /v1/ingest/browser-history` 相当の受信 API を持つ
- 受信 API は payload を raw/events/state へ保存し、
  `compaction_targets` を `browser_history_compact_workflow` として即 enqueue する
- 取りこぼし補正として、短い interval で直近月・前月を compact する
  `browser_history_compact_maintenance_workflow` も別途回す
- `backend` は Browser History の書き込み API を持たず、
  読み取り API だけを担当する

この方式なら Browser History も Spotify/GitHub/local sync と同じ
実行・観測面に統一でき、`backend` の責務が読み取り側に寄る。

#### 現行実装との対応

- 現行の自動実行は `backend` の `BackgroundTasks` による即時 compact のみで、
  定期補正ジョブはない
- 一方で `egograph/ingest/browser_history/compact.py` は引数なし実行時に
  `resolve_target_months()` を通じて **前月+当月** を compact 対象にする
- TOBE の `browser_history_compact_maintenance_workflow` は、この既存の
  前月+当月補正ロジックを定期実行へ昇格させる位置づけとする

---

## 5. Alternative Designs

### 5.1 案1: APScheduler + SQLite + subprocess workflow executor

このドキュメントの推奨案。

Pros:

- 常駐 `pipelines` に運用責務を集約しやすい
- APScheduler で cron/interval を素直に表現できる
- SQLite で run history と監視APIを作りやすい
- 既存 ingest/compact CLI を subprocess で再利用しやすい
- Schedule Trigger / Run Dispatcher / Step Executor を
  同一プロセス内でも論理分離しやすい
- systemd timer と GitHub Actions schedule を減らせる

Cons:

- workflow run / step run / lock / retry の domain model は
  自前で実装する必要がある
- APScheduler job store と自前 SQLite domain store の境界設計を
  誤ると二重状態になりやすい

### 5.2 案2: schedule は APScheduler、自動実行だけ担当し、
run history はログファイル中心で薄く持つ

Pros:

- 初期実装は軽い
- SQLite schema を小さくできる

Cons:

- `pipelines` の CLI/API から run/step 状態を構造化して見たい、
  という要件に弱い
- 最終成否・step状態・retry履歴を構造化 API 化しづらい
- 結局あとで案1に寄せる可能性が高い

### 5.3 案3: FastAPI backend に APScheduler を同居させる

Pros:

- サービス数が増えない
- backend から pipelines 状態を直接扱いやすい

Cons:

- API 可用性とジョブ実行障害が再結合しやすい
- Browser History BackgroundTasks の問題を別形で持ち込みやすい
- Issue #72 の「backend から jobs/scheduler を分離する」
  方向と逆行しやすい

よって **案1を推奨** する。

---

## 6. Proposed Package Layout

`shared` 層は作らず、TOBE の Python パッケージは
`backend` と `pipelines` の2つへ整理する。
`egograph/ingest` は移行完了後に削除する。

```text
egograph/
  backend/
  pipelines/
    __init__.py
    main.py                  # FastAPI + APScheduler 起動
    config.py                # pipelines 自身の設定
    api/
      __init__.py
      health.py
      workflows.py
      runs.py
    domain/
      workflow.py            # WorkflowDefinition / Run / StepRun
      schedule.py
      errors.py
    infrastructure/
      db/
        connection.py        # SQLite 接続
        schema.py
        repositories.py
      scheduling/
        apscheduler_app.py   # APScheduler 初期化・job同期
      dispatching/
        run_dispatcher.py    # queued run の lease 取得・dispatch
        lock_manager.py      # workflow_locks の lease/heartbeat 管理
      execution/
        subprocess_executor.py
        inprocess_executor.py
        log_store.py
      object_storage/
        r2_client.py
    workflows/
      registry.py            # workflow 定義
      builtin/
        spotify.py
        github.py
        browser_history.py
        local_mirror_sync.py
    sources/
      common/
        compaction.py
        settings.py
      spotify/
        collector.py
        transform.py
        storage.py
        pipeline.py
        compact.py
      github/
        collector.py
        transform.py
        storage.py
        pipeline.py
        compact.py
      browser_history/
        transform.py
        storage.py
        pipeline.py
        compact.py
      local_mirror_sync/
        pipeline.py
    tests/
```

### 6.1 Workspace 登録

`egograph/pipelines` を追加するだけでは `uv sync --all-packages` や pytest 対象に
自動で入らないため、root workspace 設定も同時に更新する。

更新対象:

- `pyproject.toml`
  - `[tool.uv.workspace].members` に `egograph/pipelines` を追加する
  - `[tool.pytest.ini_options].testpaths` に
    `egograph/pipelines/tests` を追加する
- `egograph/pipelines/pyproject.toml`
  - `project.dependencies` に `apscheduler`, `fastapi`, `uvicorn`, `pydantic`
    など pipelines 実行に必要な依存を定義する
  - 既存 package と同様に `dev-mode-dirs = [".."]` を使い、
    monorepo 内 import 境界を合わせる

この更新を Migration Plan の Phase 1 に含めないと、
サービス追加後に最初の `uv sync` / test discovery で詰まりやすい。

### 設計ルール

- `pipelines` から `backend` の内部 module を import しない
- `backend` も `pipelines` の SQLite schema を直接参照しない
- 連携境界は HTTP API と環境変数だけにする
- ingest cursor/state の正本は R2 のまま維持する
- workflow 定義はまず `pipelines/workflows/registry.py` で Git 管理し、
  DB は run-time state を中心に持つ

---

## 7. Migration Plan

### Phase 1: Pipelines service の MVP を追加

- `egograph/pipelines` を新設
- root `pyproject.toml` と `egograph/pipelines/pyproject.toml` を更新し、
  `uv workspace` と pytest 対象に pipelines package を追加する
- APScheduler + SQLite + FastAPI 管理APIを立ち上げる
- APScheduler は enqueue 専用にし、`queued` run を拾う
  Run Dispatcher と Step Executor を分けて実装する
- `spotify_ingest_workflow`, `github_ingest_workflow`,
  `local_mirror_sync_workflow` を固定定義で実装する
- Google Activity / YouTube は初期 workflow に含めない
- step はまず現行 `egograph.ingest.*` CLI の subprocess 実行にし、
  stdout/stderr と exit code を保存する
- startup reconcile と misfire policy を実装する
- `workflow_locks` は lease + heartbeat 方式で実装する
- systemd は `egograph-pipelines.service` の常駐起動だけを担う

### Phase 2: GitHub Actions schedule / systemd timer を pipelines へ移行

- `.github/workflows/job-ingest-spotify.yml` と
  `.github/workflows/job-ingest-github.yml` の `schedule` を止める
  または手動 fallback 専用に縮退させる
- `egograph-parquet-sync.timer` を廃止し、
  `local_mirror_sync_workflow` に寄せる
- `egograph-backend.service` の `ExecStartPre` sync を外す

### Phase 3: ingest 実装を pipelines 内部へ統合

- provider ごとに `egograph/ingest/<provider>` を
  `egograph/pipelines/sources/<provider>` へ段階移管する
- 各 provider の移管が完了したら、その provider の workflow step を
  subprocess CLI 呼び出しから `pipelines.sources.*` の
  in-process 関数呼び出しへ切り替える
- in-process 化は、対象 provider の関数 API / 例外設計 / ログ観測 /
  integration test が揃った step から順に行い、
  条件未達の step は subprocess のまま維持する
- 移管済み provider の `egograph/ingest/<provider>` はその場で削除し、
  旧実装を長く併存させない
- 最後に `egograph/ingest/compaction.py` と `egograph/ingest/settings.py` を
  `egograph/pipelines/sources/common/*` へ移し、`egograph/ingest` package を削除する
- `egograph/ingest` package 削除後は、
  root `pyproject.toml` の workspace members からも外す

### Phase 4: Browser History 受信 API / compaction を pipelines へ移行

- `pipelines` に Browser History 受信 API を追加する
- クライアント/拡張機能の送信先を `pipelines` に切り替える
- 移行期間の backend proxy 互換は原則入れず、
  送信先切り替えと backend 旧エンドポイント削除を同じ移行作業として扱う
- `browser_history_compact_workflow` と
  `browser_history_compact_maintenance_workflow` を pipelines に追加する
- `browser_history_compact_workflow` は受信直後の即時 compact、
  `browser_history_compact_maintenance_workflow` は前月+当月の定期補正を担う
- `backend` の `/v1/ingest/browser-history` と BackgroundTasks compaction を削除する
- UI/API から browser history compaction 失敗も
  他 workflow と同じ run 履歴で追えるようにする

### Phase 5: Pipelines 管理API/CLI を運用向けに仕上げる

- workflow/run 一覧、詳細、ログ参照、手動実行、retry、cancel を
  `pipelines` の CLI 主導で完結させ、主要コマンドは `--json` を持たせる
- Management API は CLI と同じ usecase を薄く公開する形で揃える
- 必要なら将来の別 Issue で dashboard/UI を検討するが、
  その場合も `pipelines` API を正本にする

---

## 8. Open Questions

- なし

---

## 9. Current Recommendation

現時点の推奨は以下。

- サービス名は `pipelines`
- `backend` とは別プロセス常駐
- 最終的な Python コンポーネントは `backend` + `pipelines` の2つにし、
  `egograph/ingest` は `pipelines` へ吸収して廃止する
- APScheduler は trigger 発火に限定して採用
- Schedule Trigger は enqueue 専用、Run Dispatcher / Step Executor は
  別責務として論理分離する
- workflow/run/step/lock/history は SQLite で自前管理
- `queued_reason`, `step_runs.attempt_no`,
  lease/heartbeat 付き `workflow_locks`,
  local mirror sync の `result_summary_json` を run model に持たせる
- step 実行は移行初期 subprocess、統合後は in-process を主軸にする
- subprocess から in-process への切り替え条件を provider 単位で明文化し、
  条件未達なら subprocess を維持する
- workflow 単位はソース別 + local mirror sync 独立
- ingest cursor は R2 state のまま維持
- log file retention と run metadata retention は分離し、
  初期値は logs 30日 / step_runs 90日 / workflow_runs 180日 を第一候補にする
- pipelines の監視・手動操作は pipelines 自身の API/CLI で完結させ、
  backend は読み取り/チャット API に集中する
- `shared` package は作らない

この構成なら、ASIS の分散した運用制御を1か所に寄せながら、
既存 ingest 実装と R2 state 設計を大きく壊さず段階移行できる。
