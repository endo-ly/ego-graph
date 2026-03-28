# 技術選定レポート: YouTube視聴履歴収集

## 1. 概要

EgoGraphプロジェクトにおいて、YouTube視聴履歴を1日単位で自動収集するための技術選定レポートです。
実行環境は **GitHub Actions（定期実行）** を前提とし、「データ完全性」「リアルタイム性」「将来の拡張性」「実装コスト」の観点から比較・推奨を行います。

**背景**: YouTube Data APIでの視聴履歴取得機能は2016年9月12日に廃止されており、公式APIでの直接取得は不可能。

（調査実施時期: 2026年1月）

---

## 2. 候補手法比較

| 手法 | データ取得頻度 | データ完全性 | 実装難易度 | 拡張性 | ToS準拠 | 推奨度 |
|:---|:---|:---|:---|:---|:---|:---|
| **A. Playwright + MyActivity** | 1日単位 | ◎ 完全 | 中 | ◎ 他サービス対応可 | △ グレー | ★★★★★ |
| B. Data Portability API | 14日に1回 | ◎ 完全 | 中 | ○ | ◎ 公式 | ★★★★☆ |
| C. YouTube Data API v3 (HL) | - | × 廃止済み | - | - | ◎ 公式 | ☆☆☆☆☆ |
| D. ブラウザ拡張機能 | リアルタイム | ◎ 完全 | 高 | ○ | ◎ 正当 | ★★★★☆ |
| E. Google Takeout (手動) | 手動のみ | ◎ 完全 | - | × | ◎ 公式 | ★☆☆☆☆ |

---

## 3. 詳細評価

### A. Playwright + Google MyActivity スクレイピング（最終選定）

**概要**: Playwrightを使用してmyactivity.google.comをスクレイピングし、認証済みCookieでアクセスしてYouTube視聴履歴を取得する手法。

**強み**:
- **1日単位での自動収集が可能**: GitHub Actionsで定期実行（Spotifyと同様の運用）
- **データの完全性**: MyActivityに記録されている全履歴が取得可能
- **統一されたデータソース**: YouTube以外のGoogleサービス（Chrome閲覧履歴、Google検索履歴、Google Maps履歴など）も同じ実装パターンで対応可能
- **標準化されたスキーマ**: Data Portability APIのActivity Schemaに準拠したデータ構造
- **既存実装の参考**: `google_takeout_parser`などのOSSライブラリが存在

**弱点・リスク**:
- **Cookie管理**: 数ヶ月ごとにCookieの再取得が必要（運用負荷）
- **ページ構造変更**: GoogleがMyActivityのHTML構造を変更した場合、実装修正が必要
- **レート制限・ブロックリスク**: Bot検知によるアクセス制限の可能性（対策: User-Agent正規化、リクエスト間隔調整）
- **ToS違反の可能性**: スクレイピング自体はグレーゾーン（個人利用目的であれば実質的な問題は少ない）

**技術的要件**:
- Playwright + Chromium（GitHub Actions対応）
- Cookie認証（GitHub Secrets管理）
- 無限スクロール処理
- HTML/JSONパーサー

---

### B. Google Data Portability API

**概要**: Googleの公式Data Portability APIを使用してMyActivityデータをアーカイブ形式でエクスポートする手法。

**強み**:
- **公式API**: ToS準拠で安全
- **データの完全性**: 全期間の履歴が取得可能
- **標準化されたフォーマット**: JSON/HTML形式でのエクスポート

**弱点**:
- **14日間隔制限**: 同一リソースのエクスポートは14日に1回まで
- **アーカイブ生成時間**: 数分〜数日かかる（リアルタイム性なし）
- **署名付きURL有効期限**: 6時間（取得後速やかにダウンロード必須）
- **1日単位収集との不適合**: EgoGraphの「Personal Data Warehouse」コンセプトに不向き

**評価**: 公式APIである点は魅力的だが、14日間隔制限により日次収集ができないため、本プロジェクトの要件を満たさない。

---

### C. YouTube Data API v3 (プレイリスト経由)

**概要**: YouTube Data API v3を使用して、"HL"（Watch History）プレイリストから視聴履歴を取得する手法。

**廃止状況**:
- **2016年9月12日に廃止**: `playlistItems.list`で"HL"を指定しても常に空のリストを返す
- **完全にアクセス不可**: 視聴履歴データは一切取得できない

**評価**: API自体は呼び出せるが、レスポンスは常に空のため**実質的に使用不可**。この手法は選択肢から除外。

---

### D. ブラウザ拡張機能

**概要**: Chrome/Firefox拡張機能を開発し、ブラウザでの視聴と同時にIndexedDBに履歴を保存する手法。

**強み**:
- **ToS準拠**: 正当なブラウザ使用であり法的リスクなし
- **リアルタイム収集**: 視聴と同時に記録
- **安定性**: YouTube側の変更に強い
- **既存実装の参考**: Watchmarker for Youtubeなどの先行事例

**弱点**:
- **開発コスト**: 拡張機能開発の初期投資が大きい
- **プラットフォーム制限**: ブラウザでの視聴のみ対応（モバイルアプリ非対応）
- **自動化の制約**: ブラウザ起動が前提（GitHub Actionsでの完全自動化は困難）

