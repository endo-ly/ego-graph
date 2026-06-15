# Google Health データソース設計

## データタイプ判定

- **タイプ**: 時系列・行動履歴
- **主用途**: DuckDB分析

---

## 1. 概要

### 1.1 データの性質

| 項目 | 値 |
|---|---|
| **タイプ** | 時系列・行動履歴 |
| **粒度** | Atomic / Summary |
| **更新頻度** | 3時間ごと / 日次 / 週次補修 |
| **センシティビティ** | High |
| **主な用途** | 分析（DuckDB） |

### 1.2 概要説明

Google Health API v4 を通じて、Google Fitbit Air 由来の活動、睡眠、心拍、回復指標を収集する。
APIレスポンス原本をRaw JSONとして保持し、日次指標、サンプル、区間、セッションの4種類へ正規化してParquetへ保存する。

主な分析対象は次のとおり。

| カテゴリ | データ |
|---|---|
| Activity / Fitness | 歩数、距離、消費カロリー、活動時間、運動、階数、VO2 Max |
| Heart / Recovery | 心拍、安静時心拍、HRV、SpO2、呼吸数、睡眠時皮膚温 |
| Sleep | 睡眠セッション、睡眠時間 |

---

## 2. データフロー全体像

```text
[Google Fitbit Air]
         ↓
[Google Health mobile app]
         ↓ 同期
[Google Health API v4]
         ↓ OAuth 2.0 / REST
[Extractor: data type単位で取得]
         ↓
[Storage: R2へRaw JSON保存]
         ↓
[Normalizer: Daily / Sample / Interval / Session]
         ↓
[Storage: R2 eventsへ{uuid}.parquet保存]
         ↓
[Compact: 対象期間を統合・置換]
         ↓
[Storage: R2 compactedへdata.parquet保存]
         ↓
[DuckDB: 日次・時系列分析]
```

接続情報、暗号化済みOAuth token、data type単位の同期状態はSQLiteで管理する。

---

## 3. 入力データ構造

### 3.1 データ取得元

| 項目 | 説明 |
|---|---|
| **取得方法** | REST API |
| **API/ソース** | Google Health API v4 |
| **Base URL** | `https://health.googleapis.com/v4` |
| **List endpoint** | `GET /users/me/dataTypes/{dataType}/dataPoints` |
| **Daily rollup endpoint** | `POST /users/me/dataTypes/{dataType}/dataPoints:dailyRollUp` |
| **認証方式** | Google OAuth 2.0 Web Server flow |
| **必要なスコープ** | Activity and Fitness / Health Metrics and Measurements / Sleep のread-only scope |
| **期間の日付解釈** | `TIMEZONE`のローカル日付。物理時刻APIにはUTCへ変換して送信 |

### 3.2 取得対象data type

#### Activity / Fitness

| Data type | 保存粒度 |
|---|---|
| `steps` | interval, daily |
| `distance` | interval, daily |
| `total-calories` | daily |
| `active-energy-burned` | interval, daily |
| `active-minutes` | interval, daily |
| `active-zone-minutes` | interval, daily |
| `activity-level` | interval |
| `sedentary-period` | interval, daily |
| `calories-in-heart-rate-zone` | interval, daily |
| `time-in-heart-rate-zone` | interval, daily |
| `exercise` | session, daily |
| `floors` | interval, daily |
| `altitude` | interval, daily |
| `swim-lengths-data` | interval, daily |
| `daily-vo2-max` | daily |
| `vo2-max` | sample |
| `run-vo2-max` | sample |

#### Heart / Recovery

| Data type | 保存粒度 |
|---|---|
| `heart-rate` | sample, daily |
| `daily-resting-heart-rate` | daily |
| `heart-rate-variability` | sample |
| `daily-heart-rate-variability` | daily |
| `daily-heart-rate-zones` | daily |
| `oxygen-saturation` | sample |
| `daily-oxygen-saturation` | daily |
| `respiratory-rate-sleep-summary` | sample, daily |
| `daily-respiratory-rate` | daily |
| `daily-sleep-temperature-derivations` | daily |

