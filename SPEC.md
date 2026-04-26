# npb-stats-db 仕様書

## 概要

NPB公式サイト（npb.jp）から野球成績データをスクレイピングし、SQLiteデータベースに蓄積する個人用ツール。
週1回の手動実行を想定し、スナップショット方式で時系列データを管理する。

---

## ディレクトリ構成

```
npb-stats-db/
├── main.py              # スクレイパーエントリーポイント
├── web.py               # Webサーバーエントリーポイント
├── seed.py              # 歴代成績シードデータ投入（初回のみ）
├── scraper/
│   ├── __init__.py
│   ├── fetch.py         # HTML取得・キャッシュ
│   ├── parse.py         # HTML解析・DataFrame整形
│   └── store.py         # SQLite保存
├── templates/
│   ├── base.html        # 共通レイアウト（列ソートJS含む）
│   ├── index.html       # ダッシュボード
│   ├── stats.html       # 成績テーブル汎用ページ
│   ├── rankings.html    # ランキングページ
│   ├── trends.html      # 推移グラフページ
│   └── history.html     # 歴代成績ページ
├── sql/
│   ├── schema.sql       # テーブル定義
│   └── seeds.sql        # 歴代優勝データ（1950〜）
├── data/
│   └── npb.db           # SQLiteデータベース（自動生成）
└── cache/
    └── YYYYMMDD/        # 取得HTMLキャッシュ（日付別、自動生成）
```

---

## プログラム仕様

### main.py — エントリーポイント

**実行方法**

```bash
python main.py --year 2026
```

| 引数 | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `--year` | int | 2026 | 取得対象年度 |

**処理フロー**

1. `init_db()` でスキーマを初期化（`IF NOT EXISTS` のため冪等）
2. `TARGETS` リストを順に処理
   - URLを構築して `fetch()` でHTML取得
   - `parse_stats_date()` でHTML内の成績基準日を抽出
   - `upsert_snapshot()` でスナップショットをコミット（FK制約のため先行）
   - 対応する `parse_*()` でDataFrame化
   - 対応する `save_*()` でDBへ保存
3. 実行後に全テーブルの行数をコンソール出力

**TARGETS 定義**

| リーグ | URLパス | 取得内容 |
|--------|---------|---------|
| C | std_c | セ・リーグ勝敗表 |
| P | std_p | パ・リーグ勝敗表 |
| C | tmb_c | セ・リーグ チーム打撃 |
| P | tmb_p | パ・リーグ チーム打撃 |
| C | tmp_c | セ・リーグ チーム投手 |
| P | tmp_p | パ・リーグ チーム投手 |
| C | tmf_c | セ・リーグ チーム守備 |
| P | tmf_p | パ・リーグ チーム守備 |
| C | bat_c | セ・リーグ 個人打撃ランキング（規定打席以上） |
| P | bat_p | パ・リーグ 個人打撃ランキング（規定打席以上） |
| C | pit_c | セ・リーグ 個人投手ランキング（規定投球回以上） |
| P | pit_p | パ・リーグ 個人投手ランキング（規定投球回以上） |
| C | fld_c | セ・リーグ 個人守備ランキング（全ポジション） |
| P | fld_p | パ・リーグ 個人守備ランキング（全ポジション） |

---

### seed.py — 歴代成績シードデータ投入

**実行方法**

```bash
python seed.py   # 初回のみ実行
```

**処理内容**

1. `init_db()` でスキーマを初期化
2. `sql/seeds.sql` を読み込んで `season_results` テーブルに `INSERT OR IGNORE` で投入
3. 投入後の行数をコンソール出力

`INSERT OR IGNORE` のため、既存行は変更されない。データを修正したい場合は `sql/seeds.sql` を直接編集したうえで `seed.py` を再実行する（`OR IGNORE` によりすでに存在する年は更新されないため、修正した年のレコードを手動で DELETE してから再実行するか、`INSERT OR REPLACE` に書き換えて実行する）。

---

### scraper/fetch.py — HTML取得

**定数**

| 定数 | 値 | 説明 |
|------|----|------|
| `USER_AGENT` | `npb-personal-db/0.1 (...)` | リクエスト識別用UA |
| `SLEEP_SEC` | 2.5 | リクエスト間隔（秒） |
| `CACHE_DIR` | `{プロジェクトルート}/cache` | キャッシュ保存先 |

**`fetch(url, *, force=False) -> str`**

