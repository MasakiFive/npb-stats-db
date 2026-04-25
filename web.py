"""NPB成績閲覧Webサーバー。
起動: python web.py
アクセス: http://localhost:5000
"""
from flask import Flask, render_template, request, g
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "npb.db"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# DB接続
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def all_snapshots():
    return get_db().execute(
        "SELECT * FROM snapshots ORDER BY stats_date DESC"
    ).fetchall()


def latest_snapshot_id():
    row = get_db().execute(
        "SELECT id FROM snapshots ORDER BY stats_date DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def current_params():
    sid = request.args.get("snapshot_id", type=int) or latest_snapshot_id()
    league = request.args.get("league", "P")
    return sid, league


# ---------------------------------------------------------------------------
# カラム定義 (DBキー, 表示名)
# ---------------------------------------------------------------------------

STANDINGS_COLS = [
    ("rank", "順位"), ("team", "チーム"), ("games", "試合"),
    ("wins", "勝"), ("losses", "負"), ("ties", "分"),
    ("win_pct", "勝率"), ("games_behind", "ゲーム差"),
]

TEAM_BATTING_COLS = [
    ("team", "チーム"), ("batting_avg", "打率"), ("games", "試合"),
    ("plate_appearances", "打席"), ("at_bats", "打数"), ("hits", "安打"),
    ("doubles", "二塁打"), ("triples", "三塁打"), ("home_runs", "本塁打"),
    ("total_bases", "塁打"), ("rbi", "打点"), ("stolen_bases", "盗塁"),
    ("caught_stealing", "盗塁刺"), ("sacrifice_hits", "犠打"),
    ("sacrifice_flies", "犠飛"), ("walks", "四球"),
    ("intentional_walks", "故意四球"), ("hit_by_pitch", "死球"),
    ("strikeouts", "三振"), ("grounded_into_dp", "併殺打"),
    ("slugging_pct", "長打率"), ("on_base_pct", "出塁率"),
]

TEAM_PITCHING_COLS = [
    ("team", "チーム"), ("era", "防御率"), ("games", "試合"),
    ("wins", "勝"), ("losses", "負"), ("saves", "S"),
    ("holds", "H"), ("hold_points", "HP"), ("complete_games", "完投"),
    ("shutouts", "完封"), ("no_walks", "無四球"), ("win_pct", "勝率"),
    ("batters_faced", "対打者"), ("innings_pitched", "投球回"),
    ("hits", "被安打"), ("home_runs", "被本塁打"), ("walks", "四球"),
    ("intentional_walks", "故意四球"), ("hit_by_pitch", "死球"),
    ("strikeouts", "奪三振"), ("wild_pitches", "暴投"),
    ("balks", "ボーク"), ("runs", "失点"), ("earned_runs", "自責点"),
]

TEAM_FIELDING_COLS = [
    ("team", "チーム"), ("fielding_avg", "守備率"), ("games", "試合"),
    ("chances", "機会"), ("putouts", "刺殺"), ("assists", "補殺"),
    ("errors", "失策"), ("double_plays_participated", "併殺参加"),
    ("double_plays_team", "球団併殺"), ("passed_balls", "捕逸"),
]

PLAYER_BATTING_COLS = [
    ("rank", "順位"), ("player", "選手"), ("team", "球団"),
    ("batting_avg", "打率"), ("games", "試合"),
    ("plate_appearances", "打席"), ("at_bats", "打数"), ("hits", "安打"),
    ("doubles", "二塁打"), ("triples", "三塁打"), ("home_runs", "本塁打"),
    ("total_bases", "塁打"), ("rbi", "打点"), ("stolen_bases", "盗塁"),
    ("caught_stealing", "盗塁刺"), ("sacrifice_hits", "犠打"),
    ("sacrifice_flies", "犠飛"), ("walks", "四球"),
    ("intentional_walks", "故意四球"), ("hit_by_pitch", "死球"),
    ("strikeouts", "三振"), ("grounded_into_dp", "併殺打"),
    ("slugging_pct", "長打率"), ("on_base_pct", "出塁率"),
]

PLAYER_PITCHING_COLS = [
    ("rank", "順位"), ("player", "選手"), ("team", "球団"),
    ("era", "防御率"), ("games", "登板"),
    ("wins", "勝"), ("losses", "負"), ("saves", "S"),
    ("holds", "H"), ("hold_points", "HP"), ("complete_games", "完投"),
    ("shutouts", "完封"), ("no_walks", "無四球"), ("win_pct", "勝率"),
    ("batters_faced", "対打者"), ("innings_pitched", "投球回"),
    ("hits", "被安打"), ("home_runs", "被本塁打"), ("walks", "四球"),
    ("intentional_walks", "故意四球"), ("hit_by_pitch", "死球"),
    ("strikeouts", "奪三振"), ("wild_pitches", "暴投"),
    ("balks", "ボーク"), ("runs", "失点"), ("earned_runs", "自責点"),
]

PLAYER_FIELDING_COLS = [
    ("rank", "順位"), ("player", "選手"), ("team", "球団"),
    ("position", "位置"), ("fielding_avg", "守備率"), ("games", "試合"),
    ("putouts", "刺殺"), ("assists", "補殺"), ("errors", "失策"),
    ("double_plays", "併殺"), ("passed_balls", "捕逸"),
]

NAV_ITEMS = [
    ("standings",       "/standings",       "勝敗表"),
    ("team_batting",    "/team/batting",    "チーム打撃"),
    ("team_pitching",   "/team/pitching",   "チーム投手"),
    ("team_fielding",   "/team/fielding",   "チーム守備"),
    ("player_batting",  "/player/batting",  "個人打撃"),
    ("player_pitching", "/player/pitching", "個人投手"),
    ("player_fielding", "/player/fielding", "個人守備"),
    ("rankings",        "/rankings",        "ランキング"),
    ("trends",          "/trends",          "推移グラフ"),
    ("history",         "/history",         "歴代成績"),
]

_CHART_COLORS = [
    "#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF",
    "#FF9F40", "#C9CBCF", "#7BC8A4", "#B3A2D1", "#E7E9ED",
]


# ---------------------------------------------------------------------------
# 順位変動・推移グラフ用ヘルパー
# ---------------------------------------------------------------------------

def get_prev_snapshot_id(current_id: int):
    """指定スナップショットの直前IDを返す（なければNone）。"""
    row = get_db().execute(
        "SELECT id FROM snapshots WHERE id < ? ORDER BY id DESC LIMIT 1",
        (current_id,)
    ).fetchone()
    return row["id"] if row else None


def standings_with_rank_change(snapshot_id: int, league: str) -> list:
    """順位変動列を付加した勝敗表データ（dictのリスト）を返す。"""
    rows = get_db().execute(
        "SELECT * FROM team_standings WHERE snapshot_id=? AND league=? ORDER BY rank",
        (snapshot_id, league)
    ).fetchall()

    prev_id = get_prev_snapshot_id(snapshot_id)
    prev_rank = {}
    if prev_id:
        for r in get_db().execute(
            "SELECT team, rank FROM team_standings WHERE snapshot_id=? AND league=?",
            (prev_id, league)
        ).fetchall():
            prev_rank[r["team"]] = r["rank"]

    result = []
    for row in rows:
        d = dict(row)
        pr = prev_rank.get(row["team"])
        d["rank_change"] = (pr - row["rank"]) if pr is not None else None
        result.append(d)
    return result


def _standings_trend_json(league: str) -> str:
    """リーグ内全チームの順位推移をChart.js JSON形式で返す。"""
    db = get_db()

    dates = [r["stats_date"] for r in db.execute(
        "SELECT DISTINCT s.stats_date FROM team_standings t "
        "JOIN snapshots s ON t.snapshot_id = s.id "
        "WHERE t.league=? ORDER BY s.stats_date",
        (league,)
    ).fetchall()]

    if not dates:
        return json.dumps({"labels": [], "datasets": []})

    teams = [r["team"] for r in db.execute(
        "SELECT DISTINCT team FROM team_standings WHERE league=? ORDER BY team",
        (league,)
    ).fetchall()]

    rows = db.execute(
        "SELECT s.stats_date, t.team, t.rank "
        "FROM team_standings t JOIN snapshots s ON t.snapshot_id = s.id "
        "WHERE t.league=? ORDER BY s.stats_date",
        (league,)
    ).fetchall()

    data_map: dict[str, dict] = {}
    for row in rows:
        data_map.setdefault(row["team"], {})[row["stats_date"]] = row["rank"]

    datasets = []
    for i, team in enumerate(teams):
        color = _CHART_COLORS[i % len(_CHART_COLORS)]
        datasets.append({
            "label": team,
            "data": [data_map.get(team, {}).get(d) for d in dates],
            "borderColor": color,
            "backgroundColor": color,
            "fill": False,
            "tension": 0.3,
            "pointRadius": 4,
            "spanGaps": False,
        })

    return json.dumps({"labels": dates, "datasets": datasets}, ensure_ascii=False)


def _trend_json(table: str, stat_col: str, league: str) -> str:
    """最新スナップショット上位10選手の全スナップショット推移をChart.js JSON形式で返す。"""
    db = get_db()
    latest_id = latest_snapshot_id()
    if not latest_id:
        return json.dumps({"labels": [], "datasets": []})

    order = "ASC" if stat_col == "era" else "DESC"
    top_players = [r["player"] for r in db.execute(
        f"SELECT player FROM {table} WHERE snapshot_id=? AND league=? "
        f"ORDER BY {stat_col} {order} LIMIT 10",
        (latest_id, league)
    ).fetchall()]

    if not top_players:
        return json.dumps({"labels": [], "datasets": []})

    dates = [r["stats_date"] for r in db.execute(
        f"SELECT DISTINCT s.stats_date FROM {table} t "
        f"JOIN snapshots s ON t.snapshot_id = s.id "
        f"WHERE t.league=? ORDER BY s.stats_date",
        (league,)
    ).fetchall()]

    ph = ",".join("?" * len(top_players))
    rows = db.execute(
        f"SELECT s.stats_date, t.player, t.{stat_col} "
        f"FROM {table} t JOIN snapshots s ON t.snapshot_id = s.id "
        f"WHERE t.league=? AND t.player IN ({ph}) ORDER BY s.stats_date",
        [league] + top_players
    ).fetchall()

    data_map: dict[str, dict] = {}
    for row in rows:
        data_map.setdefault(row["player"], {})[row["stats_date"]] = row[stat_col]

    datasets = []
    for i, player in enumerate(top_players):
        color = _CHART_COLORS[i % len(_CHART_COLORS)]
        datasets.append({
            "label": player,
            "data": [data_map.get(player, {}).get(d) for d in dates],
            "borderColor": color,
            "backgroundColor": color,
            "fill": False,
            "tension": 0.3,
            "pointRadius": 4,
            "spanGaps": False,
        })

    return json.dumps({"labels": dates, "datasets": datasets}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 共通レンダリングヘルパー
# ---------------------------------------------------------------------------

def _render_stats(page, title, table, cols, order_by):
    snap_list = all_snapshots()
    snapshot_id, league = current_params()
    rows = get_db().execute(
        f"SELECT * FROM {table} WHERE snapshot_id=? AND league=? ORDER BY {order_by}",
        (snapshot_id, league),
    ).fetchall()
    return render_template(
        "stats.html",
        page=page, title=title, cols=cols, rows=rows,
        snapshots=snap_list, snapshot_id=snapshot_id, league=league,
        nav_items=NAV_ITEMS,
    )


# ---------------------------------------------------------------------------
# ルート
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    snap_list = all_snapshots()
    snapshot_id, _ = current_params()
    c_standings = standings_with_rank_change(snapshot_id, "C")
    p_standings = standings_with_rank_change(snapshot_id, "P")
    counts = {}
    for tbl in ["snapshots", "team_standings", "team_batting", "team_pitching",
                "team_fielding", "player_batting", "player_pitching", "player_fielding"]:
        counts[tbl] = get_db().execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    return render_template(
        "index.html",
        page="index",
        snapshots=snap_list, snapshot_id=snapshot_id,
        c_standings=c_standings, p_standings=p_standings,
        counts=counts, nav_items=NAV_ITEMS,
    )


@app.route("/standings")
def standings():
    return _render_stats("standings", "勝敗表", "team_standings", STANDINGS_COLS, "rank")


@app.route("/team/batting")
def team_batting():
    return _render_stats("team_batting", "チーム打撃", "team_batting",
                         TEAM_BATTING_COLS, "batting_avg DESC")


@app.route("/team/pitching")
def team_pitching():
    return _render_stats("team_pitching", "チーム投手", "team_pitching",
                         TEAM_PITCHING_COLS, "era")


@app.route("/team/fielding")
def team_fielding():
    return _render_stats("team_fielding", "チーム守備", "team_fielding",
                         TEAM_FIELDING_COLS, "fielding_avg DESC")


@app.route("/player/batting")
def player_batting():
    return _render_stats("player_batting", "個人打撃", "player_batting",
                         PLAYER_BATTING_COLS, "rank")


@app.route("/player/pitching")
def player_pitching():
    return _render_stats("player_pitching", "個人投手", "player_pitching",
                         PLAYER_PITCHING_COLS, "rank")


@app.route("/player/fielding")
def player_fielding():
    snap_list = all_snapshots()
    snapshot_id, league = current_params()
    position = request.args.get("position", "")

    params = [snapshot_id, league]
    query = "SELECT * FROM player_fielding WHERE snapshot_id=? AND league=?"
    if position:
        query += " AND position=?"
        params.append(position)
    query += " ORDER BY rank, position"

    rows = get_db().execute(query, params).fetchall()
    pos_rows = get_db().execute(
        "SELECT DISTINCT position FROM player_fielding WHERE snapshot_id=? AND league=? ORDER BY position",
        (snapshot_id, league),
    ).fetchall()
    positions = [r["position"] for r in pos_rows]

    return render_template(
        "stats.html",
        page="player_fielding", title="個人守備",
        cols=PLAYER_FIELDING_COLS, rows=rows,
        snapshots=snap_list, snapshot_id=snapshot_id, league=league,
        nav_items=NAV_ITEMS, positions=positions, current_position=position,
    )


@app.route("/rankings")
def rankings():
    snap_list = all_snapshots()
    snapshot_id, league = current_params()
    db = get_db()

    batting_top10 = db.execute(
        "SELECT player, team, batting_avg, hits, at_bats, home_runs, rbi, stolen_bases "
        "FROM player_batting WHERE snapshot_id=? AND league=? "
        "ORDER BY batting_avg DESC LIMIT 10",
        (snapshot_id, league)
    ).fetchall()

    era_top10 = db.execute(
        "SELECT player, team, era, wins, losses, innings_pitched, strikeouts "
        "FROM player_pitching WHERE snapshot_id=? AND league=? "
        "ORDER BY era ASC LIMIT 10",
        (snapshot_id, league)
    ).fetchall()

    strikeout_top = db.execute(
        "SELECT player, team, strikeouts, innings_pitched, era "
        "FROM player_pitching WHERE snapshot_id=? AND league=? "
        "AND innings_pitched > 0 ORDER BY strikeouts DESC LIMIT 10",
        (snapshot_id, league)
    ).fetchall()

    wins_top = db.execute(
        "SELECT player, team, wins, losses, era, innings_pitched "
        "FROM player_pitching WHERE snapshot_id=? AND league=? "
        "ORDER BY wins DESC LIMIT 10",
        (snapshot_id, league)
    ).fetchall()

    k9_top = db.execute(
        "SELECT player, team, "
        "ROUND(strikeouts * 9.0 / innings_pitched, 2) AS k_per_9, "
        "strikeouts, innings_pitched, era "
        "FROM player_pitching WHERE snapshot_id=? AND league=? "
        "AND innings_pitched > 0 ORDER BY k_per_9 DESC LIMIT 10",
        (snapshot_id, league)
    ).fetchall()

    return render_template(
        "rankings.html",
        page="rankings", title="ランキング",
        snapshots=snap_list, snapshot_id=snapshot_id, league=league,
        nav_items=NAV_ITEMS,
        batting_top10=batting_top10,
        era_top10=era_top10,
        strikeout_top=strikeout_top,
        wins_top=wins_top,
        k9_top=k9_top,
    )


@app.route("/trends")
def trends():
    snap_list = all_snapshots()
    snapshot_id, league = current_params()
    return render_template(
        "trends.html",
        page="trends", title="推移グラフ",
        snapshots=snap_list, snapshot_id=snapshot_id, league=league,
        nav_items=NAV_ITEMS,
        batting_data=_trend_json("player_batting", "batting_avg", league),
        era_data=_trend_json("player_pitching", "era", league),
        c_standings_data=_standings_trend_json("C"),
        p_standings_data=_standings_trend_json("P"),
    )


@app.route("/history")
def history():
    db = get_db()

    seasons = db.execute(
        "SELECT * FROM season_results ORDER BY year DESC"
    ).fetchall()

    # チーム別集計（優勝回数）
    cl_counts = db.execute("""
        SELECT central_champion AS team, COUNT(*) AS count
        FROM season_results WHERE central_champion IS NOT NULL
        GROUP BY central_champion ORDER BY count DESC
    """).fetchall()

    pl_counts = db.execute("""
        SELECT pacific_champion AS team, COUNT(*) AS count
        FROM season_results WHERE pacific_champion IS NOT NULL
        GROUP BY pacific_champion ORDER BY count DESC
    """).fetchall()

    js_counts = db.execute("""
        SELECT japan_series_winner AS team, COUNT(*) AS count
        FROM season_results WHERE japan_series_winner IS NOT NULL
        GROUP BY japan_series_winner ORDER BY count DESC
    """).fetchall()

    return render_template(
        "history.html",
        page="history", title="歴代成績",
        nav_items=NAV_ITEMS,
        seasons=seasons,
        cl_counts=cl_counts,
        pl_counts=pl_counts,
        js_counts=js_counts,
    )


if __name__ == "__main__":
    app.run(debug=True)