#### Sleep

| Data type | 保存粒度 |
|---|---|
| `sleep` | session, daily |

### 3.3 入力スキーマ

Google Health APIの`DataPoint`はdata typeごとの値をunionとして保持する。

#### 基本情報

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `name` | string | Yes | data pointのリソース名 | `"users/me/dataTypes/steps/dataPoints/..."` |
| `dataSource` | string | No | データ生成元 | `"users/me/dataSources/..."` |
| `dataOrigin` | object | No | データ由来情報 | `{"application": {...}}` |
| `createTime` | datetime | No | API上の作成時刻 | `"2026-06-10T00:00:00Z"` |
| `updateTime` | datetime | No | API上の更新時刻 | `"2026-06-10T01:00:00Z"` |

#### 時間情報

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `{dataType}.sampleTime.physicalTime` | datetime | Conditional | サンプルの測定時刻。欠落時は`{dataType}.instantTime`を使用 | `"2026-06-10T00:15:00Z"` |
| `{dataType}.interval.startTime` | datetime | Conditional | 区間・セッション開始時刻 | `"2026-06-10T00:00:00Z"` |
| `{dataType}.interval.endTime` | datetime | Conditional | 区間・セッション終了時刻 | `"2026-06-10T00:05:00Z"` |
| `{dataType}.date` | date | Conditional | Daily recordの日付 | `"2026-06-10"` |
| `civilStartTime` | object | Conditional | daily rollupのローカル開始日時 | `{"date":{"year":2026,"month":6,"day":10}}` |
| `civilEndTime` | object | Conditional | daily rollupのローカル終了日時 | `{"date":{"year":2026,"month":6,"day":11}}` |

#### data type固有値

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `steps` | object | Conditional | 歩数値 | `{"count": 120}` |
| `heartRate` | object | Conditional | 心拍値 | `{"beatsPerMinute": 72}` |
| `sleep` | object | Conditional | 睡眠セッション情報 | `{"type": "SLEEP"}` |
| `exercise` | object | Conditional | 運動セッション情報 | `{"exerciseType": "RUNNING"}` |

レスポンスは`dataPoints`配列と、継続取得用の`nextPageToken`を持つ。

---

## 4. Parquetスキーマ

### 4.1 `google_health_daily_metrics`

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `connection_id` | VARCHAR | 接続識別子 | SQLite connection |
| `data_type` | VARCHAR | Google Health data type | API path |
| `date` | DATE | 指標のローカル日付 | `{dataType}.date` / `civilStartTime` |
| `metric_name` | VARCHAR | 正規化した指標名 | data type |
| `value` | DOUBLE | 数値 | data type固有値 |
| `unit` | VARCHAR | 単位 | data type定義 |
| `device_family` | VARCHAR | `fitbit_air`または`unknown` | `dataOrigin` |
| `raw_ref` | VARCHAR | Raw JSON保存先 | システム生成 |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 | システム生成 |

### 4.2 `google_health_samples`

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `connection_id` | VARCHAR | 接続識別子 | SQLite connection |
| `data_type` | VARCHAR | Google Health data type | API path |
| `measured_at_utc` | TIMESTAMP | 測定時刻 | `{dataType}.sampleTime.physicalTime`（欠落時は`{dataType}.instantTime`） |
| `value` | DOUBLE | 測定値 | data type固有値 |
| `unit` | VARCHAR | 単位 | data type定義 |
| `device_family` | VARCHAR | `fitbit_air`または`unknown` | `dataOrigin` |
| `raw_ref` | VARCHAR | Raw JSON保存先 | システム生成 |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 | システム生成 |