- 同日中は `cache/{YYYYMMDD}/{urlをファイル名変換}.html` のキャッシュを返す
- キャッシュなし（または `force=True`）の場合は `SLEEP_SEC` 待機後にHTTP GETを実行
- NPBサイトはShift_JIS系のため `apparent_encoding` で自動判定してUTF-8で保存
- タイムアウト30秒、HTTPエラーは `raise_for_status()` で例外送出

---

### scraper/parse.py — HTML解析

**共通ユーティリティ**

| 関数 | 説明 |
|------|------|
| `parse_stats_date(html)` | `「YYYY年M月D日 現在」` 形式の文字列からISO日付文字列（`YYYY-MM-DD`）を抽出 |
| `_split_player_team(name)` | `'佐藤輝明(神)'` を `('佐藤輝明', '神')` に分割。括弧なしの場合は `(name, None)` |
| `_to_numeric_cols(df, cols)` | 指定列を数値変換（変換不能値はNaN） |
| `_extract_rank(series)` | `'1位'` や `'1'` など数字を含む文字列から整数を抽出 |

**パース関数一覧**

| 関数 | 対象テーブル識別子 | 説明 |
|------|-----------------|------|
| `parse_standings(html, league)` | std_c / std_p | 勝敗表。7カラムを抽出し `league`, `rank` を付与 |
| `parse_team_batting(html, league)` | tmb_c / tmb_p | チーム打撃。`順位` 列がないテーブルを選択 |
| `parse_team_pitching(html, league)` | tmp_c / tmp_p | チーム投手。`防御率・投球回・自責点` を持つテーブルを選択 |
| `parse_team_fielding(html, league)` | tmf_c / tmf_p | チーム守備。列名に `「・」` 区切りが含まれる場合に動的マッピング |
| `parse_player_batting(html, league)` | bat_c / bat_p | 個人打撃。選手名からチームコードを分離 |
| `parse_player_pitching(html, league)` | pit_c / pit_p | 個人投手。先頭テーブル（規定投球回以上）のみ取得 |
| `parse_player_fielding(html, league)` | fld_c / fld_p | 個人守備。`<h5>` 見出しでポジション別にテーブルを分割し全結合。ポジションを英略称（1B/2B/3B/SS/OF/C/P）で付与 |

---

### scraper/store.py — データ保存

**定数**

| 定数 | パス |
|------|------|
| `DB_PATH` | `{プロジェクトルート}/data/npb.db` |
| `SCHEMA_PATH` | `{プロジェクトルート}/sql/schema.sql` |

**関数一覧**

| 関数 | 説明 |
|------|------|
| `get_conn()` | SQLite接続を返す。`PRAGMA foreign_keys = ON` を設定 |
| `init_db()` | `schema.sql` を実行してテーブルを初期化（冪等） |
| `upsert_snapshot(conn, year, stats_date)` | `snapshots` に `INSERT OR IGNORE` し、そのIDを返す。FK制約のため子テーブルのINSERT前に `commit()` を実施 |
| `save_standings(conn, snapshot_id, df)` | `team_standings` に保存 |
| `save_team_batting(conn, snapshot_id, df)` | `team_batting` に保存 |
| `save_team_pitching(conn, snapshot_id, df)` | `team_pitching` に保存 |
| `save_team_fielding(conn, snapshot_id, df)` | `team_fielding` に保存 |
| `save_player_batting(conn, snapshot_id, df)` | `player_batting` に保存 |
| `save_player_pitching(conn, snapshot_id, df)` | `player_pitching` に保存 |
| `save_player_fielding(conn, snapshot_id, df)` | `player_fielding` に保存 |

**保存処理の共通パターン**

各 `save_*` 関数は以下の手順で冪等な書き込みを実現する。

1. DataFrameに `snapshot_id` 列を追加
2. `DELETE FROM {table} WHERE snapshot_id=? AND league=?` で既存データを削除（再実行時の二重登録防止）
3. `DataFrame.to_sql(..., if_exists="append")` でINSERT

---

## テーブル仕様

### snapshots — スナップショット管理ハブ

成績取得日時を管理する親テーブル。全成績テーブルはこのテーブルの `id` を外部キーとして参照する。

| カラム | 型 | 制約 | 説明 |
|--------|----|------|------|
| id | INTEGER | PK, AUTOINCREMENT | スナップショットID |
| year | INTEGER | NOT NULL | 対象年度 |
| stats_date | DATE | NOT NULL | ページ記載の成績基準日 |
| fetched_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | DB登録日時 |

- `UNIQUE(year, stats_date)` — 同一基準日のデータは1レコードのみ保持