**評価**: 長期的には最も安定した手法だが、初期実装コストが高い。Phase 2の選択肢として有力。

---

### E. Google Takeout（手動エクスポート）

**概要**: https://takeout.google.com から手動でデータをエクスポートする方法。

**評価**: 自動化不可のため本プロジェクトでは採用不可。初期データのバックフィル用途のみ。

---

## 4. 最終選定とアーキテクチャ決定

### 選定: **方法A（Playwright + Google MyActivity）**

**理由**:
1. **要件適合性**: 1日単位での自動収集が可能
2. **データ完全性**: 全履歴が取得可能
3. **将来の拡張性**: YouTube以外のGoogleサービス（Chrome、検索、Maps）も同じ実装パターンで対応可能
4. **実装コスト**: 既存のSpotify収集パイプラインと同様の設計で実現可能

### アーキテクチャ上の決定

#### データソース選択: youtube.com/feed/history vs myactivity.google.com

当初はyoutube.com/feed/historyからのスクレイピングも検討したが、以下の理由で**myactivity.google.com**を選定：

| 比較項目 | youtube.com/feed/history | myactivity.google.com | 選定理由 |
|---------|-------------------------|----------------------|---------|
| データ範囲 | YouTube視聴履歴のみ | 全Googleサービス | 将来的な拡張性 |
| データ構造 | YouTube固有 | 統一されたActivity Schema | 標準化 |
| フィルタリング | なし | サービス別フィルタ可能 | 実装の柔軟性 |
| 既存参考実装 | なし | google_takeout_parser等 | 開発効率 |

**結論**: myactivity.google.comからのスクレイピングにより、YouTube視聴履歴だけでなく、将来的にはChrome閲覧履歴、Google検索履歴、Google Maps履歴なども統一されたパイプラインで収集可能。

#### 実装構造

```
ingest/google_activity/
├── collector.py          # MyActivityスクレイパー（共通）
├── parsers/
│   ├── youtube.py       # YouTube Activity → Parquet
│   ├── search.py        # Search Activity → Parquet（将来）
│   └── chrome.py        # Chrome Activity → Parquet（将来）
├── storage.py           # R2保存（Spotify共通）
└── schema.py            # 統一スキーマ定義
```

---

## 5. 段階的実装計画

### Phase 1: YouTube視聴履歴収集（優先実装）
- MyActivityからのYouTube履歴スクレイピング
- GitHub Actions定期実行（1日2回）
- Cookie管理・認証フロー確立

### Phase 2: 他Googleサービス対応（将来拡張）
- Chrome閲覧履歴
- Google検索履歴
- Google Maps位置履歴
- Google Assistant履歴

### Phase 3: 安定化施策（長期運用）
- ブラウザ拡張機能の開発（より安定した収集基盤）
- Playwrightスクレイピングのバックアップとして並行稼働

---

## 6. リスク管理

### Cookie有効期限管理
- 毎回実行時に認証状態をチェック
- 失敗時の通知機構（Slack/Email）
- GitHub Secretsでの安全な保管

### レート制限対策
- リクエスト間隔: 2-5秒（ランダム化）
- 1実行あたりの取得件数制限: 50-100件
- User-Agent正規化、headlessフラグ隠蔽

### ToS違反リスク低減
- 個人利用目的を明確化
- 適切なリクエスト間隔の確保
- Googleのrobots.txt尊重

---

## 7. 参考資料

### 公式ドキュメント
- [Google Data Portability API](https://developers.google.com/data-portability)
- [My Activity Schema Reference](https://developers.google.com/data-portability/schema-reference/my_activity)
- [YouTube Data API v3](https://developers.google.com/youtube/v3/docs)

### オープンソース実装
- [google_takeout_parser](https://github.com/seanbreckenridge/google_takeout_parser) - MyActivityパーサーの参考実装
- [youtube-watchmarker](https://github.com/sniklaus/youtube-watchmarker) - ブラウザ拡張機能の先行事例
- [google-activity-parser](https://github.com/paulnta/google-activity-parser) - HTMLパーサーの実装例

### 技術記事
- [Playwright vs Selenium 2026](https://brightdata.com/blog/web-data/playwright-vs-selenium)
- [Handling Cookies in Playwright Python](https://www.webscrapinghq.com/blog/handling-cookies-in-playwright-python)

---

## 8. 結論

**最終選定: Playwright + Google MyActivity スクレイピング**

YouTube視聴履歴の1日単位での自動収集を実現しつつ、将来的には他のGoogleサービスデータも統一されたパイプラインで収集可能な拡張性の高いアーキテクチャを採用する。

Data Portability APIの14日間隔制限や、YouTube Data APIの2週間制限といった公式APIの制約を回避し、「Personal Data Warehouse」としてのEgoGraphのコンセプトに最も適合する手法である。

個人利用目的でのスクレイピングはグレーゾーンであるが、適切なレート制限とCookie管理により、実用的かつ持続可能な運用が可能と判断する。
