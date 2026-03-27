# Spotify データソース

## データタイプ判定

- **タイプ**: 構造化ログ
- **主用途**: DuckDB分析

---

## 1. 概要

### 1.1 データの性質

| 項目 | 値 |
|---|---|
| **タイプ** | 構造化ログ |
| **粒度** | Atomic (再生イベント単位) |
| **更新頻度** | 日次 |
| **センシティビティ** | Low |
| **主な用途** | 分析（DuckDB） |

### 1.2 概要説明

Spotifyの再生履歴を取り込み、分析（Analytics）を実現する。Cloudflare R2 + DuckDB ですべての再生ログをParquet形式で保存し、正確な集計を行う。

> **Note**: 日次要約のベクトル化・Qdrantでの意味検索は将来拡張機能として検討中（未実装）。

---

## 2. データフロー全体像

```
[Spotify API]
         ↓
    [Collector: OAuth認証でデータ取得]
         ↓
    [Transform: 正規化・マスターデータ結合]
         ↓
    [Storage: R2へ保存]
         ├── Raw JSON (監査用)
         ├── Events Parquet (再生ログ)
         └── Master Parquet (楽曲・アーティスト)
         ↓
    [DuckDB: マウント・分析]
```

---

## 3. 入力データ構造

### 3.1 データ取得元

| 項目 | 説明 |
|---|---|
| **取得方法** | API |
| **API** | Spotify Web API |
| **認証方式** | OAuth 2.0 |
| **必要なスコープ** | `user-read-recently-played`, `user-library-read` |

### 3.2 入力スキーマ

#### Recently Played API

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `played_at` | datetime | Yes | 再生時刻 (ISO8601) | `"2024-01-01T12:00:00Z"` |
| `track.id` | string | Yes | トラックID | `"4iV5W9uYEdYUVa79Axb7Rh"` |
| `track.name` | string | Yes | トラック名 | `"Bohemian Rhapsody"` |
| `track.duration_ms` | int | Yes | 再生時間 (ms) | `354000` |
| `track.popularity` | int | No | 人気度 (0-100) | `85` |
| `track.explicit` | boolean | No | 明示的歌詞フラグ | `false` |
| `track.album.id` | string | Yes | アルバムID | `"1GbtB4zTnAsVwhEM7r4dmb"` |
| `track.album.name` | string | Yes | アルバム名 | `"A Night at the Opera"` |
| `track.artists[].id` | string[] | Yes | アーティストID配列 | `["1dfeR4HA"`
`WKnWQqKi"]` |
| `track.artists[].name` | string[] | Yes | アーティスト名配列 | `["Queen"]` |

#### Track Master API

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `id` | string | Yes | トラックID | `"4iV5W9uYEdYUVa79Axb7Rh"` |
| `name` | string | Yes | トラック名 | `"Bohemian Rhapsody"` |
| `artist_ids` | string[] | Yes | アーティストID配列 | `["1dfeR4HaWKnWQqKi"]` |
| `artist_names` | string[] | Yes | アーティスト名配列 | `["Queen"]` |
| `album_id` | string | Yes | アルバムID | `"1GbtB4zTnAsVwhEM7r4dmb"` |
| `album_name` | string | Yes | アルバム名 | `"A Night at the Opera"` |
| `duration_ms` | int | Yes | 再生時間 (ms) | `354000` |
| `popularity` | int | No | 人気度 (0-100) | `85` |
| `explicit` | boolean | No | 明示的歌詞フラグ | `false` |
| `preview_url` | string | No | プレビューURL | `"https://..."` |

#### Artist Master API

| フィールド名 | 型 | 必須 | 説明 | 例 |
|---|---|---|---|---|
| `id` | string | Yes | アーティストID | `"1dfeR4HaWKnWQqKi"` |
| `name` | string | Yes | アーティスト名 | `"Queen"` |
| `genres` | string[] | No | ジャンル配列 | `["rock", "classic rock"]` |
| `popularity` | int | No | 人気度 (0-100) | `92` |
| `followers.total` | int | No | フォロワー数 | `25000000` |

---

## 4. Parquetスキーマ

### 4.1 Spotify Plays (Events)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `play_id` | STRING | 一意識別子 | システム生成 (UUID) |
| `track_id` | STRING | トラックID | `track.id` |
| `track_name` | STRING | トラック名 | `track.name` |
| `album_id` | STRING | アルバムID | `track.album.id` |
| `album_name` | STRING | アルバム名 | `track.album.name` |
| `artist_ids` | VARCHAR[] | アーティストID配列 | `track.artists[].id` |
| `artist_names` | VARCHAR[] | アーティスト名配列 | `track.artists[].name` |
| `duration_ms` | INT | 再生時間 (ms) | `track.duration_ms` |
| `played_at_utc` | TIMESTAMP | 再生時刻 (UTC) | `played_at` (ISO8601) |
| `ingested_at_utc` | TIMESTAMP | 取り込み時刻 (UTC) | システム生成 |

