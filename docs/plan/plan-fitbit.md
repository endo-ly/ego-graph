# Google Health / Fitbit Air Integration Phase Plan

## 1. Purpose

本資料は、Google Fitbit Airで取得される健康・活動・睡眠データを、Google Health API経由でEgoGraphへ取り込む実装作業を3フェーズに分割するための計画書である。

実装対象の詳細仕様は、別紙 `Google Health / Fitbit Air Integration Implementation Specification` を正本とする。
本資料では、各フェーズの目的、スコープ、成果物、Definition of Doneを定義する。

---

## 2. Phase Overview

| Phase   | 名称                            | 主目的                                       | 完了時の状態                                            |
| ------- | ----------------------------- | ----------------------------------------- | ------------------------------------------------- |
| Phase 1 | Connection Foundation         | Google Health APIへ安全に接続できる基盤を作る           | OAuth接続、token保存、token refresh、API clientの最小疎通ができる |
| Phase 2 | Ingestion and Storage         | Fitbit Air由来データを取得し、Raw JSONとParquetへ保存する | backfill/range実行により対象データを保存できる                    |
| Phase 3 | Scheduled Operation and Query | 定期取得・repair・DuckDB分析までつなげる                | Schedulerで継続取得され、DuckDBから日次サマリを参照できる              |

3フェーズの考え方は以下である。

```txt
Phase 1: つながる
Phase 2: 取って保存できる
Phase 3: 運用・分析できる
```

これ以上細かく分けると、認証だけ、Rawだけ、Parquetだけのような中途半端な完成点が増えやすい。
そのため、PRや作業単位は3つにまとめ、各Phase内部の実装タスクを小さく刻む。

---

## 3. Common Principles

全フェーズで以下を守る。

| 原則              | 内容                                                   |
| --------------- | ---------------------------------------------------- |
| CLIを追加しない       | 操作はPipelines ServiceのAPIとSchedulerに寄せる               |
| Tailscale依存にしない | OAuth callbackの公開方式は環境変数で切り替える                       |
| tokenをログに出さない   | access token、refresh token、authorization codeはログ出力禁止 |
| Raw JSONを保存する   | APIレスポンスの再処理・監査・normalizer修正に備える                     |
| Parquetを分析正本にする | DuckDBで読む正規化データはParquetに保存する                         |
| SQLiteは状態管理に使う  | token、connection、cursor、workflow run状態を保存する          |
| 欠損をエラー扱いしない     | Fitbit Airで値が返らない日は `no_data` として扱う                  |
| 再取得可能にする        | 同じ期間を再実行しても破綻しない設計にする                                |

---

# Phase 1: Connection Foundation

## 4. Objective

Google Health APIとEgoGraphを接続するための認証・接続基盤を作る。

このPhaseでは、健康データの本格取得やParquet保存までは扱わない。
目的は、Google OAuth2によって接続し、refresh tokenを保存し、Pipelines ServiceからGoogle Health APIを継続的に呼べる状態を作ることである。

---

## 5. Scope

### 5.1 In Scope

| 項目                   | 内容                                          |
| -------------------- | ------------------------------------------- |
| config追加             | Google Health用の環境変数を追加                      |
| SQLite migration     | connection、oauth token、sync cursorのテーブルを追加  |
| OAuth start API      | Google OAuth認可URLを生成する                      |
| OAuth callback API   | authorization codeを受け取りtokenへ交換する           |
| connection API       | 接続状態を取得・削除できる                               |
| token保存              | refresh token / access tokenをSQLiteに暗号化保存する |
| token refresh        | access token期限切れ時にrefresh tokenで更新する        |
| Google Health client | API呼び出しの共通clientを実装する                       |
| retry基盤              | 429、5xx、network errorに対するretryの土台を作る        |
| data type registry   | Fitbit Air対象data typeの定義ファイルを追加する           |
| smoke test           | 代表data type 1〜2個でAPI疎通を確認する                 |

