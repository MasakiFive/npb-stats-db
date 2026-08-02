# npb-stats-db 仕様書

## 概要

NPB公式サイト（npb.jp）から野球成績データをスクレイピングし、SQLiteデータベースに蓄積する個人用ツール。
Cloud Run Job による毎日1回の自動実行を前提とし、スナップショット方式で時系列データを管理する。
ローカルでの手動実行（`python main.py`）も同じコードパスで行える。

---

## ディレクトリ構成

```
npb-stats-db/
├── main.py              # スクレイパーエントリーポイント
├── web.py               # Webサーバーエントリーポイント
├── seed.py              # 歴代成績シードデータ投入（初回のみ）
├── gcp_job.py           # Cloud Run Job エントリーポイント
├── scraper/
│   ├── __init__.py
│   ├── fetch.py         # HTML取得・キャッシュ
│   ├── parse.py         # HTML解析・DataFrame整形
│   └── store.py         # SQLite保存
├── templates/
│   ├── base.html                   # 共通レイアウト（列ソートJS含む）
│   ├── index.html                  # ダッシュボード
│   ├── stats.html                  # 成績テーブル汎用ページ
│   ├── rankings.html               # ランキングページ
│   ├── trends.html                 # 推移グラフページ
│   ├── history.html                # 歴代成績ページ
│   ├── hawks_batting.html          # ホークス試合別打撃成績
│   ├── hawks_ranking.html          # ホークス打撃ランキング
│   ├── hawks_pitching.html         # ホークス試合別投手成績
│   └── hawks_pitching_ranking.html # ホークス投手ランキング
├── sql/
│   ├── schema.sql       # テーブル定義
│   └── seeds.sql        # 歴代優勝データ（1950〜）
├── gcp/
│   ├── setup.sh         # GCPリソース初回セットアップ
│   ├── deploy_web.sh    # Webサービスデプロイ
│   └── update.sh        # スクレイパーイメージ更新
├── tests/
│   ├── conftest.py      # フィクスチャローダ・import パス設定
│   ├── test_parse.py    # パーサの回帰テスト
│   ├── test_store.py    # 保存・マイグレーションのテスト
│   ├── test_main.py     # scrape_hawks_games の統合テスト
│   └── fixtures/        # NPB公式ページの構造を模したHTML
├── Dockerfile           # Cloud Run Job 用（CMD: python gcp_job.py）
├── Dockerfile.web       # Cloud Run Service 用（CMD: gunicorn web:app）
├── requirements.txt     # 実行時依存
├── requirements-dev.txt # 実行時依存 + pytest
├── pytest.ini           # pytest 設定（testpaths=tests）
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

1. `init_db()` でスキーマを初期化・マイグレーション実行（冪等）
2. `TARGETS` リストを順に処理
   - URLを構築して `fetch()` でHTML取得
   - `parse_stats_date()` でHTML内の成績基準日を抽出
   - `upsert_snapshot()` でスナップショットをコミット（FK制約のため先行）
   - 対応する `parse_*()` でDataFrame化
   - 対応する `save_*()` でDBへ保存
3. `scrape_hawks_games(year, conn)` でホークス全試合のボックススコアを取得
   - 3〜10月の月別スケジュールページからホークス試合URLを抽出
   - 各ボックススコアから `parse_game_batting()` / `parse_game_pitching()` でDataFrame化
   - `save_game_batting()` / `save_game_pitching()` でDBへ保存
4. 実行後に全テーブルの行数をコンソール出力

**ホークス試合のスキップ条件**

`scrape_hawks_games()` は以下の順に判定し、該当する試合を取得対象から外す。

| 判定 | 条件 | ログ出力 |
| ---- | ---- | ------- |
| 未来の試合 | `game_date > today` | なし |
| 取得済み | `game_batting`（`walks IS NOT NULL`）と `game_pitching` の両方に行がある | なし |
| 中止試合 | `is_cancelled_game(box_html)` が真 | `中止のためスキップ` |

中止試合はDBに行が残らないため、翌日以降も毎回1回だけボックススコアを取得して
判定し直す。取得済み判定で `walks IS NOT NULL` を条件にしているのは、`walks` 列を
追加する前にスクレイプした試合を再取得させるため。

上記いずれにも該当せずパースに失敗した場合は `失敗: <例外メッセージ>` を出力して
次の試合へ進む（1試合の失敗で全体は止めない）。「打撃テーブルが見つかりません」が
出た場合は NPB 側のHTML構造が変わった可能性がある。

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
| `parse_schedule_game_urls(html, year)` | — | 月別スケジュールHTMLからホークス試合URL・日付・H/A・対戦相手を抽出。同一試合への重複リンクは1件に畳む |
| `is_cancelled_game(html)` | — | 中止試合のボックススコアページかを判定。`【雨天のため中止】` のように `【】` で囲まれた「中止」表記に限定して照合する（単なる部分一致だとページ内の別試合の告知を誤検知するため） |
| `parse_game_batting(html, home_away)` | — | ボックススコアHTMLからホークス打線のDataFrameを返す。打席結果列（1〜9）から本塁打数・打席数も算出 |
| `parse_game_pitching(html, home_away)` | — | ボックススコアHTMLからホークス投手陣のDataFrameを返す。投球回は NPB 表記（`5.2` = 5と2/3回）を `float` に変換 |
| `_parse_innings(val)` | — | NPB投球回表記（整数 or `N.1`/`N.2`）を浮動小数に変換するユーティリティ |

#### ボックススコアのテーブル順序

NPBボックススコア（`/scores/YYYY/MMDD/{away}-{home}-NN/box.html`）は以下の順でテーブルが並ぶ。

| テーブル | home_away='H' | home_away='A' |
| ------- | ------------ | ------------ |
| 打撃テーブル[0] | ホークス（ホーム） | 相手（ホーム） |
| 打撃テーブル[1] | 相手（アウェー） | ホークス（アウェー） |
| 投手テーブル[0] | ホークス（ホーム） | 相手（ホーム） |
| 投手テーブル[1] | 相手（アウェー） | ホークス（アウェー） |

中止試合および当日未実施の試合ではこれらのテーブルが存在せず、`parse_game_batting()` /
`parse_game_pitching()` は `ValueError` を送出する。中止試合は `is_cancelled_game()` で
事前に除外する。

---

### scraper/store.py — データ保存

**定数**

| 定数 | パス |
|------|------|
| `DB_PATH` | 環境変数 `NPB_DB_PATH`。未設定時は `{プロジェクトルート}/data/npb.db` |
| `SCHEMA_PATH` | `{プロジェクトルート}/sql/schema.sql` |

**関数一覧**

| 関数 | 説明 |
|------|------|
| `get_conn()` | SQLite接続を返す。`PRAGMA foreign_keys = ON` を設定 |
| `init_db()` | `schema.sql` を実行してテーブルを初期化し、`_migrate()` でカラム追加を適用（冪等） |
| `_migrate(conn)` | `ALTER TABLE` によるカラム追加を冪等に適用。`game_pitching` の汚染行（投球回端数行）も除去 |
| `upsert_snapshot(conn, year, stats_date)` | `snapshots` に `INSERT OR IGNORE` し、そのIDを返す。FK制約のため子テーブルのINSERT前に `commit()` を実施 |
| `save_standings(conn, snapshot_id, df)` | `team_standings` に保存 |
| `save_team_batting(conn, snapshot_id, df)` | `team_batting` に保存 |
| `save_team_pitching(conn, snapshot_id, df)` | `team_pitching` に保存 |
| `save_team_fielding(conn, snapshot_id, df)` | `team_fielding` に保存 |
| `save_player_batting(conn, snapshot_id, df)` | `player_batting` に保存 |
| `save_player_pitching(conn, snapshot_id, df)` | `player_pitching` に保存 |
| `save_player_fielding(conn, snapshot_id, df)` | `player_fielding` に保存 |
| `save_game_batting(conn, year, game_date, opponent, home_away, df)` | `game_batting` に保存。`DELETE WHERE year AND game_date` で再実行安全 |
| `save_game_pitching(conn, year, game_date, opponent, home_away, df)` | `game_pitching` に保存。`DELETE WHERE year AND game_date` で再実行安全 |

**保存処理の共通パターン**

各 `save_*` 関数は以下の手順で冪等な書き込みを実現する。

1. DataFrameに `snapshot_id`（またはゲーム系は `year`, `game_date` 等）の列を追加
2. `DELETE FROM {table} WHERE ...` で既存データを削除（再実行時の二重登録防止）
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

### game_batting — ホークス試合別打撃成績

ボックススコアから取得するスナップショット非依存テーブル。1試合ごとに DELETE → INSERT で上書きされる。

| カラム | 型 | 説明 |
|--------|----|------|
| id | INTEGER | PK, AUTOINCREMENT |
| year | INTEGER | 対象年度 |
| game_date | DATE | 試合日 |
| opponent | TEXT | 対戦相手チーム名 |
| home_away | TEXT | `'H'`（本拠地）または `'A'`（ビジター） |
| row_order | INTEGER | 打順行の表示順（ボックススコアの行番号） |
| position | TEXT | 守備位置 |
| player | TEXT | 選手名 |
| at_bats | INTEGER | 打数 |
| plate_appearances | INTEGER | 打席数（打席結果列の非 `-` セル数から算出） |
| runs | INTEGER | 得点 |
| hits | INTEGER | 安打 |
| home_runs | INTEGER | 本塁打（打席結果列の「本」を含むセル数から算出） |
| rbi | INTEGER | 打点 |
| stolen_bases | INTEGER | 盗塁 |

- インデックス: `game_date`

---

### game_pitching — ホークス試合別投手成績

| カラム | 型 | 説明 |
|--------|----|------|
| id | INTEGER | PK, AUTOINCREMENT |
| year | INTEGER | 対象年度 |
| game_date | DATE | 試合日 |
| opponent | TEXT | 対戦相手チーム名 |
| home_away | TEXT | `'H'` または `'A'` |
| row_order | INTEGER | 登板順 |
| pitcher | TEXT | 投手名 |
| result | TEXT | `'○'`（勝）/ `'●'`（負）/ `NULL`（なし） |
| innings_pitched | REAL | 投球回（`5.333…` = 5と1/3回） |
| batters_faced | INTEGER | 対戦打者数 |
| hits | INTEGER | 被安打 |
| home_runs | INTEGER | 被本塁打 |
| strikeouts | INTEGER | 奪三振 |
| walks | INTEGER | 四球 |
| hit_by_pitch | INTEGER | 死球 |
| runs | INTEGER | 失点 |
| earned_runs | INTEGER | 自責点 |

- インデックス: `game_date`

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

season_results   ← seeds.sql から独立投入（snapshots との FK なし）

game_batting     ← ボックススコアから独立取得（snapshots との FK なし）
game_pitching    ← ボックススコアから独立取得（snapshots との FK なし）
```