### 4.2 Spotify Tracks (Master)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `track_id` | STRING | トラックID | `id` |
| `track_name` | STRING | トラック名 | `name` |
| `artist_ids` | VARCHAR[] | アーティストID配列 | `artist_ids` |
| `artist_names` | VARCHAR[] | アーティスト名配列 | `artist_names` |
| `album_id` | STRING | アルバムID | `album_id` |
| `album_name` | STRING | アルバム名 | `album_name` |
| `duration_ms` | INT | 再生時間 (ms) | `duration_ms` |
| `popularity` | INT | 人気度 | `popularity` |
| `explicit` | BOOLEAN | 明示的フラグ | `explicit` |
| `preview_url` | STRING | プレビューURL | `preview_url` |
| `updated_at_utc` | TIMESTAMP | 更新時刻 (UTC) | システム生成 |

### 4.3 Spotify Artists (Master)

| 列名 | 型 | 説明 | 変換元 |
|---|---|---|---|
| `artist_id` | STRING | アーティストID | `id` |
| `artist_name` | STRING | アーティスト名 | `name` |
| `genres` | VARCHAR[] | ジャンル配列 | `genres` |
| `popularity` | INT | 人気度 | `popularity` |
| `followers_total` | INT | フォロワー数 | `followers.total` |
| `updated_at_utc` | TIMESTAMP | 更新時刻 (UTC) | システム生成 |

### 4.4 パーティション

- **パーティションキー**: `year`, `month`
- **理由**: 時系列データのクエリ効率向上

---

## 5. R2保存先

### 5.1 ディレクトリ構造

```text
s3://ego-graph/
  ├── events/spotify/
  │   └── plays/
  │       └── year=YYYY/
  │           └── month=MM/
  │               └── {uuid}.parquet
  ├── master/spotify/
  │   ├── tracks/
  │   │   └── year=YYYY/
  │   │       └── month=MM/
  │   │           └── {uuid}.parquet
  │   └── artists/
  │       └── {uuid}.parquet
  ├── raw/spotify/
  │   └── {timestamp}.json
  └── state/
      └── spotify_ingest_state.json
```

### 5.2 保存パス例

- **Plays (Events)**: `s3://ego-graph/events/spotify/plays/year=2024/month=01/abc123.parquet`
- **Tracks (Master)**: `s3://ego-graph/master/spotify/tracks/year=2024/month=01/def456.parquet`
- **Artists (Master)**: `s3://ego-graph/master/spotify/artists/ghi789.parquet`
- **Raw**: `s3://ego-graph/raw/spotify/2024-01-01T120000.json`
- **State**: `s3://ego-graph/state/spotify_ingest_state.json`

---

## 6. 検索・活用シナリオ

- **定量分析**: 再生回数、アーティスト別集計、時間帯別傾向
- **定性要約**: 最近の聴取傾向、お気に入りアーティストの把握
- **事実列挙**: 特定期間のセットリスト、特定曲の再生履歴
- **将来拡張**: 日次要約のベクトル化・Qdrantによる意味検索（「雰囲気」や「ムード」での検索）

---
## 11. 実装時の考慮事項

### 11.1 エッジケース

- **Audio Features**: Spotify API で提供終了しているため取得しない
- **Genres**: アーティストに依存するため空配列が多い。集計時は "unknown" として扱う
- **Preview URL**: 権利都合で null が多い。UI 側で存在チェックが必須

### 11.2 制約・制限

- Recently Played API は直近50件のみ取得可能
- 増分取り込みは `played_at` の最大値をカーソルとして使用

### 11.3 将来拡張

- 日次要約の生成とQdrantへの保存
- 再生傾向に基づくレコメンデーション
- 他データソース（Location等）との相関分析

---

## 12. サンプルデータ

### 12.1 入力データ例 (Recently Played API)

```json
{
  "items": [
    {
      "played_at": "2024-01-01T12:00:00Z",
      "track": {
        "id": "4iV5W9uYEdYUVa79Axb7Rh",
        "name": "Bohemian Rhapsody",
        "duration_ms": 354000,
        "popularity": 85,
        "explicit": false,
        "album": {
          "id": "1GbtB4zTnAsVwhEM7r4dmb",
          "name": "A Night at the Opera"
        },
        "artists": [
          {
            "id": "1dfeR4HaWKnWQqKi",
            "name": "Queen"
          }
        ]
      }
    }
  ]
}
```

### 12.2 Parquet行例 (Spotify Plays)

```json
{
  "play_id": "550e8400-e29b-41d4-a716-446655440000",
  "track_id": "4iV5W9uYEdYUVa79Axb7Rh",
  "track_name": "Bohemian Rhapsody",
  "album_id": "1GbtB4zTnAsVwhEM7r4dmb",
  "album_name": "A Night at the Opera",
  "artist_ids": ["1dfeR4HaWKnWQqKi"],
  "artist_names": ["Queen"],
  "duration_ms": 354000,
  "played_at_utc": "2024-01-01T12:00:00Z",
  "ingested_at_utc": "2024-01-01T13:00:00Z"
}
```

---

## 13. 次のステップ

### 実装状況

- [x] データ取得 (Recently Played)
- [x] Parquet保存 (Events + Master)
- [x] DuckDBマウント
- [x] テスト完了

### 未実装機能

- [ ] 日次要約の生成
- [ ] Qdrantへの保存（将来検討）
- [ ] Audio Features の代替手段調査

---

## 参考

- [Spotify Web API Documentation](https://developer.spotify.com/documentation/web-api)
- [Ingest 共通アーキテクチャ](./README.md)
- [データ戦略](../01-overview/data-strategy.md)