### 5.2 Out of Scope

| 項目           | 理由         |
| ------------ | ---------- |
| 全data type取得 | Phase 2で扱う |
| Raw JSON保存   | Phase 2で扱う |
| Parquet保存    | Phase 2で扱う |
| Scheduler登録  | Phase 3で扱う |
| DuckDB view  | Phase 3で扱う |
| CLI          | 追加しない      |

---

## 6. Deliverables

| 成果物                                   | 内容                                     |
| ------------------------------------- | -------------------------------------- |
| `sources/google_health/auth.py`       | OAuth start / callback / token refresh |
| `sources/google_health/client.py`     | Google Health API client               |
| `sources/google_health/data_types.py` | Fitbit Air対象data type定義                |
| `api/routes/google_health.py`         | OAuth / connection API                 |
| SQLite migration                      | connection / token / cursor用テーブル       |
| config                                | Google Health用env                      |
| minimal smoke test                    | OAuth接続と代表API呼び出し確認                    |

---

## 7. Definition of Done

Phase 1は、以下を満たしたら完了とする。

### 7.1 Authentication

* `GET /v1/sources/google-health/auth/start` でOAuth認可URLを生成できる
* `GET /v1/sources/google-health/auth/callback` でauthorization codeを受け取れる
* authorization codeをaccess token / refresh tokenへ交換できる
* refresh tokenをSQLiteへ暗号化保存できる
* access tokenを自動refreshできる
* token、authorization codeをログに出していない

### 7.2 Connection Management

* `GET /v1/sources/google-health/connection` で接続状態を確認できる
* `DELETE /v1/sources/google-health/connection` で接続情報とtokenを削除できる
* connection statusとして `active` / `expired` / `revoked` / `error` を表現できる

### 7.3 Deployment Flexibility

* OAuth callback URIが `GOOGLE_HEALTH_REDIRECT_URI` で指定できる
* Tailscale専用実装になっていない
* Tailscale Serve、Cloudflare Tunnel、独自ドメイン、localhost検証のいずれでも構成可能な実装になっている

### 7.4 API Client

* Google Health API clientがaccess tokenを使ってAPI呼び出しできる
* 代表data typeで疎通確認できる
* 429、5xx、network errorに対するretryの基礎がある
* API errorを呼び出し元で分類できる

---

## 8. Phase 1 Test Points

| 観点            | 確認内容                                   |
| ------------- | -------------------------------------- |
| OAuth success | Google認可後、connectionがactiveになる         |
| Refresh       | access token期限切れ時にrefreshできる           |
| Delete        | connection削除後、tokenが残らない               |
| Invalid token | refresh失敗時にconnection statusがerror系になる |
| Redirect URI  | env変更でcallback URIを切り替えられる             |
| Log safety    | tokenやauthorization codeがログに出ない        |

---

# Phase 2: Ingestion and Storage

## 9. Objective

Fitbit Air由来のGoogle Health data typeを取得し、Raw JSONと正規化Parquetとして保存する。

このPhaseで、Google Health連携はEgoGraphのデータソースとして実質的に成立する。
backfill、range再取得、data type指定再取得をAPIから実行できるようにし、再取得時は対象partitionを上書きする。

---

## 10. Scope

### 10.1 In Scope

| 項目                  | 内容                                                 |
| ------------------- | -------------------------------------------------- |
| workflow実装          | `google_health_ingest_workflow` を追加                |
| run mode            | `initial_backfill`, `range`, `data_type_range` を実装 |
| extractor           | data typeごとの取得処理                                   |
| Raw JSON保存          | APIレスポンス原本をobject storageへ保存                       |
| normalizer          | Daily / Sample / Interval / Sessionへ正規化            |
| Parquet writer      | 正規化データをParquetへ保存                                  |
| partition overwrite | 対象期間のParquetを再生成                                   |
| no_data handling    | 値が返らないdata typeを正常扱いする                             |
| partial failure     | data type単位で成功・失敗を記録する                             |
| sync cursor         | data type単位の同期結果をSQLiteへ記録する                       |