---

### team_standings — チーム勝敗表

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'`（セ）または `'P'`（パ） |
| rank | INTEGER | 順位 |
| team | TEXT | チーム名 |
| games | INTEGER | 試合数 |
| wins | INTEGER | 勝利 |
| losses | INTEGER | 敗北 |
| ties | INTEGER | 引分 |
| win_pct | REAL | 勝率 |
| games_behind | REAL | ゲーム差（首位は NULL） |

- PK: `(snapshot_id, league, team)`

---

### team_batting — チーム打撃成績

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| team | TEXT | チーム名 |
| batting_avg | REAL | 打率 |
| games | INTEGER | 試合数 |
| plate_appearances | INTEGER | 打席 |
| at_bats | INTEGER | 打数 |
| runs | INTEGER | 得点 |
| hits | INTEGER | 安打 |
| doubles | INTEGER | 二塁打 |
| triples | INTEGER | 三塁打 |
| home_runs | INTEGER | 本塁打 |
| total_bases | INTEGER | 塁打 |
| rbi | INTEGER | 打点 |
| stolen_bases | INTEGER | 盗塁 |
| caught_stealing | INTEGER | 盗塁刺 |
| sacrifice_hits | INTEGER | 犠打 |
| sacrifice_flies | INTEGER | 犠飛 |
| walks | INTEGER | 四球 |
| intentional_walks | INTEGER | 故意四球 |
| hit_by_pitch | INTEGER | 死球 |
| strikeouts | INTEGER | 三振 |
| grounded_into_dp | INTEGER | 併殺打 |
| slugging_pct | REAL | 長打率 |
| on_base_pct | REAL | 出塁率 |

- PK: `(snapshot_id, league, team)`

---

### team_pitching — チーム投手成績

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| team | TEXT | チーム名 |
| era | REAL | 防御率 |
| games | INTEGER | 試合数 |
| wins | INTEGER | 勝利 |
| losses | INTEGER | 敗北 |
| saves | INTEGER | セーブ |
| holds | INTEGER | ホールド |
| hold_points | INTEGER | ホールドポイント（HP） |
| complete_games | INTEGER | 完投 |
| shutouts | INTEGER | 完封勝 |
| no_walks | INTEGER | 無四球 |
| win_pct | REAL | 勝率 |
| batters_faced | INTEGER | 対戦打者数 |
| innings_pitched | REAL | 投球回 |
| hits | INTEGER | 被安打 |
| home_runs | INTEGER | 被本塁打 |
| walks | INTEGER | 四球 |
| intentional_walks | INTEGER | 故意四球 |
| hit_by_pitch | INTEGER | 死球 |
| strikeouts | INTEGER | 奪三振 |
| wild_pitches | INTEGER | 暴投 |
| balks | INTEGER | ボーク |
| runs | INTEGER | 失点 |
| earned_runs | INTEGER | 自責点 |

- PK: `(snapshot_id, league, team)`

---

### team_fielding — チーム守備成績

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| team | TEXT | チーム名 |
| fielding_avg | REAL | 守備率 |
| games | INTEGER | 試合数 |
| chances | INTEGER | 守備機会 |
| putouts | INTEGER | 刺殺 |
| assists | INTEGER | 補殺 |
| errors | INTEGER | 失策 |
| double_plays_participated | INTEGER | 併殺参加 |
| double_plays_team | INTEGER | 球団併殺 |
| passed_balls | INTEGER | 捕逸 |

- PK: `(snapshot_id, league, team)`

---

### player_batting — 個人打撃成績（規定打席以上）

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| player | TEXT | 選手名 |
| team | TEXT | チームコード（例: `神`, `巨`） |
| rank | INTEGER | 打率ランキング順位 |
| batting_avg | REAL | 打率 |
| games | INTEGER | 試合数 |
| plate_appearances | INTEGER | 打席 |
| at_bats | INTEGER | 打数 |
| runs | INTEGER | 得点 |
| hits | INTEGER | 安打 |
| doubles | INTEGER | 二塁打 |
| triples | INTEGER | 三塁打 |
| home_runs | INTEGER | 本塁打 |
| total_bases | INTEGER | 塁打 |
| rbi | INTEGER | 打点 |
| stolen_bases | INTEGER | 盗塁 |
| caught_stealing | INTEGER | 盗塁刺 |
| sacrifice_hits | INTEGER | 犠打 |
| sacrifice_flies | INTEGER | 犠飛 |
| walks | INTEGER | 四球 |
| intentional_walks | INTEGER | 故意四球 |
| hit_by_pitch | INTEGER | 死球 |
| strikeouts | INTEGER | 三振 |
| grounded_into_dp | INTEGER | 併殺打 |
| slugging_pct | REAL | 長打率 |
| on_base_pct | REAL | 出塁率 |