### 4.3 `google_health_intervals`

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `connection_id` | VARCHAR | 接続識別子 | SQLite connection |
| `data_type` | VARCHAR | Google Health data type | API path |
| `started_at_utc` | TIMESTAMP | 区間開始時刻 | `interval.startTime` |
| `ended_at_utc` | TIMESTAMP | 区間終了時刻 | `interval.endTime` |
| `value` | DOUBLE | 区間値 | data type固有値 |
| `unit` | VARCHAR | 単位 | data type定義 |
| `device_family` | VARCHAR | `fitbit_air`または`unknown` | `dataOrigin` |
| `raw_ref` | VARCHAR | Raw JSON保存先 | システム生成 |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 | システム生成 |

### 4.4 `google_health_sessions`

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `connection_id` | VARCHAR | 接続識別子 | SQLite connection |
| `data_type` | VARCHAR | `sleep`または`exercise` | API path |
| `session_id` | VARCHAR | セッション識別子 | `name` |
| `started_at_utc` | TIMESTAMP | セッション開始時刻 | `interval.startTime` |
| `ended_at_utc` | TIMESTAMP | セッション終了時刻 | `interval.endTime` |
| `duration_seconds` | BIGINT | 継続秒数 | 開始・終了時刻から算出 |
| `session_type` | VARCHAR | 睡眠・運動種別 | data type固有値 |
| `device_family` | VARCHAR | `fitbit_air`または`unknown` | `dataOrigin` |
| `raw_ref` | VARCHAR | Raw JSON保存先 | システム生成 |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 | システム生成 |

### 4.5 パーティション

- **パーティションキー**: `year`, `month`
- **基準日**: dailyはローカル`date`、sampleは`measured_at_utc`、interval/sessionは`started_at_utc`
- **再取得**: compacted内の対象期間を置換する
- **時刻partition**: sample / interval / sessionの`year` / `month`はUTC基準
- **理由**: 保存時刻をUTCへ統一し、期間指定クエリのpartition pruningと再取得時の重複を防ぐ

---

## 5. R2保存先

### 5.1 ディレクトリ構造

```text
s3://egograph/
  ├── raw/google_health/
  │   └── connection_id={connection_id}/
  │       └── data_type={data_type}/
  │           └── from={from}/
  │               └── to={to}/
  │                   └── run_id={run_id}.json
  ├── events/google_health/
  │   └── {daily_metrics|samples|intervals|sessions}/
  │       └── year=YYYY/
  │           └── month=MM/
  │               └── {uuid}.parquet
  └── compacted/events/google_health/
      └── {daily_metrics|samples|intervals|sessions}/
          └── year=YYYY/
              └── month=MM/
                  └── data.parquet
```

同期cursor、connection、OAuth tokenはR2ではなくPipelines ServiceのSQLiteへ保存する。

### 5.2 保存パス例

- **Raw**: `s3://egograph/raw/google_health/connection_id=google-health-primary/data_type=steps/from=2026-06-01/to=2026-06-10/run_id={run_id}.json`
- **Daily**: `s3://egograph/events/google_health/daily_metrics/year=2026/month=06/{uuid}.parquet`
- **Sample**: `s3://egograph/events/google_health/samples/year=2026/month=06/{uuid}.parquet`
- **Interval**: `s3://egograph/events/google_health/intervals/year=2026/month=06/{uuid}.parquet`
- **Session**: `s3://egograph/events/google_health/sessions/year=2026/month=06/{uuid}.parquet`
- **Compacted**: `s3://egograph/compacted/events/google_health/samples/year=2026/month=06/data.parquet`

---

## 6. 検索・活用シナリオ