### 10.2 Out of Scope

| 項目             | 理由         |
| -------------- | ---------- |
| Scheduler登録    | Phase 3で扱う |
| DuckDB view    | Phase 3で扱う |
| Webhook        | 最終設計で扱う    |
| Health Connect | 最終設計で扱う    |
| LLM context生成  | 最終設計で扱う    |

---

## 11. Data Coverage

Phase 2では、以下のdata typeを取得対象として実装する。

### 11.1 Activity / Fitness

| data type                     | 保存粒度            |
| ----------------------------- | --------------- |
| `steps`                       | interval, daily |
| `distance`                    | interval, daily |
| `total-calories`              | daily           |
| `active-energy-burned`        | interval, daily |
| `active-minutes`              | interval, daily |
| `active-zone-minutes`         | interval, daily |
| `activity-level`              | interval        |
| `sedentary-period`            | interval, daily |
| `calories-in-heart-rate-zone` | interval, daily |
| `time-in-heart-rate-zone`     | interval, daily |
| `exercise`                    | session, daily  |
| `floors`                      | interval, daily |
| `altitude`                    | interval, daily |
| `swim-lengths-data`           | interval, daily |
| `daily-vo2-max`               | daily           |
| `vo2-max`                     | sample          |
| `run-vo2-max`                 | sample          |

### 11.2 Heart / Recovery

| data type                             | 保存粒度          |
| ------------------------------------- | ------------- |
| `heart-rate`                          | sample, daily |
| `daily-resting-heart-rate`            | daily         |
| `heart-rate-variability`              | sample        |
| `daily-heart-rate-variability`        | daily         |
| `daily-heart-rate-zones`              | daily         |
| `oxygen-saturation`                   | sample        |
| `daily-oxygen-saturation`             | daily         |
| `respiratory-rate-sleep-summary`      | sample, daily |
| `daily-respiratory-rate`              | daily         |
| `daily-sleep-temperature-derivations` | daily         |

### 11.3 Sleep

| data type | 保存粒度           |
| --------- | -------------- |
| `sleep`   | session, daily |

### 11.4 Explicitly Excluded

以下は取得対象外として維持する。

| data type                       | 理由                       |
| ------------------------------- | ------------------------ |
| `food`                          | 食事ログ                     |
| `food-measurement-unit`         | 食事ログ補助                   |
| `nutrition-log`                 | 栄養ログ                     |
| `hydration-log`                 | 水分ログ                     |
| `weight`                        | 体重計・手入力系                 |
| `height`                        | プロフィール・手入力系              |
| `body-fat`                      | 体組成計・手入力系                |
| `blood-glucose`                 | Fitbit Air通常センサー由来ではない   |
| `electrocardiogram`             | Fitbit Airの標準取得対象として扱わない |
| `irregular-rhythm-notification` | Fitbit Airの標準取得対象として扱わない |

---

## 12. Deliverables

| 成果物                                   | 内容                                  |
| ------------------------------------- | ----------------------------------- |
| `sources/google_health/extractor.py`  | data typeごとの取得処理                    |
| `sources/google_health/normalizer.py` | Raw JSON → normalized records       |
| `sources/google_health/writer.py`     | Raw JSON / Parquet writer           |
| `sources/google_health/workflow.py`   | ingestion workflow                  |
| workflow registry登録                   | `google_health_ingest_workflow`     |
| workflow run API連携                    | APIからrunを作成できる                      |
| Parquet schema                        | daily / sample / interval / session |
| partition overwrite                   | 再取得時の上書き処理                          |
| sync cursor更新                         | data type単位の状態記録                    |

---

## 13. Definition of Done

Phase 2は、以下を満たしたら完了とする。

### 13.1 Workflow Execution

