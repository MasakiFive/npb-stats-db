"""DataFrameをSQLiteに保存する層。"""
import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "npb.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


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
