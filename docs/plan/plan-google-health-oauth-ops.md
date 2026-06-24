# Google Health 認証障害の診断性改善 Plan

## 目的

Google Health 取り込みで認証が切れたときに、原因をコードと運用から一意に判断できるようにする。

今回の主因は Google Auth Platform が `テスト中` だったことによる refresh token の7日失効と判断する。これは運用設定で解消済み。コード側で直すべき本質は、refresh 失敗時に原因情報を捨てているため、次回障害時に同じ調査を繰り返す構造である。

## 現状

本番で確認した状態:

- `google_health_connections.status = revoked`
- `last_error_message = access token refresh failed`
- `google_health_ingest_workflow` は `google_health_active_connection_not_found` で失敗
- Google Auth Platform は `テスト中` だった
- connection 作成から revoked 更新まで約7日

該当コード:

- `egograph/pipelines/sources/google_health/client.py`
  - `_refresh_token()` が refresh 失敗時に `access token refresh failed` だけを保存する
  - Google OAuth error body を捨てている
- `egograph/pipelines/sources/google_health/workflow.py`
  - connection が active でない場合に `google_health_active_connection_not_found` を投げる
- `egograph/pipelines/api/google_health.py`
  - 手動run作成時は active connection がなければ 409 を返す

## 方針

1. refresh 失敗の OAuth error body を安全に要約する
2. 要約を `last_error_message` に保存する
3. connection status は、OAuth error の意味に基づいて更新する
4. 一時障害では connection を inactive にしない
5. workflow 側の前提条件エラー文だけ具体化する
6. Activity系 null は、認証復旧後に1回だけ実データで切り分ける。コード変更はまだしない

## 実装タスク

### Task 1: OAuth error body の安全な要約関数を追加する

対象: `egograph/pipelines/sources/google_health/client.py`

追加する関数:

```python
def _oauth_error_summary(response: Response) -> str:
    ...
```

仕様:

- 返り値は1行文字列
- 最大長は 500 文字程度に切る
- JSON bodyの場合、以下だけ使う
  - HTTP status
  - `error`
  - `error_subtype`
- `error_description` は意図的に保存しない。provider 側が自由に書ける free text であり、機密値が混入する可能性があるため
- JSONでない場合は body を保存しない
- token、code、secret、authorization header は絶対に含めない
- `error` / `error_subtype` の値は field ごとの明示的許可リストに完全一致する
  場合だけ保存する。許可リスト外の値 (token / code / 自由文等) は、
  field 名ごと要約から除外する。
  - `error` 許可リスト: `invalid_request` / `invalid_client` / `invalid_grant`
    / `unauthorized_client` / `unsupported_grant_type` / `invalid_scope`
  - `error_subtype` 許可リスト: `invalid_rapt`
  - 短い token や authorization code は OAuth 仕様の identifier 形状を満たし
    得るため、形状ではなく許可リストで制限する。provider 由来の文字列を
    無条件で信頼しない。秘密情報混入を防ぐための防御線。

出力例:

```text
oauth_refresh_failed: status=400 error=invalid_grant
```

```text
oauth_refresh_failed: status=401 error=invalid_client
```

```text
oauth_refresh_failed: status=500
```

実装上の制約:

- `response.text` を丸ごと保存しない
- 未知fieldを保存しない
- 例外が出ても診断関数自体で落とさない

### Task 2: `_refresh_token()` の status 更新メッセージを置き換える

対象: `egograph/pipelines/sources/google_health/client.py`

現状:

```python
self._repository.update_connection_status(
    connection_id,
    status,
    "access token refresh failed",
)
raise GoogleHealthAuthenticationError("google_health_token_refresh_failed")
```

変更後:

```python
error_summary = _oauth_error_summary(response)
status = _refresh_failure_connection_status(response)
if status is not None:
    self._repository.update_connection_status(
        connection_id,
        status,
        error_summary,
    )
raise GoogleHealthAuthenticationError(error_summary)
```

status 方針:

- `invalid_grant`: `ConnectionStatus.REVOKED`
- `invalid_client` / `unauthorized_client`: `ConnectionStatus.ERROR`
- 429 / 5xx: connection status は更新しない
- JSONでない4xx: `ConnectionStatus.ERROR`
- `error` 値が `error` field の明示的許可リスト (Task 1 と同一) に一致しない場合は
  未分類扱い。結果として未知の 4xx と同じく `ConnectionStatus.ERROR` になる。
  許可リスト外の値で既知の error 名との完全一致を試みない。