* `google_health_ingest_workflow` がworkflow registryに登録されている
* APIから `initial_backfill` runを作成できる
* APIから `range` runを作成できる
* APIから `data_type_range` runを作成できる
* connectionがない場合は安全に失敗する
* token期限切れ時はrefreshしてから取得できる

### 13.2 Raw JSON Storage

* data typeごとにRaw JSONを保存できる
* Raw JSON保存先に `connection_id`, `data_type`, `from`, `to`, `run_id` が含まれる
* Raw JSONをログに出していない
* normalizerを再実行できるだけの原本が残る

### 13.3 Normalization

* Daily recordを `google_health_daily_metrics` 形式に変換できる
* Sample recordを `google_health_samples` 形式に変換できる
* Interval recordを `google_health_intervals` 形式に変換できる
* Session recordを `google_health_sessions` 形式に変換できる
* `raw_ref` にRaw JSON保存先を保持している
* `device_family` に `fitbit_air` または `unknown` を設定できる

### 13.4 Parquet Storage

* `daily_metrics` Parquetを保存できる
* `samples` Parquetを保存できる
* `intervals` Parquetを保存できる
* `sessions` Parquetを保存できる
* 日付partitionで保存できる
* 同一期間を再取得した場合、対象partitionをoverwriteできる
* 小さいファイルが極端に増えすぎない最低限の保存単位になっている

### 13.5 Data Type Coverage

* Activity / Fitness対象data typeが取得対象として定義されている
* Heart / Recovery対象data typeが取得対象として定義されている
* Sleep対象data typeが取得対象として定義されている
* 値が返らないdata typeを `no_data` として扱える
* 一部data typeが失敗しても他data typeの取得を継続できる

### 13.6 Sync State

* data type単位で取得成功範囲をSQLiteに記録できる
* `success`, `no_data`, `failed` を区別できる
* 失敗時にerror messageを保存できる
* run全体のstatusとして `succeeded`, `partial_failed`, `failed` を表現できる

---

## 14. Phase 2 Test Points

| 観点              | 確認内容                             |
| --------------- | -------------------------------- |
| Backfill        | 過去90日分のinitial backfillが実行できる    |
| Range           | 任意期間の再取得ができる                     |
| Data type range | 特定data typeのみ再取得できる              |
| Raw             | Raw JSONがdata typeごとに保存される       |
| Daily           | 日次指標がParquet化される                 |
| Sample          | 心拍などのsampleがParquet化される          |
| Interval        | 歩数・活動量などのintervalがParquet化される    |
| Session         | sleep / exerciseがsessionとして保存される |
| Overwrite       | 同一期間再実行で重複せず上書きされる               |
| No data         | 値がないdata typeが正常終了扱いになる          |
| Partial failure | 一部失敗しても他data typeが保存される          |

---

# Phase 3: Scheduled Operation and Query

## 15. Objective

Google Health連携をEgoGraphの常駐データソースとして運用可能にする。

このPhaseでは、Schedulerによる定期取得、repair window、DuckDB view、run観測性、運用ドキュメントを整備する。
完了時点で、Fitbit Air由来データを日常的に蓄積し、DuckDBから健康状態の時系列を参照できる状態にする。

---

## 16. Scope

### 16.1 In Scope

| 項目                | 内容                                             |
| ----------------- | ---------------------------------------------- |
| Scheduler登録       | same-day / daily / weekly repair jobを登録        |
| repair window     | 直近期間を繰り返し再取得する                                 |
| DuckDB view       | `google_health_daily_summary` を追加              |
| run observability | run status、record count、duration、errorを確認可能にする |
| retry API連携       | 失敗runを再試行できる                                   |
| smoke test        | 実データで運用確認する                                    |
| docs              | OAuth設定、callback方式、運用手順を記載する                   |

### 16.2 Out of Scope

