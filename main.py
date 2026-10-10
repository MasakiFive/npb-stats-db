"""成績スクレイピングのメインスクリプト。

本番では Cloud Run Job（gcp_job.py）から毎朝 8:00 JST に実行される。
公式戦トップの勝敗表欄でシーズンの進行状況を判定し、開幕前と閉幕後
（最終成績の取り込み後）は何もせずに終了コード EXIT_SKIPPED で終わる。
ローカルでの手動実行:
    python main.py              # 当年を自動取得
    python main.py --year 2025  # 年を指定する場合
    python main.py --final P=2026-10-06  # 閉幕したリーグの最終戦日を明示する場合
"""
from __future__ import annotations  # `str | None` を Python 3.9 でも評価可能にする

import argparse
import sys
from datetime import datetime, date, timedelta, timezone
import requests
from scraper.fetch import fetch
from scraper.parse import (
    FINISHED,
    IN_PROGRESS,
    NOT_STARTED,
    parse_season_status,
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
    get_final_dates,
    init_db,
    record_final_date,
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
    "season_end",
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

# シーズン期間外で取り込みを行わなかったときの終了コード（gcp_job.py が参照する）
EXIT_SKIPPED = 10

JST = timezone(timedelta(hours=9))
LEAGUE_NAMES = {"C": "セ", "P": "パ"}


def get_season_status(year: int) -> dict:
    """公式戦トップから各リーグの進行状況を返す。ページが無ければ開幕前とみなす。"""
    try:
        html = fetch(f"https://npb.jp/games/{year}/")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return {"C": (NOT_STARTED, None), "P": (NOT_STARTED, None)}
        raise
    return parse_season_status(html, year)


def plan_run(
    status: dict,
    final_dates: dict,
    default_final: str,
    final_overrides: dict | None = None,
) -> tuple[str | None, dict]:
    """取り込みの要否と成績基準日を決める。

    status: get_season_status() の戻り値
    final_dates: 記録済みのリーグ別最終戦日
    default_final: 新たに閉幕を検知したリーグの最終戦日とみなす日（通常は前日）
    final_overrides: 新たに閉幕を検知したリーグの最終戦日を明示する場合に指定

    戻り値: (基準日。取り込み不要なら None, 新たに記録するリーグ別最終戦日)
    - どちらかのリーグがシーズン中 → そのページの基準日で取り込む。閉幕済みのリーグも
      同じスナップショットに最終成績を入れ、リーグ切替で空にならないようにする
    - 両リーグ閉幕で、まだ最終戦日を記録していないリーグがある → 最終成績を取り込む
    - それ以外（開幕前、または最終成績を取り込み済み）→ スキップ
    """
    new_finals = {
        league: (final_overrides or {}).get(league, default_final)
        for league, (state, _) in status.items()
        if state == FINISHED and league not in final_dates
    }
    in_progress = [d for state, d in status.values() if state == IN_PROGRESS]
    if in_progress:
        return max(in_progress), new_finals
    if new_finals:
        return max({**final_dates, **new_finals}.values()), new_finals
    return None, {}


def scrape_hawks_games(year: int, conn, until: str | None = None) -> None:
    """ホークスの全試合ボックススコアを取得して game_batting に保存する。

    until を渡すとその日より後の試合は取得しない。パ・リーグ閉幕後に日程ページへ
    載るポストシーズンの試合を、公式戦として取り込まないために使う。
    """
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
            if until and game["game_date"] > until:
                continue  # 閉幕後（ポストシーズン）の試合はスキップ
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


def run(year: int, today: date, final_overrides: dict | None = None) -> bool:
    """成績を取り込む。シーズン期間外で何もしなかった場合は False を返す。

    final_overrides: 新たに閉幕を検知したリーグの最終戦日を {'P': 'YYYY-MM-DD'} で指定する。
    未指定のリーグは前日を最終戦日とみなす（毎日実行していれば閉幕翌朝に検知するため）。
    """
    init_db()
    with get_conn() as conn:
        status = get_season_status(year)
        print("[season] " + " / ".join(
            f"{LEAGUE_NAMES[lg]}: {state}" + (f" ({d})" if d else "")
            for lg, (state, d) in status.items()
        ))
        final_dates = get_final_dates(conn, year)
        yesterday = (today - timedelta(days=1)).isoformat()
        run_date, new_finals = plan_run(status, final_dates, yesterday, final_overrides)
        if run_date is None:
            print(f"[season] {year}年はシーズン期間外（開幕前、または最終成績を取り込み済み）のためスキップ")
            return False

        for league, path, parse_fn, save_fn, label in TARGETS:
            url = f"https://npb.jp/bis/{year}/stats/{path}.html"
            html = fetch(url)
            if status[league][0] == FINISHED:
                # 閉幕後のページは「◯月◯日 現在」の表記が消える
                stats_date = run_date
            else:
                stats_date = parse_stats_date(html)
            # FK制約のため snapshot を先にコミットしてから子テーブルへINSERT
            snapshot_id = upsert_snapshot(conn, year, stats_date)
            df = parse_fn(html, league)
            save_fn(conn, snapshot_id, df)
            print(f"[OK] {league}リーグ {label} ({stats_date}) -> {len(df)} 行")

        print("\n[ホークス] 試合別打撃成績を取得中...")
        scrape_hawks_games(year, conn, until={**final_dates, **new_finals}.get("P"))

        # 取り込みが最後まで成功してから記録する（途中で失敗したら翌日やり直す）
        for league, final_date in new_finals.items():
            record_final_date(conn, year, league, final_date)
            print(f"[season] {LEAGUE_NAMES[league]}・リーグ閉幕: 最終戦日 {final_date} として最終成績を記録")

        print("\n--- テーブル別行数 ---")
        for table in TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<25} {count:>5} 行")
    return True


def _parse_final_arg(value: str) -> tuple[str, str]:
    league, _, final_date = value.partition("=")
    if league not in LEAGUE_NAMES:
        raise argparse.ArgumentTypeError(f"リーグは C か P: {value}")
    return league, date.fromisoformat(final_date).isoformat()


if __name__ == "__main__":
    today = datetime.now(JST).date()
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--final", type=_parse_final_arg, action="append", default=[],
                        metavar="LEAGUE=YYYY-MM-DD",
                        help="閉幕したリーグの最終戦日（未指定なら前日とみなす）")
    args = parser.parse_args()
    if not run(args.year, today, dict(args.final)):
        sys.exit(EXIT_SKIPPED)