- PK: `(snapshot_id, league, player)`

---

### player_pitching — 個人投手成績（規定投球回以上）

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| player | TEXT | 選手名 |
| team | TEXT | チームコード |
| rank | INTEGER | 防御率ランキング順位 |
| era | REAL | 防御率 |
| games | INTEGER | 登板数 |
| wins | INTEGER | 勝利 |
| losses | INTEGER | 敗北 |
| saves | INTEGER | セーブ |
| holds | INTEGER | ホールド |
| hold_points | INTEGER | ホールドポイント（HP） |
| complete_games | INTEGER | 完投 |
| shutouts | INTEGER | 完封勝 |
| no_walks | INTEGER | 無四球 |
| win_pct | REAL | 勝率 |
| batters_faced | INTEGER | 対戦打者数 |
| innings_pitched | REAL | 投球回 |
| hits | INTEGER | 被安打 |
| home_runs | INTEGER | 被本塁打 |
| walks | INTEGER | 四球 |
| intentional_walks | INTEGER | 故意四球 |
| hit_by_pitch | INTEGER | 死球 |
| strikeouts | INTEGER | 奪三振 |
| wild_pitches | INTEGER | 暴投 |
| balks | INTEGER | ボーク |
| runs | INTEGER | 失点 |
| earned_runs | INTEGER | 自責点 |

- PK: `(snapshot_id, league, player)`

---

### player_fielding — 個人守備成績

| カラム | 型 | 説明 |
|--------|----|------|
| snapshot_id | INTEGER | FK → snapshots.id |
| league | TEXT | `'C'` または `'P'` |
| position | TEXT | 守備位置（英略称: 1B / 2B / 3B / SS / OF / C / P） |
| player | TEXT | 選手名 |
| team | TEXT | チームコード |
| rank | INTEGER | 守備率ランキング順位 |
| fielding_avg | REAL | 守備率 |
| games | INTEGER | 試合数 |
| putouts | INTEGER | 刺殺 |
| assists | INTEGER | 補殺 |
| errors | INTEGER | 失策 |
| double_plays | INTEGER | 併殺 |
| passed_balls | INTEGER | 捕逸（捕手のみ） |

- PK: `(snapshot_id, league, position, player)`

---

### season_results — 歴代シーズン成績

スクレイピングとは独立した静的参照テーブル。`seed.py` によって `sql/seeds.sql` から投入する。

| カラム | 型 | 説明 |
|--------|----|------|
| year | INTEGER | PK。シーズン年度 |
| central_champion | TEXT | セ・リーグ優勝チーム |
| pacific_champion | TEXT | パ・リーグ優勝チーム |
| cs_central_winner | TEXT | CSセ・リーグ勝者（2007年〜、NULL = CS未開催） |
| cs_pacific_winner | TEXT | CSパ・リーグ勝者（2007年〜、NULL = CS未開催） |
| japan_series_winner | TEXT | 日本シリーズ優勝チーム |
| notes | TEXT | 当時のチーム名・備考 |

**チーム名の表記規則**

現フランチャイズ名に統一して格納する。当時の名称は `notes` に記載。

| 現名称 | 主な前身チーム |
|--------|--------------|
| ソフトバンク | 南海ホークス → 福岡ダイエーホークス |
| 西武 | 西鉄ライオンズ → 太平洋C → クラウンライター → 西武 |
| オリックス | 阪急ブレーブス・大阪近鉄バファローズ → 各オリックスチーム |
| ロッテ | 毎日オリオンズ → 大毎 → ロッテオリオンズ |
| 日本ハム | 東映フライヤーズ → 日拓ホーム → 日本ハム |
| DeNA | 大洋ホエールズ → 横浜大洋 → 横浜ベイスターズ |
| ヤクルト | 国鉄スワローズ → ヤクルトスワローズ |
| 松竹 | 松竹ロビンス（1952年解散、現存せず） |

---

## テーブル関連図

```
snapshots (1)
    └── (N) team_standings
    └── (N) team_batting
    └── (N) team_pitching
    └── (N) team_fielding
    └── (N) player_batting
    └── (N) player_pitching
    └── (N) player_fielding

season_results  ← seeds.sql から独立投入（snapshots との FK なし）
```