| ユーザーの質問 | 意図 | SQLクエリ例 |
|---|---|---|
| 直近30日の睡眠時間、歩数、HRV、安静時心拍を一覧したい | 事実列挙 | `SELECT * FROM google_health_daily_summary WHERE date >= current_date - INTERVAL 30 DAY ORDER BY date` |
| HRVが低い日の睡眠時間、呼吸数、SpO2を比較したい | パターン発見 | `SELECT date, daily_hrv, sleep_duration, daily_respiratory_rate, daily_oxygen_saturation FROM google_health_daily_summary WHERE daily_hrv < 30 ORDER BY date` |
| 活動量が多い日と睡眠時間の関係を確認したい | 定量分析 | `SELECT corr(steps, sleep_duration) FROM google_health_daily_summary WHERE steps IS NOT NULL AND sleep_duration IS NOT NULL` |
| 特定日の心拍推移を確認したい | 事実列挙 | `SELECT measured_at_utc, value FROM google_health_samples WHERE data_type = 'heart-rate' AND CAST(measured_at_utc AS DATE) = DATE '2026-06-10' ORDER BY measured_at_utc` |

日次サマリはBackendから次の2経路で参照できる。

| 経路 | 識別子 | 日付の扱い |
|---|---|---|
| REST API | `GET /v1/data/google-health/daily-summary` | `start_date`と`end_date`を含むローカル日付範囲 |
| MCP | `get_google_health_daily_summary` | REST APIと同じローカル日付範囲 |

`google_health_daily_summary`相当のDuckDBクエリは`daily_metrics.date`をそのまま日付軸として使う。
絶対時刻のタイムゾーン変換は行わず、欠損した指標は`NULL`として返す。

---

## 7. 設計判断・技術選定

### 7.1 保存形式

| 対象 | 保存先 | 理由 |
|---|---|---|
| APIレスポンス原本 | R2 Raw JSON | normalizer修正後の再処理と監査に使用する |
| 取得単位の正規化データ | R2 events Parquet | runごとの取得結果を保持する |
| 分析用の正規化データ | R2 compacted Parquet | DuckDBの列指向分析とpartition pruningに適する |
| connection / token / cursor | SQLite | Pipelines Serviceの状態として一貫して更新する |

### 7.2 正規化粒度

data typeごとに個別テーブルを増やさず、Daily / Sample / Interval / Sessionの4種類へ統合する。
共通の時系列クエリを保ちつつ、data type固有の取得処理を分離できるためである。

### 7.3 再取得

同一期間を再取得した場合は、選択したdata typeの対象期間だけを月partition内で置換する。
同じ月に保存されている他のdata typeと対象期間外の行は保持する。
`compact_range`は`connection_id`と`data_type`が一致し、`date_from <= row_date < date_to`となる行だけを置換する。
sessionの`data_type`が`sleep`の場合、対象日には`started_at_utc`ではなく`ended_at_utc`を使用する。
取得ごとにeventsへ`{uuid}.parquet`を追加し、compact処理で対象期間を反映したcompactedの`data.parquet`を再生成する。
events側の`{run_id}.parquet`は削除せず、削除対象になるのは置換後に空となったcompactedファイルだけである。
Google Health側の遅延同期や後日補完を取り込みながら、重複レコードを残さない。

APIの`from` / `to`は`TIMEZONE`のローカル日付として扱う。
`reconcile`とphysical `rollUp`には、各日付のローカル0時をUTCへ変換して送信する。
`dailyRollUp`にはcivil dateをそのまま送信する。
取得した絶対時刻と`ingested_at_utc`はUTCで保存し、睡眠などから生成する日次行の日付は`TIMEZONE`で判定する。

### 7.4 同期状態

`google_health_sync_cursors`へdata type単位で次を保存する。
同期結果は`save_sync_result`がupsertし、compact処理では`last_run_id`を使って対象runの結果だけを読み込む。

| 列 | 内容 |
|---|---|
| `status` | `success` / `no_data` / `failed` |
| `range_start` | 取得範囲の開始日 |
| `range_end` | 取得範囲の終了日（この日を含まない） |
| `last_run_id` | 最後に処理したworkflow run ID |
| `record_count` | 正規化後の保存件数 |
| `last_error_message` | 失敗理由 |
| `updated_at` | 更新時刻 |

---

## 11. 実装時の考慮事項

### 11.1 エッジケース