スクレイピング系テーブル（`team_*`, `player_*`）は `snapshot_id` で `snapshots` を参照する。
`game_batting` / `game_pitching` はスナップショット管理とは独立しており、`(year, game_date)` を主キー相当として管理する。
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
| `/hawks/batting` | ホークス打撃 | 試合別打撃成績（試合選択ドロップダウン） |
| `/hawks/ranking` | ホークス打撃ランキング | 年間累積成績。規定打席（試合数×3.1）到達者に順位付け |
| `/hawks/pitching` | ホークス投手 | 試合別投手成績（試合選択ドロップダウン） |
| `/hawks/pitching/ranking` | ホークス投手ランキング | 年間累積成績。規定投球回（試合数×1.0）到達者に順位付け |

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

## テスト仕様

**実行方法**

```bash
pip install -r requirements-dev.txt
python -m pytest
```

**方針**

- ネットワークアクセスと本番DBへの書き込みを一切行わない
- HTTP取得は `tests/fixtures/` のHTMLで代替し、DBは `tmp_path` 上のSQLiteに差し替える
- NPB側のHTML構造変更やリファクタでパースが壊れたことを検知することが主目的

**ファイル構成**

| ファイル | 対象 | 主な検証内容 |
| ------- | ---- | ---------- |
| `tests/conftest.py` | — | フィクスチャローダ `html(name)` の提供、リポジトリルートの `sys.path` 追加 |
| `tests/test_parse.py` | `scraper/parse.py` | 全パーサ、テーブル選択条件、打席結果セルからの本塁打・四球・打席数の集計、投球回変換、合計行・汚染行の除去、中止判定 |
| `tests/test_store.py` | `scraper/store.py` | `upsert_snapshot` の冪等性とコミット順序、同一 `snapshot_id` でのリーグ別上書き、旧スキーマからのマイグレーション、parse→store の往復（出力列がスキーマ列に収まること） |
| `tests/test_main.py` | `main.scrape_hawks_games` | `fetch` を差し替えた統合テスト。中止試合のスキップ、取得済み試合の再取得抑止 |