スクレイピング系テーブルは `snapshot_id` で `snapshots` を参照する。
同一 `stats_date` のデータが複数回実行された場合は DELETE → INSERT で上書きされる（再実行安全）。
`season_results` は静的参照テーブルのため、スナップショット管理とは独立している。

---

## Webサーバー仕様

### web.py — Flaskアプリ

**起動方法**

```bash
python web.py
# → http://localhost:5000
```

**依存ライブラリ**

- Flask >= 3.0（サーバー本体）
- Chart.js 4.4.3（CDN、推移グラフのみ読み込み）

**ページ一覧**

| URL | ページ名 | 説明 |
|-----|---------|------|
| `/` | ダッシュボード | DB概要 + セ/パ両リーグ順位表（順位変動付き） |
| `/standings` | 勝敗表 | リーグ別 全カラム表示 |
| `/team/batting` | チーム打撃 | 打率降順 |
| `/team/pitching` | チーム投手 | 防御率昇順 |
| `/team/fielding` | チーム守備 | 守備率降順 |
| `/player/batting` | 個人打撃 | 打率ランキング順（規定打席以上） |
| `/player/pitching` | 個人投手 | 防御率ランキング順（規定投球回以上） |
| `/player/fielding` | 個人守備 | 順位・ポジション順（ポジションフィルタあり） |
| `/rankings` | ランキング | 打率/防御率/奪三振/勝利数/K9 の各トップ10 |
| `/trends` | 推移グラフ | 打率・防御率の推移折れ線グラフ（Chart.js） |
| `/history` | 歴代成績 | 1950年〜の年度別優勝チーム + チーム別優勝回数 |

**共通UIコントロール**

全ページ共通で以下を提供する。

- スナップショット選択ドロップダウン（`?snapshot_id=N`、未指定時は最新）
- セ/パリーグ切替ボタン（`?league=C` または `?league=P`）、デフォルトはパ・リーグ
- 個人守備ページのみポジションフィルタボタンを追加表示
- 全テーブルのヘッダークリックで列ソート（昇順/降順トグル）
  - 数値列は数値比較、文字列列は日本語ロケール比較
  - 欠損値（`-`）は常に末尾に表示
  - 現在のソート方向をヘッダーに `↑` / `↓` で表示

**主要ヘルパー関数**

| 関数 | 説明 |
|------|------|
| `get_prev_snapshot_id(current_id)` | 指定IDの直前スナップショットIDを返す |
| `standings_with_rank_change(snapshot_id, league)` | 直前スナップショットとの順位差（`rank_change`）を付加した勝敗表データ（`list[dict]`）を返す。正値＝順位上昇、負値＝順位下降、`None`＝比較対象なし |
| `_trend_json(table, stat_col, league)` | 最新スナップショット上位10選手の全スナップショット推移をChart.js形式のJSONで返す。防御率は昇順で選手を選択 |

**ランキングページの集計クエリ**

| セクション | 抽出条件 |
|-----------|---------|
| 打率トップ10 | `player_batting` を `batting_avg DESC LIMIT 10` |
| 防御率トップ10 | `player_pitching` を `era ASC LIMIT 10` |
| 奪三振ランキング | `player_pitching` を `strikeouts DESC LIMIT 10`（`innings_pitched > 0`） |
| 勝利数ランキング | `player_pitching` を `wins DESC LIMIT 10` |
| K/9ランキング | `ROUND(strikeouts * 9.0 / innings_pitched, 2)` を計算して `k_per_9 DESC LIMIT 10`（`innings_pitched > 0`） |

**推移グラフの仕様**

- 最新スナップショットの上位10選手を対象選手として固定
- 全スナップショットにわたって各選手の指定スタッツを取得しプロット
- データが存在しない日付はNaN（`spanGaps: false` で線を繋がない）
- 防御率グラフはY軸反転（低い方が上 = 優秀）

**歴代成績ページの仕様**

- 上段：セ優勝回数 / パ優勝回数 / 日本シリーズ優勝回数をバーチャート付き一覧で表示
- 下段：年度別テーブル（降順表示、列クリックで並び替え可）
  - CS列は2007年以降のみ表示値あり、それ以前は `-`
  - CSセ列・CSパ列・日本一列でリーグ優勝チーム以外が制覇した年（下克上）を赤字で強調

---

## 運用仕様