| 項目              | 理由                 |
| --------------- | ------------------ |
| Webhook         | 最終設計で扱う            |
| Dashboard       | 別機能として扱う           |
| Agent context生成 | health mart安定後に扱う  |
| Health Connect  | 別source追加として扱う     |
| compact jobの高度化 | 小ファイル問題が顕在化した時点で追加 |

---

## 17. Scheduler Jobs

| job                             | schedule | target range | 目的                        |
| ------------------------------- | -------- | ------------ | ------------------------- |
| `google_health_same_day_repair` | 3時間ごと    | 当日・前日        | 同日中の同期遅延を吸収               |
| `google_health_daily_repair`    | 毎日 04:30 | 過去14日        | 睡眠・HRV・SpO2・呼吸数などの後日補完を吸収 |
| `google_health_weekly_repair`   | 週1回      | 過去45日        | アプリ未起動、旅行、同期漏れなど長めの欠損を補修  |

14日は「完全性を保証する期間」ではなく、日常運用上の短期repair windowである。
長めの欠損はweekly repairで補う。

---

## 18. DuckDB Integration

### 18.1 Required View

日次分析用に、以下のview相当を用意する。

```sql
CREATE OR REPLACE VIEW google_health_daily_summary AS
SELECT
  date,
  max(CASE WHEN metric_name = 'steps' THEN value END) AS steps,
  max(CASE WHEN metric_name = 'distance' THEN value END) AS distance,
  max(CASE WHEN metric_name = 'total_calories' THEN value END) AS total_calories,
  max(CASE WHEN metric_name = 'active_energy_burned' THEN value END) AS active_energy_burned,
  max(CASE WHEN metric_name = 'active_minutes' THEN value END) AS active_minutes,
  max(CASE WHEN metric_name = 'active_zone_minutes' THEN value END) AS active_zone_minutes,
  max(CASE WHEN metric_name = 'resting_heart_rate' THEN value END) AS resting_heart_rate,
  max(CASE WHEN metric_name = 'daily_hrv' THEN value END) AS daily_hrv,
  max(CASE WHEN metric_name = 'daily_oxygen_saturation' THEN value END) AS daily_oxygen_saturation,
  max(CASE WHEN metric_name = 'daily_respiratory_rate' THEN value END) AS daily_respiratory_rate,
  max(CASE WHEN metric_name = 'sleep_duration' THEN value END) AS sleep_duration,
  max(CASE WHEN metric_name = 'daily_vo2_max' THEN value END) AS daily_vo2_max
FROM google_health_daily_metrics
GROUP BY date;
```

### 18.2 Query Use Cases

Phase 3完了時点で、以下の問いにDuckDBで答えられること。

```txt
直近30日の睡眠時間、歩数、HRV、安静時心拍を一覧する
```

```txt
HRVが低い日を抽出し、睡眠時間・呼吸数・SpO2と並べる
```

```txt
活動量が多い日と睡眠時間の関係を見る
```

```txt
repair window実行後に、過去数日の欠損が埋まったか確認する
```

---

## 19. Deliverables

| 成果物               | 内容                                     |
| ----------------- | -------------------------------------- |
| scheduler job     | same-day / daily / weekly repair       |
| DuckDB view       | `google_health_daily_summary`          |
| run status確認      | run一覧・詳細で状態確認可能                        |
| retry連携           | 失敗runを再試行可能                            |
| operational logs  | data type、record count、duration、status |
| docs              | OAuth setup、callback、scheduler、再取得手順   |
| smoke test report | 実データでの取得・保存・参照確認                       |

---

## 20. Definition of Done

Phase 3は、以下を満たしたら完了とする。

### 20.1 Scheduled Operation

* `google_health_same_day_repair` がSchedulerから実行される
* `google_health_daily_repair` がSchedulerから実行される
* `google_health_weekly_repair` がSchedulerから実行される
* 各jobが `google_health_ingest_workflow` を呼び出す
* Scheduler実行でもAPI手動実行でも同じworkflowを使う
* 同一期間の再取得でpartition overwriteされる

### 20.2 Repair Behavior

