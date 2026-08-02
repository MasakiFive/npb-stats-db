"""週1で手動実行するメインスクリプト。
使い方: python main.py  # 当年を自動取得
        python main.py --year 2025  # 年を指定する場合
"""
import argparse
from datetime import datetime, date
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
    parse_schedule_game_urls,
    parse_game_batting,
    parse_game_pitching,
    is_cancelled_game,
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
    save_game_batting,
    save_game_pitching,
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
    "game_batting",
    "game_pitching",
]


def scrape_hawks_games(year: int, conn) -> None:
    """ホークスの全試合ボックススコアを取得して game_batting に保存する。"""
    today = date.today().isoformat()
    batting_dates = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT game_date FROM game_batting WHERE year=? AND walks IS NOT NULL", (year,)
        ).fetchall()
    }
    pitching_dates = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT game_date FROM game_pitching WHERE year=?", (year,)
        ).fetchall()
    }
    existing_dates = batting_dates & pitching_dates  # 両方揃っている試合のみスキップ

    total = 0
    for month in range(3, 11):
        schedule_url = f"https://npb.jp/games/{year}/schedule_{month:02d}_detail.html"
        try:
            html = fetch(schedule_url)
        except Exception as e:
            print(f"[ホークス] {month}月スケジュール取得失敗: {e}")
            continue

        games = parse_schedule_game_urls(html, year)
        for game in games:
            if game["game_date"] > today:
                continue  # 未来の試合はスキップ
            if game["game_date"] in existing_dates:
                continue  # 取得済みはスキップ
            try:
                box_html = fetch(game["url"])
                if is_cancelled_game(box_html):
                    # 中止試合はボックススコアが存在しない。エラーではないので
                    # 「打撃テーブルが見つかりません」を出さずに静かにスキップする。
                    print(f"[ホークス] {game['game_date']} vs {game['opponent']} 中止のためスキップ")
                    continue
                bat_df = parse_game_batting(box_html, game["home_away"])
                pit_df = parse_game_pitching(box_html, game["home_away"])
                save_game_batting(conn, year, game["game_date"],
                                  game["opponent"], game["home_away"], bat_df)
                save_game_pitching(conn, year, game["game_date"],
                                   game["opponent"], game["home_away"], pit_df)
                conn.commit()
                existing_dates.add(game["game_date"])
                total += len(bat_df)
                print(f"[ホークス] {game['game_date']} vs {game['opponent']}"
                      f" ({game['home_away']}) 打撃{len(bat_df)}行 投手{len(pit_df)}行")
            except Exception as e:
                print(f"[ホークス] {game['game_date']} vs {game['opponent']} 失敗: {e}")

    print(f"[ホークス] 打撃成績 新規追加 {total} 行")


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

        print("\n[ホークス] 試合別打撃成績を取得中...")
        scrape_hawks_games(year, conn)

        print("\n--- テーブル別行数 ---")
        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<25} {count:>5} 行")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()
    run(args.year)