一時障害で connection を `error` に落とさない。ここを誤ると、Google側の一時障害やrate limitで永続的に ingest が止まり、手動再認証ではなくDB状態修復が必要になる。

細かい分類enumは追加しない。現時点では過剰。判断に必要な情報は `last_error_message` と status 遷移で足りる。

### Task 3: workflow の active connection 不在エラーを具体化する

対象: `egograph/pipelines/sources/google_health/workflow.py`

現状:

```python
if connection is None or connection.status is not ConnectionStatus.ACTIVE:
    raise RuntimeError("google_health_active_connection_not_found")
```

変更後:

```python
if connection is None:
    raise RuntimeError("google_health_active_connection_not_found")
if connection.status is not ConnectionStatus.ACTIVE:
    raise RuntimeError(
        "google_health_active_connection_not_found: "
        f"status={connection.status.value}"
    )
```

目的:

- run一覧だけで `revoked` / `expired` / `error` を判別できる
- DBを直接見なくても再認証が必要か判断できる

`last_error_message` まで例外に混ぜない。長くなり、秘密情報混入の検査対象が増えるため。

### Task 4: connection API のレスポンスは維持する

対象: `egograph/pipelines/api/google_health.py`

変更しない。

理由:

- すでに `status` と `last_error_message` を返している
- 診断情報は Task 2 で `last_error_message` に入る
- API契約を変える必要がない

### Task 5: テストを追加する

対象:

- `egograph/pipelines/tests/unit/google_health/test_client.py`
- `egograph/pipelines/tests/unit/google_health/test_workflow.py`

必要なテスト:

1. refresh 400 `invalid_grant` の診断保存

条件:

- token refresh response が 400
- body:

```json
{
  "error": "invalid_grant",
  "error_description": "Token has been expired or revoked."
}
```

期待:

- connection status が `revoked`
- `last_error_message` が以下を含む
  - `oauth_refresh_failed`
  - `status=400`
  - `error=invalid_grant`
- `error_description` の値 (`Token has been expired or revoked.`) を含まない
- token文字列を含まない

2. refresh 401 `invalid_client` の診断保存

期待:

- connection status が `error`
- `last_error_message` に `error=invalid_client`

3. refresh 500 は connection status を変えない

期待:

- connection status は `active` のまま
- 例外メッセージは `oauth_refresh_failed: status=500`

4. refresh 429 は connection status を変えない

期待:

- connection status は `active` のまま
- 例外メッセージは `oauth_refresh_failed: status=429`

5. 許可リスト外の `error` / `error_subtype` 値は要約から除外する

条件:

- refresh response が 400 で `error` / `error_subtype` が許可リスト (Task 1 と同一) 外の値
  - 自由文・文字種違反 (例: `refresh_token=secret; code=authz-code-123`)
  - 許可リスト外の identifier 形状値 (例: `authz-code-123`)。
    短い token や authorization code も identifier 形状になり得るため、
    形状ではなく許可リストで弾く

期待:

- 例外メッセージ・`last_error_message` ともに当該値を含まず、`oauth_refresh_failed: status=400` のみ残る

6. inactive connection の workflow error に status が入る

条件:

- repository が `ConnectionStatus.REVOKED` の connection を返す

期待:

```text
google_health_active_connection_not_found: status=revoked
```

## 完了条件

- refresh失敗時に `last_error_message` だけで OAuth error の種類が分かる
- token、authorization code、client secret がログ・DBに保存されない
- 一時的なOAuth障害やrate limitで connection が inactive にならない
- invalid_grant のときだけ connection が `revoked` になる
- 既存API契約を壊していない
- unit test が通る
- 再認証後、connection / smoke-test / `steps` + `sleep` manual run の結果を確認できる

## 実装順序

1. `_oauth_error_summary()` を追加
2. `_refresh_token()` の保存メッセージを差し替え
3. refresh failure の status 遷移を error body ベースに変更
4. workflow の inactive connection error を具体化
5. unit test 追加
6. test 実行
7. 本番再認証後に運用確認
