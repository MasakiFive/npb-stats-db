"""HTMLから成績テーブルを取り出してDataFrameに整形。"""
import re
from io import StringIO
from datetime import datetime
import pandas as pd
from bs4 import BeautifulSoup


def parse_stats_date(html: str) -> str:
    """「2026年4月17日 現在」のような文字列から日付を抽出。"""
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*現在", html)
    if not m:
        raise ValueError("stats_date が見つかりません")
    y, mo, d = map(int, m.groups())
    return datetime(y, mo, d).date().isoformat()


def parse_standings(html: str, league: str) -> pd.DataFrame:
    """勝敗表のDataFrameを返す。"""
    # pandas 2.x では StringIO で包む必要がある
    tables = pd.read_html(StringIO(html))

    # 勝敗表は「試合/勝利/敗北/勝率」を列に持つテーブル
    df = next(
        t for t in tables
        if {"試合", "勝利", "敗北", "勝率"}.issubset(set(t.columns.astype(str)))
    )

    # 主要7列だけ残す（ホーム/ロード/対戦成績は初期版では捨てる）
    df = df.rename(columns={
        df.columns[0]: "team",
        "試合": "games",
        "勝利": "wins",
        "敗北": "losses",
        "引分": "ties",
        "勝率": "win_pct",
        "差": "games_behind",
    })
    df = df[["team", "games", "wins", "losses", "ties", "win_pct", "games_behind"]].copy()

    df["league"] = league
    df["rank"] = range(1, len(df) + 1)
    df["games_behind"] = pd.to_numeric(df["games_behind"], errors="coerce")  # "--" → NaN

    return df[["league", "rank", "team", "games", "wins", "losses", "ties",
               "win_pct", "games_behind"]]


