"""scraper.store の保存・マイグレーション処理のテスト。

DB_PATH をテンポラリに差し替えて、本番DBに触れずに検証する。
"""
import sqlite3

import pandas as pd
import pytest

from scraper import store
from scraper.parse import (
    parse_game_batting,
    parse_game_pitching,
    parse_player_batting,
    parse_player_fielding,
    parse_player_pitching,
    parse_standings,
    parse_team_batting,
    parse_team_fielding,
    parse_team_pitching,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """テンポラリDBを初期化して返す。"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")
    store.init_db()
    conn = store.get_conn()
    yield conn
    conn.close()


def columns_of(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# スキーマ初期化
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "snapshots", "team_standings", "team_batting", "team_pitching",
    "team_fielding", "player_batting", "player_pitching", "player_fielding",
    "season_results", "game_batting", "game_pitching",
}


def test_init_db_creates_all_tables(db):
    tables = {
        r[0] for r in
        db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert EXPECTED_TABLES.issubset(tables)


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")
    store.init_db()
    store.init_db()  # 2回目でも例外にならない
    with store.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------

def test_upsert_snapshot_is_idempotent(db):
    first = store.upsert_snapshot(db, 2026, "2026-04-17")
    second = store.upsert_snapshot(db, 2026, "2026-04-17")
    assert first == second
    assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_upsert_snapshot_distinct_dates(db):
    a = store.upsert_snapshot(db, 2026, "2026-04-17")
    b = store.upsert_snapshot(db, 2026, "2026-04-18")
    assert a != b
    assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2


def test_snapshot_is_committed_before_return(db):
    """FK参照のため、返却前に別接続から見えている必要がある。"""
    snapshot_id = store.upsert_snapshot(db, 2026, "2026-04-17")
    other = sqlite3.connect(store.DB_PATH)
    try:
        row = other.execute(
            "SELECT id FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
    finally:
        other.close()
    assert row is not None


# ---------------------------------------------------------------------------
# 上書き保存
# ---------------------------------------------------------------------------

def _standings_df(league: str, wins: int) -> pd.DataFrame:
    return pd.DataFrame([{
        "league": league, "rank": 1, "team": "ソフトバンク", "games": 20,
        "wins": wins, "losses": 6, "ties": 1, "win_pct": 0.684,
        "games_behind": None,
    }])


def test_save_standings_overwrites_same_snapshot_and_league(db):
    snapshot_id = store.upsert_snapshot(db, 2026, "2026-04-17")
    store.save_standings(db, snapshot_id, _standings_df("P", 13))
    store.save_standings(db, snapshot_id, _standings_df("P", 14))

    rows = db.execute("SELECT wins FROM team_standings").fetchall()
    assert len(rows) == 1        # 重複せず上書きされる
    assert rows[0][0] == 14


def test_save_standings_keeps_other_league_on_same_snapshot(db):
    """セ・パが同一 stats_date の場合 snapshot_id を共有するため、
    片方の保存でもう片方が消えてはいけない。"""
    snapshot_id = store.upsert_snapshot(db, 2026, "2026-04-17")
    store.save_standings(db, snapshot_id, _standings_df("C", 11))
    store.save_standings(db, snapshot_id, _standings_df("P", 13))
    store.save_standings(db, snapshot_id, _standings_df("P", 14))

    leagues = {
        r[0] for r in db.execute("SELECT league FROM team_standings").fetchall()
    }
    assert leagues == {"C", "P"}
    assert db.execute("SELECT COUNT(*) FROM team_standings").fetchone()[0] == 2


def test_save_game_batting_overwrites_same_date(db):
    df = pd.DataFrame([{"position": "中", "player": "周東　佑京", "at_bats": 3,
                        "plate_appearances": 4, "runs": 1, "hits": 2,
                        "home_runs": 0, "rbi": 0, "stolen_bases": 1, "walks": 1}])
    store.save_game_batting(db, 2026, "2026-04-05", "日本ハム", "H", df)
    store.save_game_batting(db, 2026, "2026-04-05", "日本ハム", "H", df)

    assert db.execute("SELECT COUNT(*) FROM game_batting").fetchone()[0] == 1
    assert db.execute("SELECT row_order FROM game_batting").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# マイグレーション
# ---------------------------------------------------------------------------

OLD_GAME_BATTING_DDL = """
CREATE TABLE game_batting (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    year         INTEGER NOT NULL,
    game_date    DATE    NOT NULL,
    opponent     TEXT    NOT NULL,
    home_away    TEXT    NOT NULL CHECK(home_away IN ('H','A')),
    row_order    INTEGER NOT NULL,
    position     TEXT,
    player       TEXT    NOT NULL,
    at_bats      INTEGER,
    runs         INTEGER,
    hits         INTEGER,
    rbi          INTEGER,
    stolen_bases INTEGER
);
"""


def test_migrate_adds_missing_game_batting_columns(tmp_path, monkeypatch):
    """旧スキーマのDBに対して home_runs / plate_appearances / walks が追加される。"""
    db_path = tmp_path / "npb.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_GAME_BATTING_DDL)
    conn.execute(
        "INSERT INTO game_batting(year, game_date, opponent, home_away, row_order,"
        " position, player, at_bats, runs, hits, rbi, stolen_bases)"
        " VALUES (2026, '2026-04-05', '日本ハム', 'H', 0, '中', '周東　佑京', 3, 1, 2, 0, 1)"
    )
    conn.commit()
    conn.close()

    store.init_db()

    with store.get_conn() as conn:
        cols = columns_of(conn, "game_batting")
        assert {"home_runs", "plate_appearances", "walks"}.issubset(cols)
        # home_runs 追加時に旧データは破棄され、再スクレイプ対象になる
        assert conn.execute("SELECT COUNT(*) FROM game_batting").fetchone()[0] == 0


def test_migrate_removes_polluted_pitcher_rows(db):
    db.execute(
        "INSERT INTO game_pitching(year, game_date, opponent, home_away, row_order, pitcher)"
        " VALUES (2026, '2026-04-05', '日本ハム', 'H', 0, '有原　航平')"
    )
    db.execute(
        "INSERT INTO game_pitching(year, game_date, opponent, home_away, row_order, pitcher)"
        " VALUES (2026, '2026-04-05', '日本ハム', 'H', 1, '.1')"
    )
    db.commit()

    store._migrate(db)

    pitchers = [r[0] for r in db.execute("SELECT pitcher FROM game_pitching").fetchall()]
    assert pitchers == ["有原　航平"]


# ---------------------------------------------------------------------------
# parse → store の往復（列名とスキーマの整合性）
# ---------------------------------------------------------------------------

SNAPSHOT_ROUND_TRIPS = [
    ("std_p.html", parse_standings,       store.save_standings,       "team_standings"),
    ("tmb_p.html", parse_team_batting,    store.save_team_batting,    "team_batting"),
    ("tmp_p.html", parse_team_pitching,   store.save_team_pitching,   "team_pitching"),
    ("tmf_p.html", parse_team_fielding,   store.save_team_fielding,   "team_fielding"),
    ("bat_p.html", parse_player_batting,  store.save_player_batting,  "player_batting"),
    ("pit_p.html", parse_player_pitching, store.save_player_pitching, "player_pitching"),
    ("fld_p.html", parse_player_fielding, store.save_player_fielding, "player_fielding"),
]


@pytest.mark.parametrize("fixture, parse_fn, save_fn, table", SNAPSHOT_ROUND_TRIPS)
def test_parse_output_matches_schema(db, html, fixture, parse_fn, save_fn, table):
    """パーサの出力列がスキーマの列に収まることを確認する。"""
    snapshot_id = store.upsert_snapshot(db, 2026, "2026-04-17")
    df = parse_fn(html(fixture), "P")
    save_fn(db, snapshot_id, df)

    saved = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert saved == len(df)
    assert set(df.columns).issubset(columns_of(db, table))


def test_game_tables_round_trip(db, html):
    box = html("box.html")
    bat = parse_game_batting(box, "H")
    pit = parse_game_pitching(box, "H")

    store.save_game_batting(db, 2026, "2026-04-05", "日本ハム", "H", bat)
    store.save_game_pitching(db, 2026, "2026-04-05", "日本ハム", "H", pit)
    db.commit()

    assert db.execute("SELECT COUNT(*) FROM game_batting").fetchone()[0] == len(bat)
    assert db.execute("SELECT COUNT(*) FROM game_pitching").fetchone()[0] == len(pit)

    row = db.execute(
        "SELECT player, home_runs, walks, plate_appearances FROM game_batting"
        " WHERE player='柳田　悠岐'"
    ).fetchone()
    assert row == ("柳田　悠岐", 2, 1, 5)

    ip = db.execute(
        "SELECT innings_pitched FROM game_pitching WHERE pitcher='モイネロ'"
    ).fetchone()[0]
    assert ip == pytest.approx(5 + 1 / 3)