- 値が返らないdata typeは失敗ではなく`no_data`として扱う
- 一部data typeが失敗しても、他data typeの取得と保存を継続する
- API paginationの`nextPageToken`を最後まで処理する
- 取得期間上限が異なるdata typeはリクエスト期間を分割する
- Fitbitアプリとの同期遅延を考慮して直近期間を再取得する

### 11.2 制約・制限

- access tokenとrefresh tokenはFernetで暗号化してSQLiteへ保存する
- token、authorization code、Raw JSON本文をログへ出さない
- OAuth `state`はハッシュ化し、期限付きの一回限りの値として検証する
- callbackのquery stringはaccess logで伏せる
- 健康データを含むため、Raw JSONとParquetをHigh sensitivityとして扱う

### 11.3 将来拡張

- 日次サマリ以外のsample / interval / session参照API
- 健康指標の可視化Dashboard

---

## 12. サンプルデータ

### 12.1 入力データ例

```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/heart-rate/dataPoints/example",
      "heartRate": {
        "sampleTime": {
          "physicalTime": "2026-06-10T00:15:00Z"
        },
        "beatsPerMinute": 72
      }
    }
  ]
}
```

### 12.2 Parquet行例

```json
{
  "connection_id": "google-health-primary",
  "data_type": "heart-rate",
  "measured_at_utc": "2026-06-10T00:15:00Z",
  "value": 72,
  "unit": "beats_per_minute",
  "device_family": "fitbit_air",
  "raw_ref": "raw/google_health/connection_id=google-health-primary/data_type=heart-rate/from=2026-06-10/to=2026-06-11/run_id=example.json",
  "ingested_at_utc": "2026-06-11T00:00:00Z"
}
```

---

## 13. 次のステップ

### 実装状況

- [x] OAuth接続、token暗号化保存、token refresh
- [x] 対象data typeの取得とpagination
- [x] Raw JSON保存
- [x] Daily / Sample / Interval / Session正規化
- [x] events保存とcompactedの月partition範囲置換
- [x] data type単位の同期状態保存
- [x] backfill / range / data type指定run API
- [x] same-day / daily / weekly repair Scheduler
- [x] DuckDB日次サマリ
- [x] REST API / MCP提供
- [x] run観測と入力を保持したretry
- [x] 単体テスト・統合テスト
- [x] DuckDBマウント

### 未実装機能

- [ ] sample / interval / sessionの専用参照API

---

## 14. セットアップ・運用手順

### 14.1 Google Cloud

#### 14.1.1 プロジェクトを選択する

