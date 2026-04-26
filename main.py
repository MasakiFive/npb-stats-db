"""週1で手動実行するメインスクリプト。
使い方: python main.py  # 当年を自動取得
        python main.py --year 2025  # 年を指定する場合
"""
import argparse
from datetime import datetime
from scraper.fetch import fetch
from scraper.parse import (
    parse_stats_date,
    parse_standings,
    parse_team_batting,
    parse_team_pitching,
    parse_team_fielding,
    parse_player_batting,
    parse_player_pitching,
    parse_player_fielding,
)
from scraper.store import (
    get_conn,
    init_db,
    upsert_snapshot,
    save_standings,
    save_team_batting,
    save_team_pitching,
    save_team_fielding,
    save_player_batting,
    save_player_pitching,
    save_player_fielding,
)

# (league, url_path, parse_fn, save_fn, 表示ラベル)
TARGETS = [
    ("C", "std_c", parse_standings,      save_standings,      "勝敗表"),
    ("P", "std_p", parse_standings,      save_standings,      "勝敗表"),
    ("C", "tmb_c", parse_team_batting,   save_team_batting,   "チーム打撃"),
    ("P", "tmb_p", parse_team_batting,   save_team_batting,   "チーム打撃"),
    ("C", "tmp_c", parse_team_pitching,  save_team_pitching,  "チーム投手"),
    ("P", "tmp_p", parse_team_pitching,  save_team_pitching,  "チーム投手"),
    ("C", "tmf_c", parse_team_fielding,  save_team_fielding,  "チーム守備"),
    ("P", "tmf_p", parse_team_fielding,  save_team_fielding,  "チーム守備"),
    ("C", "bat_c", parse_player_batting, save_player_batting, "個人打撃"),
    ("P", "bat_p", parse_player_batting, save_player_batting, "個人打撃"),
    ("C", "pit_c", parse_player_pitching,save_player_pitching,"個人投手"),
    ("P", "pit_p", parse_player_pitching,save_player_pitching,"個人投手"),
    ("C", "fld_c", parse_player_fielding,save_player_fielding,"個人守備"),
    ("P", "fld_p", parse_player_fielding,save_player_fielding,"個人守備"),
]

TABLES = [
    "snapshots",
    "team_standings",
    "team_batting",
    "team_pitching",
    "team_fielding",
    "player_batting",
    "player_pitching",
    "player_fielding",
]


def run(year: int) -> None:
    init_db()
    with get_conn() as conn:
        for league, path, parse_fn, save_fn, label in TARGETS:
            url = f"https://npb.jp/bis/{year}/stats/{path}.html"
            html = fetch(url)
            stats_date = parse_stats_date(html)
            # FK制約のため snapshot を先にコミットしてから子テーブルへINSERT
            snapshot_id = upsert_snapshot(conn, year, stats_date)
            df = parse_fn(html, league)
            save_fn(conn, snapshot_id, df)
            print(f"[OK] {league}リーグ {label} ({stats_date}) -> {len(df)} 行")

        print("\n--- テーブル別行数 ---")
        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<25} {count:>5} 行")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()
    run(args.year)