| 項目 | 内容 |
|------|------|
| スクレイパー実行頻度 | 毎日自動（Cloud Scheduler: 毎朝8:00 JST） |
| リクエスト間隔 | 2.5秒 |
| キャッシュ有効期間 | 当日中（`cache/YYYYMMDD/` 単位） |
| データ利用制限 | NPB公式利用規約に基づき個人ローカル利用に限定 |
| DBファイル | GCS: `gs://amplified-alpha-330603-npb-stats/npb.db`（SQLite3） |
| Webサーバー | Cloud Run Service（Google OAuth 認証付き） |
| シードデータ | `python seed.py` で初回のみ投入。修正は `sql/seeds.sql` を直接編集 |

---

## GCP 構成

### アーキテクチャ

```text
Cloud Scheduler（毎朝 8:00 JST）
    → Cloud Run Job（npb-stats-job）
        ① GCS から npb.db をダウンロード
        ② python main.py --year <当年> を実行（NPB スクレイピング）
        ③ 更新した npb.db を GCS にアップロード

GCS（npb.db 永続ストレージ）
    ↓ 毎朝 9:00 JST（APScheduler）
Cloud Run Service（npb-stats-web）
    Flask + Google OAuth 認証
```

### GCP リソース一覧

| リソース | 名前 | 説明 |
| -------- | ---- | ---- |
| GCS バケット | `amplified-alpha-330603-npb-stats` | DB 永続ストレージ |
| Artifact Registry | `npb-stats`（asia-northeast1） | Docker イメージ管理 |
| Cloud Run Job | `npb-stats-job` | スクレイパー実行コンテナ |
| Cloud Run Service | `npb-stats-web` | Web ビューア |
| Cloud Scheduler | `npb-stats-job-trigger` | 毎朝8:00 JST に Job を起動 |
| Secret Manager | `npb-web-client-id` / `npb-web-client-secret` / `npb-web-secret-key` | OAuth 認証情報 |
| サービスアカウント | `npb-stats-job@amplified-alpha-330603.iam.gserviceaccount.com` | Job・Service 共用 |

### Cloud Run Job（スクレイパー）

- **エントリーポイント**: `gcp_job.py`
- **Dockerfile**: `Dockerfile`（CMD: `python gcp_job.py`）
- **環境変数**: `GCS_BUCKET`, `GCS_DB_BLOB`
- **対象年度**: `datetime.now().year` で自動取得（`--year` 引数で上書き可）

### Cloud Run Service（Web ビューア）

- **エントリーポイント**: `web.py`
- **Dockerfile**: `Dockerfile.web`（gunicorn, 1 worker / 8 threads）
- **環境変数**: `NPB_DB_PATH=/tmp/npb.db`, `GCS_BUCKET`, `ALLOWED_EMAIL`
- **シークレット**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FLASK_SECRET_KEY`（Secret Manager）
- **DB パス**: `/tmp/npb.db`（コンテナ内一時領域）

#### DB 更新フロー

| タイミング | 処理 |
| --------- | ---- |
| コンテナ起動時 | GCS から `/tmp/npb.db` をダウンロード |
| 毎朝 9:00 JST | APScheduler が GCS から最新 DB を再ダウンロード |

### 認証

- Cloud Run Service は `--allow-unauthenticated`（ブラウザアクセス可）
- Flask 内で **Google OAuth 2.0**（`authlib` 使用）
- `ALLOWED_EMAIL` 環境変数で許可アカウントを制限（現在: `mfujishiro49321@gmail.com`）
- ローカル開発時は `GOOGLE_CLIENT_ID` 未設定のため認証スキップ

### デプロイスクリプト

| スクリプト | 用途 |
| --------- | ---- |
| `gcp/setup.sh` | GCP リソースの初回セットアップ |
| `gcp/deploy_web.sh` | Web サービスのビルド・デプロイ |
| `gcp/update.sh` | スクレイパーイメージの更新・Job への反映 |

#### Web サービスのデプロイ（コード変更時）

```bash
bash gcp/deploy_web.sh
```

#### スクレイパーのデプロイ（コード変更時）

```bash
bash gcp/update.sh
```

#### 初回セットアップ時の Secret Manager 登録

```bash
echo -n "CLIENT_ID"     | gcloud secrets create npb-web-client-id     --data-file=- --project=amplified-alpha-330603
echo -n "CLIENT_SECRET" | gcloud secrets create npb-web-client-secret --data-file=- --project=amplified-alpha-330603
python3 -c "import secrets; print(secrets.token_hex(32), end='')" \
  | gcloud secrets create npb-web-secret-key --data-file=- --project=amplified-alpha-330603
```