* 当日・前日の同期遅延をsame-day repairで吸収できる
* 過去14日の後日補完をdaily repairで吸収できる
* 過去45日の欠損補修をweekly repairで実行できる
* `no_data` と `failed` を区別して記録できる
* repair実行後にsync cursorが更新される

### 20.3 DuckDB Query

* Google Health ParquetをDuckDBから読める
* `google_health_daily_summary` 相当のviewを利用できる
* 睡眠、心拍、HRV、SpO2、呼吸数、歩数、活動量を同一日付軸で参照できる
* 直近30日程度の健康サマリを取得できる
* 欠損値をNULLとして扱える

### 20.4 Observability

* runごとにstatusを確認できる
* data typeごとの成功・no_data・失敗を確認できる
* record countを確認できる
* durationを確認できる
* error messageを確認できる
* tokenやRaw JSON本文がログに出ていない

### 20.5 Documentation

* Google Cloud側のOAuth設定手順が書かれている
* `GOOGLE_HEALTH_REDIRECT_URI` の設定方法が書かれている
* Tailscale以外のcallback方式も選べることが書かれている
* 初回backfillの実行方法が書かれている
* range再取得の実行方法が書かれている
* Scheduler jobの意味が書かれている
* 保存先の役割が書かれている

---

## 21. Phase 3 Test Points

| 観点              | 確認内容                    |
| --------------- | ----------------------- |
| Scheduler       | 予定時刻にworkflow runが作成される |
| Same-day repair | 当日・前日のデータが再取得される        |
| Daily repair    | 過去14日のpartitionが再生成される  |
| Weekly repair   | 過去45日の補修が実行される          |
| DuckDB          | daily summary viewが読める  |
| Missing data    | 欠損がNULLとして扱われる          |
| Retry           | 失敗runを再実行できる            |
| Logs            | tokenやRaw JSON本文が出力されない |
| Docs            | 新規環境で設定・接続・取得まで再現できる    |

---

# 22. Overall Completion Criteria

3フェーズ全体の完了条件は以下である。

| 領域   | 完了条件                                          |
| ---- | --------------------------------------------- |
| 認証   | Google OAuthで接続し、refresh tokenで継続取得できる        |
| 取得   | Fitbit Air由来の対象data typeを取得対象として実装している        |
| 保存   | Raw JSONと正規化Parquetを保存できる                     |
| 再取得  | backfill、range、data type指定、repair windowが動く   |
| 運用   | Schedulerでsame-day / daily / weekly repairが動く |
| 分析   | DuckDBから日次健康サマリを参照できる                         |
| 安全性  | tokenやRaw健康データ本文がログに出ない                       |
| 再処理性 | Raw JSONからParquetを再生成できる                      |
| 欠損耐性 | no_data、partial failure、retryを扱える             |

最終的な完成状態は以下である。

```txt
Fitbit Air由来の活動・睡眠・心拍・回復データが、
Google Health API経由で定期取得され、
Raw JSONとParquetとして保存され、
DuckDBから日次サマリとして参照できる。
```

---

# 23. Recommended PR Split

| PR   | 対応Phase | 目的                 |
| ---- | ------- | ------------------ |
| PR 1 | Phase 1 | Google Health接続基盤  |
| PR 2 | Phase 2 | Ingestionと保存       |
| PR 3 | Phase 3 | SchedulerとDuckDB統合 |

各PRの名前例。

```txt
PR 1: add google health connection foundation
PR 2: add google health ingestion and parquet storage
PR 3: add google health scheduler and daily summary query
```

PRは3つにまとめるが、Phase 2内部の実装順序は小さく刻む。

```txt
1. steps
2. sleep
3. heart-rate
4. daily HRV / SpO2 / respiratory rate
5. activity zone / exercise
6. optional no_data系
```

この順序により、最初に単純なActivity系で保存処理を固め、次にSessionであるsleep、Sampleであるheart-rateへ広げられる。
