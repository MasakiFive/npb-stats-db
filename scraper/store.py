"""DataFrameをSQLiteに保存する層。"""
import os
import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH = Path(os.environ.get(
    "NPB_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "npb.db"),
))
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)


def _migrate(conn) -> None:
    """スキーマ変更をべき等に適用する。"""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(game_batting)").fetchall()}
    if "home_runs" not in existing:
        conn.execute("ALTER TABLE game_batting ADD COLUMN home_runs INTEGER")
        conn.execute("DELETE FROM game_batting")  # home_runs なしデータを破棄して再スクレイプ
        conn.commit()
        existing.add("home_runs")
    if "plate_appearances" not in existing:
        conn.execute("ALTER TABLE game_batting ADD COLUMN plate_appearances INTEGER")
        conn.execute("UPDATE game_batting SET plate_appearances = at_bats")  # 近似値で初期化
        conn.commit()
    if "walks" not in existing:
        conn.execute("ALTER TABLE game_batting ADD COLUMN walks INTEGER")
        conn.commit()

    # 投球回端数行（'.1', '.2' 等）の汚染データを除去
    conn.execute("DELETE FROM game_pitching WHERE pitcher LIKE '.%'")
    conn.commit()


def upsert_snapshot(conn, year: int, stats_date: str) -> int:
    """スナップショット行を挿入（存在すれば無視）し、そのidを返す。
    FK制約で参照されるため、必ずcommitしてから返す。"""
    conn.execute(
        "INSERT OR IGNORE INTO snapshots(year, stats_date) VALUES (?, ?)",
        (year, stats_date),
    )
    conn.commit()  # ← ここがポイント。pandasのto_sql前に確実に可視化する
    row = conn.execute(
        "SELECT id FROM snapshots WHERE year=? AND stats_date=?",
        (year, stats_date),
    ).fetchone()
    return row[0]


def _league(df: pd.DataFrame) -> str:
    """DataFrameの league 列から値を取り出す。"""
    return str(df["league"].iloc[0])


def save_standings(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    # C/Pリーグが同日の場合に snapshot_id が共有されるため league でも絞り込む
    conn.execute(
        "DELETE FROM team_standings WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("team_standings", conn, if_exists="append", index=False)


def save_team_batting(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM team_batting WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("team_batting", conn, if_exists="append", index=False)


def save_team_pitching(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM team_pitching WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("team_pitching", conn, if_exists="append", index=False)


def save_team_fielding(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM team_fielding WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("team_fielding", conn, if_exists="append", index=False)


def save_player_batting(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM player_batting WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("player_batting", conn, if_exists="append", index=False)


def save_player_pitching(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM player_pitching WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("player_pitching", conn, if_exists="append", index=False)


def save_player_fielding(conn, snapshot_id: int, df: pd.DataFrame) -> None:
    df = df.copy()
    df["snapshot_id"] = snapshot_id
    conn.execute(
        "DELETE FROM player_fielding WHERE snapshot_id=? AND league=?",
        (snapshot_id, _league(df)),
    )
    df.to_sql("player_fielding", conn, if_exists="append", index=False)


def save_game_batting(
    conn,
    year: int,
    game_date: str,
    opponent: str,
    home_away: str,
    df: pd.DataFrame,
) -> None:
    df = df.copy()
    df["year"] = year
    df["game_date"] = game_date
    df["opponent"] = opponent
    df["home_away"] = home_away
    df["row_order"] = range(len(df))
    conn.execute(
        "DELETE FROM game_batting WHERE year=? AND game_date=?",
        (year, game_date),
    )
    df.to_sql("game_batting", conn, if_exists="append", index=False)


def save_game_pitching(
    conn,
    year: int,
    game_date: str,
    opponent: str,
    home_away: str,
    df: pd.DataFrame,
) -> None:
    df = df.copy()
    df["year"] = year
    df["game_date"] = game_date
    df["opponent"] = opponent
    df["home_away"] = home_away
    df["row_order"] = range(len(df))
    conn.execute(
        "DELETE FROM game_pitching WHERE year=? AND game_date=?",
        (year, game_date),
    )
    df.to_sql("game_pitching", conn, if_exists="append", index=False)