**フィクスチャ**

`tests/fixtures/` にNPB公式ページの構造を最小限に模したHTMLを置く。実ページそのものではなく、
パーサが依存している構造（列名、テーブルの並び順、見出し階層）だけを再現している。

| ファイル | 模した対象 |
| ------- | -------- |
| `std_p.html` / `tmb_p.html` / `tmp_p.html` / `tmf_p.html` | 勝敗表・チーム打撃/投手/守備 |
| `bat_p.html` / `pit_p.html` / `fld_p.html` | 個人打撃/投手/守備ランキング |
| `schedule_04.html` | 月別スケジュール（重複リンク・他球団の試合を含む） |
| `box.html` | ボックススコア（ホーム/ビジター両方の打撃・投手テーブル） |
| `box_cancelled.html` | 中止試合のボックススコア（空の線スコアと `【雨天のため中止】` のみ） |

**フィクスチャの更新手順**

NPB側のHTML構造が変わってテストが落ちた場合は、`cache/YYYYMMDD/` に保存された実ページを
参照して該当フィクスチャの構造を合わせ、期待値を実データに基づいて修正する。

**既知の制約**

テーブルが1つも存在しないHTMLを `pd.read_html` に渡すと、lxml が失敗して html5lib に
フォールバックし、`ValueError` ではなく `ImportError: Missing optional dependency 'html5lib'`
が送出される。テストは実際に起こりやすい「テーブルはあるが目的の構造ではない」ケースで
検証している。

