# npb-stats-db

NPB公式サイト(npb.jp)から野球成績を取得してSQLiteに蓄積し、Webブラウザで閲覧できる個人用ツール。

## 本番環境（GCP）

| コンポーネント | 内容 |
| ------------- | ---- |
| スクレイパー | Cloud Run Job（`npb-stats-job`）毎朝 8:00 JST 自動実行 |
| DB 永続化 | GCS: `gs://amplified-alpha-330603-npb-stats/npb.db` |
| Web ビューア | Cloud Run Service（`npb-stats-web`）Google OAuth 認証付き |
| DB 自動更新 | Web サービスが毎朝 9:00 JST に GCS から最新 DB を取得 |

### コードを変更した場合のデプロイ

```bash
# Web ビューア
bash gcp/deploy_web.sh

# スクレイパー
bash gcp/update.sh
```

---

## ローカル開発

### セットアップ

```bash
cd ~/npb-stats-db
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 歴代成績データを投入（初回のみ）
python seed.py
```

### 成績データの取得

```bash
source .venv/bin/activate
python main.py          # 当年を自動取得
python main.py --year 2025  # 年を指定する場合
```

同日に再実行しても冪等（キャッシュ利用＋上書き保存）。

### Web 閲覧

```bash
python web.py
# → http://localhost:5000（認証スキップ）
```

### テスト

```bash
pip install -r requirements-dev.txt
python -m pytest
```

`tests/fixtures/` に NPB 公式ページの構造を模した HTML を置き、
`scraper/parse.py` の全パーサと `scraper/store.py` の保存・マイグレーション処理を検証する。
ネットワークアクセスも本番DBへの書き込みも発生しない。

NPB 側の HTML 構造が変わってパースが壊れた場合は、実ページ（`cache/` に保存されたもの）を
元にフィクスチャを更新して期待値を直す。

---

## 取得対象

| 種別 | URLパス | 内容 |
| ---- | ------- | ---- |
| チーム | std_c / std_p | 勝敗表 |
| チーム | tmb_c / tmb_p | 打撃成績 |
| チーム | tmp_c / tmp_p | 投手成績 |
| チーム | tmf_c / tmf_p | 守備成績 |
| 個人 | bat_c / bat_p | 打撃ランキング（規定打席以上） |
| 個人 | pit_c / pit_p | 投手ランキング（規定投球回以上） |
| 個人 | fld_c / fld_p | 守備ランキング（全ポジション） |
| ホークス | ボックススコア | 試合別打撃・投手成績（一軍全試合） |

## Web ページ一覧

| URL | 内容 |
| --- | ---- |
| `/` | ダッシュボード（両リーグ順位表・順位変動） |
| `/standings` | 勝敗表 |
| `/team/batting` | チーム打撃 |
| `/team/pitching` | チーム投手 |
| `/team/fielding` | チーム守備 |
| `/player/batting` | 個人打撃ランキング |
| `/player/pitching` | 個人投手ランキング |
| `/player/fielding` | 個人守備ランキング |
| `/rankings` | 打率/防御率/奪三振/勝利数/K9 トップ10 |
| `/trends` | 打率・防御率・チーム順位の推移グラフ |
| `/history` | 歴代優勝チーム・優勝回数（1950〜） |
| `/hawks/batting` | ホークス試合別打撃成績 |
| `/hawks/ranking` | ホークス打撃ランキング（規定打席順位付き） |
| `/hawks/pitching` | ホークス試合別投手成績 |
| `/hawks/pitching/ranking` | ホークス投手ランキング（規定投球回順位付き） |

## DB 構造

- `snapshots`：取得日時のハブテーブル（全成績テーブルのFK参照元）
- `team_standings` / `team_batting` / `team_pitching` / `team_fielding`：チーム成績
- `player_batting` / `player_pitching` / `player_fielding`：個人成績
- `season_results`：歴代シーズン優勝データ（seed.py で投入、スナップショットと独立）
- `game_batting`：ホークス試合別打撃成績（ボックススコアから取得）
- `game_pitching`：ホークス試合別投手成績（ボックススコアから取得）

## よく使うクエリ

```sql
-- 最新スナップショットのパ・リーグ勝敗表
SELECT rank, team, wins, losses, win_pct, games_behind
FROM team_standings
WHERE snapshot_id = (SELECT MAX(id) FROM snapshots)
  AND league = 'P'
ORDER BY rank;

-- 特定選手の打率推移
SELECT s.stats_date, p.batting_avg
FROM player_batting p
JOIN snapshots s ON p.snapshot_id = s.id
WHERE p.player LIKE '%山川%'
ORDER BY s.stats_date;

-- チーム別日本シリーズ優勝回数
SELECT japan_series_winner, COUNT(*) AS count
FROM season_results
GROUP BY japan_series_winner
ORDER BY count DESC;
```

## 注意

- NPB公式の利用規約上、データは個人のローカル利用に限定する
- リクエスト間隔は2.5秒、取得HTMLは `cache/` にローカル保存
- 歴代成績データ（`sql/seeds.sql`）は記憶に基づくため一部要確認。誤りは直接編集して `python seed.py` を再実行