1. [Google Cloud Console](https://console.cloud.google.com/)を開き、Google Accountでログインする。
2. 画面上部のプロジェクト名をクリックする。
3. EgoGraphで使用するプロジェクトを選択する。
4. プロジェクトがない場合は[プロジェクト作成](https://console.cloud.google.com/projectcreate)を開き、次を入力して作成する。

| 項目 | 入力値 |
|---|---|
| Project name | `EgoGraph` |
| Organization | 個人利用の場合は`No organization` |
| Location | Organizationに応じた値 |

以降の操作前に、画面上部で選択中のプロジェクトがEgoGraph用になっていることを確認する。

#### 14.1.2 Google Health APIを有効化する

1. [Google Health APIのAPIライブラリ](https://console.cloud.google.com/apis/library/health.googleapis.com)を開く。
2. ページ上部の選択中プロジェクトがEgoGraph用であることを確認する。
3. `ENABLE`または`有効にする`をクリックする。
4. `API enabled`と表示されるか、ボタンが`MANAGE`または`管理`へ変われば完了。

ページが見つからない場合は、[APIライブラリ](https://console.cloud.google.com/apis/library)を開き、検索欄へ`Google Health API`と入力して同名のAPIを選択する。

#### 14.1.3 OAuth consent screenとAudienceを設定する

1. [Google Auth Platform Overview](https://console.cloud.google.com/auth/overview)を開く。
2. 未設定の場合は`Get started`をクリックする。
3. 次を入力する。

| 画面 | 項目 | 入力値 |
|---|---|---|
| App Information | App name | `EgoGraph` |
| App Information | User support email | 自分のGoogle Accountのメールアドレス |
| Audience | User type | `External` |
| Contact Information | Email addresses | 自分のGoogle Accountのメールアドレス |

4. Google API Services User Data Policyへの同意欄を確認して作成を完了する。
5. [Audience](https://console.cloud.google.com/auth/audience)を開く。
6. `Publishing status`が`Testing`、`User type`が`External`であることを確認する。
7. `Test users`の`Add users`をクリックする。
8. Google Fitbit Airで使用しているメインGoogle Accountのメールアドレスを入力する。
9. `Save`をクリックする。

Google Cloudの管理に使う開発用Google Accountと、健康データを持つメインGoogle Accountは別でよい。
OAuth認証時は、Test userへ追加したメインGoogle Accountでログインする。

`Testing`ではrefresh tokenが7日で失効する。
継続運用へ移行する際は`In production`へ変更し、OAuth app verificationを完了する。
100ユーザーを超える利用や一般公開では、Google Healthの第三者セキュリティレビューも必要になる。

#### 14.1.4 OAuth scopeを追加する

1. [Data Access](https://console.cloud.google.com/auth/scopes)を開く。
2. `Add or remove scopes`をクリックする。
3. 検索欄で`Google Health API`を検索する。
4. 次の3スコープを選択する。

```text
https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly
https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly
https://www.googleapis.com/auth/googlehealth.sleep.readonly
```

5. `Update`をクリックする。
6. Data Access画面へ戻ったら`Save`をクリックする。

#### 14.1.5 OAuth clientを作成する

1. [Clients](https://console.cloud.google.com/auth/clients)を開く。
2. `Create client`をクリックする。
3. 次を入力する。

| 項目 | 入力値 |
|---|---|
| Application type | `Web application` |
| Name | `EgoGraph Pipelines` |
| Authorized JavaScript origins | 空欄 |
| Authorized redirect URIs | `https://<callback-host>/v1/sources/google-health/auth/callback` |

4. `Create`をクリックする。
5. 表示されたClient IDとClient secretを安全な場所へ控える。
6. Client IDとClient secretをGit、Issue、PR、チャットへ貼らない。

### 14.2 環境変数

| 変数 | 必須 | 内容 |
|---|---|---|
| `TIMEZONE` | Yes | 取得日付と日次判定に使うIANAタイムゾーン名（例: `Asia/Tokyo`） |
| `GOOGLE_HEALTH_CLIENT_ID` | Yes | OAuth client ID |
| `GOOGLE_HEALTH_CLIENT_SECRET` | Yes | OAuth client secret |
| `GOOGLE_HEALTH_REDIRECT_URI` | Yes | Google Cloud登録済みcallback URI |
| `GOOGLE_HEALTH_TOKEN_ENCRYPTION_KEY` | Yes | Fernet key |
| `PIPELINES_API_KEY` | Yes | 管理APIの認証key |

Fernet keyは次のコマンドで生成する。

```bash
uv run python -c \
  'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

keyを変更すると既存tokenは復号できないため、tokenとは別のsecret storeで管理する。

`egograph/pipelines/.env`へ次を設定する。

```dotenv
TIMEZONE=Asia/Tokyo
PIPELINES_API_KEY=<十分に長いランダム文字列>
GOOGLE_HEALTH_CLIENT_ID=<14.1.5で取得したClient ID>
GOOGLE_HEALTH_CLIENT_SECRET=<14.1.5で取得したClient secret>
GOOGLE_HEALTH_REDIRECT_URI=https://<callback-host>/v1/sources/google-health/auth/callback
GOOGLE_HEALTH_TOKEN_ENCRYPTION_KEY=<生成したFernet key>
```

### 14.3 接続

14.2まで完了したら、次の手順を上から順に実行する。

#### 14.3.1 Pipelines Serviceを起動する

リポジトリルートで次を実行する。

```bash
uv run python -m pipelines.main serve
```

`Uvicorn running`と表示されたら、接続作業が完了するまでこのターミナルを開いたままにする。

#### 14.3.2 OAuth callbackの受信方法を選択する

次の3方式から1つを選択する。
どの方式でも、Google CloudのAuthorized redirect URIと`GOOGLE_HEALTH_REDIRECT_URI`を完全に一致させる。
callbackはOAuth認証時だけ必要であり、認証完了後は公開やトンネルを停止してよい。

##### A. Tailscale Serve

tailnet内のHTTPS URLを一時的にPipelines Serviceへ転送する。

Google Cloudと`.env`には次の形式で設定する。

```text
https://<tailscale-host>:<https-port>/v1/sources/google-health/auth/callback
```

サーバーで次を実行する。

```bash
tailscale serve --bg \
  --https=<https-port> \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}"
```

認証完了後に停止する。

```bash
tailscale serve --https=<https-port> off
```

##### B. Tailscale以外の外部HTTPS

Cloudflare Tunnelや独自ドメインのHTTPS reverse proxyを利用し、Pipelines Serviceへ転送する。
例としてCloudflare Tunnelを使用する場合、固定ホスト名を割り当てたnamed tunnelを作成し、次のように転送する。

```yaml
# ~/.cloudflared/config.yml
tunnel: <tunnel-id>
credentials-file: /path/to/<tunnel-id>.json

ingress:
  - hostname: <callback-host>
    path: ^/v1/sources/google-health/auth/callback$
    service: http://127.0.0.1:8001
  - service: http_status:404
```

Google Cloudと`.env`には次を設定する。

```text
https://<callback-host>/v1/sources/google-health/auth/callback
```

サーバーでtunnelを起動する。

```bash
cloudflared tunnel run <tunnel-name>
```

認証完了後は`cloudflared`を停止する。
独自ドメインのreverse proxyを使う場合も、公開するcallback URIだけをPipelines Serviceへ転送する。

##### C. 手元PCからSSHローカルフォワード

外部HTTPSを公開せず、手元PCのloopback URLでcallbackを受け、SSH経由でサーバーのPipelines Serviceへ転送する。

Google Cloudとサーバーの`.env`には次を設定する。

```text
http://127.0.0.1:18001/v1/sources/google-health/auth/callback
```

設定変更後にPipelines Serviceを再起動する。
手元PCで次を実行し、認証完了まで開いたままにする。

```bash
ssh -N \
  -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18001:127.0.0.1:8001 \
  <user>@<server>
```

サーバー側のPipelines Serviceが`8001`以外で待ち受ける場合は、コマンド末尾のポートを合わせる。
認可URLは14.3.3の手順でサーバー上から取得し、手元PCのブラウザで開く。
callbackは手元PCの`127.0.0.1:18001`からSSHトンネルを通ってサーバーへ届く。
認証完了後はSSHコマンドを`Ctrl+C`で停止する。

#### 14.3.3 認可URLを取得する

別のターミナルを開き、リポジトリルートで次を実行する。

```bash
set -a
source egograph/pipelines/.env
set +a

curl -s \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/auth/start" \
  | uv run python -c \
    'import json, sys; print(json.load(sys.stdin)["authorization_url"])'
```

表示された`https://accounts.google.com/...`で始まるURLをブラウザで開く。

#### 14.3.4 Google Accountで認証する

1. Test userへ追加した、Google Fitbit Airの健康データを持つメインGoogle Accountを選択する。
2. EgoGraphが要求する3つのread-only権限を確認する。
3. 権限を許可する。
4. callbackの結果として、connection IDと`active`がブラウザへ表示されることを確認する。

#### 14.3.5 接続状態を確認する

14.3.3で使用したターミナルで次を実行する。

```bash
curl -s \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/connection" \
  | uv run python -m json.tool
```

`connected`が`true`、`status`が`active`であれば接続完了。

### 14.4 疎通確認

`steps`と`sleep`を各1件まで取得する。

```bash
curl -X POST \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/connection/smoke-test"
```

### 14.5 データ取得

すべての期間指定は`from`を含み、`to`を含まない。
たとえば`from=2026-06-01`, `to=2026-06-03`は6月1日と6月2日を取得する。

#### 14.5.1 初回90日分を取得する

```bash
curl -s -X POST \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"mode":"initial_backfill"}' \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/runs" \
  | uv run python -m json.tool
```

#### 14.5.2 指定期間を全data type再取得する

```bash
curl -s -X POST \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"mode":"range","from":"2026-06-01","to":"2026-06-03"}' \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/runs" \
  | uv run python -m json.tool
```

#### 14.5.3 指定data typeだけ再取得する

```bash
curl -s -X POST \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "mode":"data_type_range",
    "from":"2026-06-01",
    "to":"2026-06-03",
    "data_types":["steps","sleep","heart-rate"]
  }' \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/runs" \
  | uv run python -m json.tool
```

レスポンスの`run_id`を使って実行結果を確認する。

```bash
RUN_ID=<レスポンスのrun_id>

curl -s \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/runs/${RUN_ID}" \
  | uv run python -m json.tool
```

runの`status`は`succeeded`、`partial_failed`、`failed`のいずれかになる。
`result_summary.data_types`でdata typeごとの`success`、`no_data`、`failed`、件数、エラーを確認する。

#### 14.5.4 SQLiteの同期状態を確認する

```bash
uv run python <<'PY'
import sqlite3
from pipelines.config import PipelinesConfig

db_path = PipelinesConfig().database_path
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

for row in conn.execute("""
    SELECT
        data_type,
        status,
        range_start,
        range_end,
        last_run_id,
        record_count,
        last_error_message,
        updated_at
    FROM google_health_sync_cursors
    ORDER BY data_type
"""):
    print(dict(row))
PY
```

### 14.6 Scheduler運用

Pipelines Service起動中は、次のrepair jobが`TIMEZONE`基準で同じ`google_health_ingest_workflow`を実行する。

| Job | Schedule | 取得範囲 |
|---|---|---|
| `google_health_same_day_repair` | 3時間ごと | 実行日と前日 |
| `google_health_daily_repair` | 毎日04:30 | 実行日を含む直近14日 |
| `google_health_weekly_repair` | 毎週日曜05:30 | 実行日を含む直近45日 |

jobは実行時刻を`TIMEZONE`へ変換してclosed-open期間を確定する。
実行日が2026-06-15の場合、14日repairは`from=2026-06-02`, `to=2026-06-16`となる。

### 14.7 日次サマリ参照

Backend APIでは`start_date`と`end_date`の両日を含む。

```bash
curl -s \
  -H "X-API-Key: ${BACKEND_API_KEY}" \
  "http://${BACKEND_HOST:-127.0.0.1}:${BACKEND_PORT:-8000}/v1/data/google-health/daily-summary?start_date=2026-06-01&end_date=2026-06-30" \
  | uv run python -m json.tool
```

MCPでは`get_google_health_daily_summary`へ同じ`start_date`と`end_date`を渡す。
日次指標はGoogle Healthが返したローカル`date`を維持し、欠損指標は`null`になる。

### 14.8 接続削除

```bash
curl -X DELETE \
  -H "X-API-Key: ${PIPELINES_API_KEY}" \
  "http://${PIPELINES_HOST:-127.0.0.1}:${PIPELINES_PORT:-8001}/v1/sources/google-health/connection"
```

connectionを削除すると、SQLite内のOAuth tokenとsync cursorも削除される。

### 14.9 参照

- [Google Health API: Set up Google Cloud and OAuth](https://developers.google.com/health/setup)
- [Google OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google Health API Scopes](https://developers.google.com/health/scopes)