---

## 環境変数

| 変数名 | 使用箇所 | デフォルト | 説明 |
| ------ | ------- | --------- | ---- |
| `NPB_DB_PATH` | `scraper/store.py`, `web.py` | `{プロジェクトルート}/data/npb.db` | SQLiteファイルのパス。`Dockerfile.web` では `/tmp/npb.db` を指定 |
| `GCS_BUCKET` | `gcp_job.py`, `web.py` | Job: `amplified-alpha-330603-npb-stats`／Web: 空 | DB永続化先のGCSバケット。Webでは空ならGCS連携を行わない |
| `GCS_DB_BLOB` | `gcp_job.py`, `web.py` | `npb.db` | バケット内のオブジェクト名 |
| `ALLOWED_EMAIL` | `web.py` | 空 | ログインを許可するGoogleアカウント。空なら制限なし |
| `GOOGLE_CLIENT_ID` | `web.py` | 空 | OAuthクライアントID。**空の場合は認証自体をスキップ**（ローカル開発用） |
| `GOOGLE_CLIENT_SECRET` | `web.py` | 空 | OAuthクライアントシークレット |
| `FLASK_SECRET_KEY` | `web.py` | `dev-only-insecure-key` | セッション署名鍵。本番ではSecret Managerから注入 |
| `GMAIL_USER` | `gcp_job.py` | 空 | 通知メールの送信元アカウント |
| `GMAIL_APP_PASSWORD` | `gcp_job.py` | 空 | Gmailアプリパスワード |
| `NOTIFY_EMAIL` | `gcp_job.py` | 空 | 通知メールの宛先 |
| `WEB_URL` | `gcp_job.py` | 空 | 完了通知メールに記載するWebビューアのURL。空なら記載しない |

`GMAIL_USER` / `GMAIL_APP_PASSWORD` / `NOTIFY_EMAIL` のいずれかが空の場合、通知は送信されず
ログに `[Mail] 通知設定が未完了のためスキップ` が出力される。

---

## 運用仕様

| 項目 | 内容 |
|------|------|
| スクレイパー実行頻度 | 毎日自動（Cloud Scheduler: 毎朝8:00 JST） |
| リクエスト間隔 | 2.5秒 |
| キャッシュ有効期間 | 当日中（`cache/YYYYMMDD/` 単位）。Cloud Run Job はコンテナが毎回新規のため実質無効 |
| データ利用制限 | NPB公式利用規約に基づき私的利用の範囲に限定。DBは非公開のGCSバケットに保管し、WebビューアはOAuthで単一アカウントのみに公開 |
| DBファイル | GCS: `gs://amplified-alpha-330603-npb-stats/npb.db`（SQLite3） |
| Webサーバー | Cloud Run Service（Google OAuth + `ALLOWED_EMAIL` による単一アカウント許可制） |
| 実行結果の通知 | Gmail SMTP（`smtp.gmail.com:465`）で完了・失敗を通知。`GMAIL_USER` / `GMAIL_APP_PASSWORD` / `NOTIFY_EMAIL` のいずれかが未設定なら送信をスキップ |
| 失敗時の挙動 | `main.py` が異常終了してもDBはGCSへアップロードし、失敗通知を送ってから終了コードを引き継いで終了 |
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
        ④ Gmail SMTP で完了 / 失敗を通知（実行ログ本文つき）

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
| Secret Manager | `npb-web-client-id` / `npb-web-client-secret` / `npb-web-secret-key` | OAuth 認証情報・Flask セッションキー |
| Secret Manager | `npb-gmail-user` / `npb-gmail-app-password` | 通知メール送信用の Gmail アカウントとアプリパスワード |
| サービスアカウント | `npb-stats-job@amplified-alpha-330603.iam.gserviceaccount.com` | Job・Service 共用 |

### Cloud Run Job（スクレイパー）

- **エントリーポイント**: `gcp_job.py`
- **Dockerfile**: `Dockerfile`（CMD: `python gcp_job.py`）
- **環境変数**: `GCS_BUCKET`, `GCS_DB_BLOB`, `NOTIFY_EMAIL`, `WEB_URL`
- **シークレット**: `GMAIL_USER`, `GMAIL_APP_PASSWORD`（Secret Manager）
- **対象年度**: JST 現在時刻の年を自動取得し `main.py --year` に渡す
- **DB パス**: `{アプリルート}/data/npb.db`（コンテナ内一時領域）

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