def _split_player_team(name: str):
    """'佐藤輝明(神)' → ('佐藤輝明', '神')。チームコードが取れない場合は (name, None)。"""
    m = re.match(r"^(.+?)\(([^)]+)\)$", str(name).strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return str(name).strip(), None


def _to_numeric_cols(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """指定列を pd.to_numeric で変換（変換不能値は NaN）。"""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _extract_rank(series: pd.Series) -> pd.Series:
    """'1位' や '1' など数字を含む文字列から整数を取り出す。"""
    return pd.to_numeric(series.astype(str).str.extract(r"(\d+)", expand=False), errors="coerce")


# ---------------------------------------------------------------------------
# チーム打撃 (tmb_c / tmb_p)
# ---------------------------------------------------------------------------
def parse_team_batting(html: str, league: str) -> pd.DataFrame:
    """チーム打撃成績のDataFrameを返す。"""
    tables = pd.read_html(StringIO(html))

    # チーム打撃テーブル: 打率・打席・塁打・打点を持ち、順位列がないもの
    df = next(
        t for t in tables
        if {"打率", "打席", "塁打", "打点"}.issubset(set(t.columns.astype(str)))
        and "順位" not in t.columns.astype(str)
    )

    # 列名 → 英語カラム名マッピング
    rename = {
        df.columns[0]: "team",   # チーム名列（"チーム" 等）
        "打率": "batting_avg",
        "試合": "games",
        "打席": "plate_appearances",
        "打数": "at_bats",
        "得点": "runs",
        "安打": "hits",
        "二塁打": "doubles",
        "三塁打": "triples",
        "本塁打": "home_runs",
        "塁打": "total_bases",
        "打点": "rbi",
        "盗塁": "stolen_bases",
        "盗塁刺": "caught_stealing",
        "犠打": "sacrifice_hits",
        "犠飛": "sacrifice_flies",
        "四球": "walks",
        "故意四": "intentional_walks",
        "死球": "hit_by_pitch",
        "三振": "strikeouts",
        "併殺打": "grounded_into_dp",
        "長打率": "slugging_pct",
        "出塁率": "on_base_pct",
    }
    df = df.rename(columns=rename)

    numeric_cols = [
        "batting_avg", "games", "plate_appearances", "at_bats", "runs", "hits",
        "doubles", "triples", "home_runs", "total_bases", "rbi", "stolen_bases",
        "caught_stealing", "sacrifice_hits", "sacrifice_flies", "walks",
        "intentional_walks", "hit_by_pitch", "strikeouts", "grounded_into_dp",
        "slugging_pct", "on_base_pct",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "team", "batting_avg", "games", "plate_appearances",
                "at_bats", "runs", "hits", "doubles", "triples", "home_runs",
                "total_bases", "rbi", "stolen_bases", "caught_stealing",
                "sacrifice_hits", "sacrifice_flies", "walks", "intentional_walks",
                "hit_by_pitch", "strikeouts", "grounded_into_dp", "slugging_pct",
                "on_base_pct"]
    return df[[c for c in cols_out if c in df.columns]]


# ---------------------------------------------------------------------------
# チーム投手 (tmp_c / tmp_p)
# ---------------------------------------------------------------------------
def parse_team_pitching(html: str, league: str) -> pd.DataFrame:
    """チーム投手成績のDataFrameを返す。"""
    tables = pd.read_html(StringIO(html))

    # チーム投手テーブル: 防御率・投球回・自責点を持ち、順位列がないもの
    df = next(
        t for t in tables
        if {"防御率", "投球回", "自責点"}.issubset(set(t.columns.astype(str)))
        and "順位" not in t.columns.astype(str)
    )

    rename = {
        df.columns[0]: "team",   # チーム名列
        "防御率": "era",
        "試合": "games",
        "勝利": "wins",
        "敗北": "losses",
        "セーブ": "saves",
        "ホールド": "holds",
        "ＨＰ": "hold_points",
        "完投": "complete_games",
        "完封勝": "shutouts",
        "無四球": "no_walks",
        "勝率": "win_pct",
        "打者": "batters_faced",
        "投球回": "innings_pitched",
        "安打": "hits",
        "本塁打": "home_runs",
        "四球": "walks",
        "故意四": "intentional_walks",
        "死球": "hit_by_pitch",
        "三振": "strikeouts",
        "暴投": "wild_pitches",
        "ボーク": "balks",
        "失点": "runs",
        "自責点": "earned_runs",
    }
    df = df.rename(columns=rename)

    numeric_cols = [
        "era", "games", "wins", "losses", "saves", "holds", "hold_points",
        "complete_games", "shutouts", "no_walks", "win_pct", "batters_faced",
        "innings_pitched", "hits", "home_runs", "walks", "intentional_walks",
        "hit_by_pitch", "strikeouts", "wild_pitches", "balks", "runs", "earned_runs",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "team", "era", "games", "wins", "losses", "saves", "holds",
                "hold_points", "complete_games", "shutouts", "no_walks", "win_pct",
                "batters_faced", "innings_pitched", "hits", "home_runs", "walks",
                "intentional_walks", "hit_by_pitch", "strikeouts", "wild_pitches",
                "balks", "runs", "earned_runs"]
    return df[[c for c in cols_out if c in df.columns]]


# ---------------------------------------------------------------------------
# チーム守備 (tmf_c / tmf_p)
# ---------------------------------------------------------------------------
def parse_team_fielding(html: str, league: str) -> pd.DataFrame:
    """チーム守備成績のDataFrameを返す。"""
    tables = pd.read_html(StringIO(html))

    # チーム守備テーブル: 守備率・守備機会・補殺を持つもの
    df = next(
        t for t in tables
        if {"守備率", "守備機会", "補殺"}.issubset(set(t.columns.astype(str)))
    )

    # 「併殺・参加」「併殺・球団」のように「・」区切りの列名を動的に対応
    col_names = list(df.columns.astype(str))
    rename = {col_names[0]: "team"}
    for c in col_names:
        if c == "守備率":
            rename[c] = "fielding_avg"
        elif c == "試合":
            rename[c] = "games"
        elif c == "守備機会":
            rename[c] = "chances"
        elif c == "刺殺":
            rename[c] = "putouts"
        elif c == "補殺":
            rename[c] = "assists"
        elif c == "失策":
            rename[c] = "errors"
        elif "参加" in c:
            rename[c] = "double_plays_participated"
        elif "球団" in c:
            rename[c] = "double_plays_team"
        elif c == "捕逸":
            rename[c] = "passed_balls"

    df = df.rename(columns=rename)

    numeric_cols = [
        "fielding_avg", "games", "chances", "putouts", "assists", "errors",
        "double_plays_participated", "double_plays_team", "passed_balls",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "team", "fielding_avg", "games", "chances", "putouts",
                "assists", "errors", "double_plays_participated", "double_plays_team",
                "passed_balls"]
    return df[[c for c in cols_out if c in df.columns]]


# ---------------------------------------------------------------------------
# 個人打撃ランキング (bat_c / bat_p)  ※規定打席以上
# ---------------------------------------------------------------------------
def parse_player_batting(html: str, league: str) -> pd.DataFrame:
    """個人打撃成績のDataFrameを返す（規定打席以上）。"""
    tables = pd.read_html(StringIO(html))

    # 個人打撃テーブル: 打率・打席・塁打・順位を持つもの
    df = next(
        t for t in tables
        if {"打率", "打席", "塁打", "順位"}.issubset(set(t.columns.astype(str)))
    )

    rename = {
        "順位": "rank",
        "選手": "player_raw",
        "打率": "batting_avg",
        "試合": "games",
        "打席": "plate_appearances",
        "打数": "at_bats",
        "得点": "runs",
        "安打": "hits",
        "二塁打": "doubles",
        "三塁打": "triples",
        "本塁打": "home_runs",
        "塁打": "total_bases",
        "打点": "rbi",
        "盗塁": "stolen_bases",
        "盗塁刺": "caught_stealing",
        "犠打": "sacrifice_hits",
        "犠飛": "sacrifice_flies",
        "四球": "walks",
        "故意四": "intentional_walks",
        "死球": "hit_by_pitch",
        "三振": "strikeouts",
        "併殺打": "grounded_into_dp",
        "長打率": "slugging_pct",
        "出塁率": "on_base_pct",
    }
    df = df.rename(columns=rename)

    # 選手名とチームコードを分離: '佐藤輝明(神)' → player='佐藤輝明', team='神'
    df[["player", "team"]] = df["player_raw"].apply(
        lambda x: pd.Series(_split_player_team(x))
    )
    df = df.drop(columns=["player_raw"])

    # rank: '1位' のような表記にも対応
    df["rank"] = _extract_rank(df["rank"])

    numeric_cols = [
        "batting_avg", "games", "plate_appearances", "at_bats", "runs", "hits",
        "doubles", "triples", "home_runs", "total_bases", "rbi", "stolen_bases",
        "caught_stealing", "sacrifice_hits", "sacrifice_flies", "walks",
        "intentional_walks", "hit_by_pitch", "strikeouts", "grounded_into_dp",
        "slugging_pct", "on_base_pct",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "player", "team", "rank", "batting_avg", "games",
                "plate_appearances", "at_bats", "runs", "hits", "doubles", "triples",
                "home_runs", "total_bases", "rbi", "stolen_bases", "caught_stealing",
                "sacrifice_hits", "sacrifice_flies", "walks", "intentional_walks",
                "hit_by_pitch", "strikeouts", "grounded_into_dp", "slugging_pct",
                "on_base_pct"]
    return df[[c for c in cols_out if c in df.columns]]


# ---------------------------------------------------------------------------
# 個人投手ランキング (pit_c / pit_p)  ※規定投球回以上
# ---------------------------------------------------------------------------
def parse_player_pitching(html: str, league: str) -> pd.DataFrame:
    """個人投手成績のDataFrameを返す（規定投球回以上、ページ先頭テーブルのみ）。"""
    tables = pd.read_html(StringIO(html))

    # 規定投球回以上テーブル: 防御率・投球回・自責点・順位を持つ最初のもの
    df = next(
        t for t in tables
        if {"防御率", "投球回", "自責点", "順位"}.issubset(set(t.columns.astype(str)))
    )

    rename = {
        "順位": "rank",
        "投手": "player_raw",
        "防御率": "era",
        "登板": "games",
        "勝利": "wins",
        "敗北": "losses",
        "セーブ": "saves",
        "ホールド": "holds",
        "ＨＰ": "hold_points",
        "完投": "complete_games",
        "完封勝": "shutouts",
        "無四球": "no_walks",
        "勝率": "win_pct",
        "打者": "batters_faced",
        "投球回": "innings_pitched",
        "安打": "hits",
        "本塁打": "home_runs",
        "四球": "walks",
        "故意四": "intentional_walks",
        "死球": "hit_by_pitch",
        "三振": "strikeouts",
        "暴投": "wild_pitches",
        "ボーク": "balks",
        "失点": "runs",
        "自責点": "earned_runs",
    }
    df = df.rename(columns=rename)

    # 投手名とチームコードを分離: '髙橋　遥人(神)' → player='髙橋　遥人', team='神'
    df[["player", "team"]] = df["player_raw"].apply(
        lambda x: pd.Series(_split_player_team(x))
    )
    df = df.drop(columns=["player_raw"])

    df["rank"] = _extract_rank(df["rank"])

    numeric_cols = [
        "era", "games", "wins", "losses", "saves", "holds", "hold_points",
        "complete_games", "shutouts", "no_walks", "win_pct", "batters_faced",
        "innings_pitched", "hits", "home_runs", "walks", "intentional_walks",
        "hit_by_pitch", "strikeouts", "wild_pitches", "balks", "runs", "earned_runs",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "player", "team", "rank", "era", "games", "wins", "losses",
                "saves", "holds", "hold_points", "complete_games", "shutouts", "no_walks",
                "win_pct", "batters_faced", "innings_pitched", "hits", "home_runs",
                "walks", "intentional_walks", "hit_by_pitch", "strikeouts", "wild_pitches",
                "balks", "runs", "earned_runs"]
    return df[[c for c in cols_out if c in df.columns]]


# ---------------------------------------------------------------------------
# 個人守備ランキング (fld_c / fld_p)
# ---------------------------------------------------------------------------

# 守備位置の日本語→英語略称マッピング
_POSITION_MAP = {
    "一塁手": "1B",
    "二塁手": "2B",
    "三塁手": "3B",
    "遊撃手": "SS",
    "外野手": "OF",
    "捕手":   "C",
    "投手":   "P",
}


def parse_player_fielding(html: str, league: str) -> pd.DataFrame:
    """個人守備成績のDataFrameを返す（全ポジション統合）。

    fld ページはポジション別に h5 見出し + テーブルが並ぶ構造のため
    BeautifulSoup でセクション見出しを特定してから pd.read_html を適用する。
    """
    soup = BeautifulSoup(html, "lxml")
    all_dfs = []

    for h5 in soup.find_all("h5"):
        heading = h5.get_text(strip=True)
        position_jp = next(
            (jp for jp in _POSITION_MAP if jp in heading), None
        )
        if position_jp is None:
            continue

        table_tag = h5.find_next("table")
        if table_tag is None:
            continue

        tbl = pd.read_html(StringIO(str(table_tag)))[0]
        tbl["position"] = _POSITION_MAP[position_jp]
        all_dfs.append(tbl)

    if not all_dfs:
        raise ValueError("守備ポジションテーブルが見つかりません")

    df = pd.concat(all_dfs, ignore_index=True)

    rename = {
        "順位": "rank",
        "選手": "player_raw",
        "守備率": "fielding_avg",
        "試合": "games",
        "刺殺": "putouts",
        "補殺": "assists",
        "失策": "errors",
        "併殺": "double_plays",
        "捕逸": "passed_balls",
    }
    df = df.rename(columns=rename)

    # 選手名とチームコードを分離
    df[["player", "team"]] = df["player_raw"].apply(
        lambda x: pd.Series(_split_player_team(x))
    )
    df = df.drop(columns=["player_raw"])

    df["rank"] = _extract_rank(df["rank"])

    numeric_cols = [
        "fielding_avg", "games", "putouts", "assists", "errors",
        "double_plays", "passed_balls",
    ]
    df = _to_numeric_cols(df, numeric_cols)
    df["league"] = league

    cols_out = ["league", "position", "player", "team", "rank", "fielding_avg",
                "games", "putouts", "assists", "errors", "double_plays", "passed_balls"]
    return df[[c for c in cols_out if c in df.columns]]