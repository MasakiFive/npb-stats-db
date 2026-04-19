# npb-stats-db

NPB公式サイト(npb.jp)から野球成績を取得してSQLiteに蓄積する個人用ツール。

## 使い方

```bash
cd ~/npb-stats-db
source .venv/bin/activate
python main.py --year 2026
```

## 取得対象

- チーム勝敗表（std_c, std_p）
- チーム打撃・投手・守備（tmb_*, tmp_*, tmf_*）
- 個人ランキング打撃・投手・守備（bat_*, pit_*, fld_*）※規定以上

## DB構造

- `snapshots`：取得日時のハブテーブル
- 各成績テーブルは `snapshot_id` で snapshots を参照（履歴管理）

## よく使うクエリ

```sql
-- 最新スナップショットのセ・リーグ勝敗表
SELECT rank, team, wins, losses, win_pct, games_behind
FROM team_standings
WHERE snapshot_id = (SELECT MAX(id) FROM snapshots)
  AND league = 'C'
ORDER BY rank;

-- 特定選手の打率推移（週を重ねるごとに意味が出てくる）
SELECT s.stats_date, p.avg
FROM player_batting p
JOIN snapshots s ON p.snapshot_id = s.id
WHERE p.name LIKE '%佐藤%'
ORDER BY s.stats_date;
```

## 注意

- NPB公式の利用規約上、データは個人のローカル利用に限定する
- リクエスト間隔は2.5秒、取得HTMLはcache/にローカル保存