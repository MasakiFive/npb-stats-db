"""scraper.parse の回帰テスト。

フィクスチャHTML（tests/fixtures/）は NPB 公式ページの構造を最小限に模したもの。
現在のパーサが返す結果を固定し、リファクタや NPB 側の構造変更で
壊れたことを検知することが目的。
"""
import pandas as pd
import pytest

from scraper.parse import (
    TEAM_CODE_MAP,
    _extract_rank,
    _parse_innings,
    _split_player_team,
    parse_game_batting,
    parse_game_pitching,
    parse_player_batting,
    parse_player_fielding,
    parse_player_pitching,
    parse_schedule_game_urls,
    parse_standings,
    parse_stats_date,
    parse_team_batting,
    parse_team_fielding,
    parse_team_pitching,
)


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------

def test_parse_stats_date():
    assert parse_stats_date("<p>2026年4月17日 現在</p>") == "2026-04-17"
    assert parse_stats_date("2026年12月3日現在") == "2026-12-03"


def test_parse_stats_date_missing():
    with pytest.raises(ValueError):
        parse_stats_date("<p>日付なし</p>")


@pytest.mark.parametrize("raw, expected", [
    ("佐藤輝明(神)", ("佐藤輝明", "神")),
    ("近藤　健介(ソ)", ("近藤　健介", "ソ")),
    ("  柳田　悠岐(ソ)  ", ("柳田　悠岐", "ソ")),
    ("チーム計", ("チーム計", None)),
])
def test_split_player_team(raw, expected):
    assert _split_player_team(raw) == expected


def test_extract_rank():
    result = _extract_rank(pd.Series(["1位", "2", "", None]))
    assert result.iloc[0] == 1
    assert result.iloc[1] == 2
    assert pd.isna(result.iloc[2])
    assert pd.isna(result.iloc[3])


@pytest.mark.parametrize("raw, expected", [
    (6, 6.0),
    ("6", 6.0),
    ("5.1", 5 + 1 / 3),
    ("5.2", 5 + 2 / 3),
    ("0.1", 1 / 3),
    ("0.2", 2 / 3),
])
def test_parse_innings(raw, expected):
    assert _parse_innings(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, float("nan"), "-", "", "未定"])
def test_parse_innings_invalid(raw):
    assert _parse_innings(raw) is None


# ---------------------------------------------------------------------------
# 勝敗表
# ---------------------------------------------------------------------------

def test_parse_standings(html):
    df = parse_standings(html("std_p.html"), "P")

    assert list(df.columns) == [
        "league", "rank", "team", "games", "wins", "losses", "ties",
        "win_pct", "games_behind",
    ]
    assert len(df) == 6
    assert (df["league"] == "P").all()
    # 順位は行順から採番される
    assert list(df["rank"]) == [1, 2, 3, 4, 5, 6]

    top = df.iloc[0]
    assert top["team"] == "ソフトバンク"
    assert top["games"] == 20
    assert top["wins"] == 13
    assert top["losses"] == 6
    assert top["ties"] == 1
    assert top["win_pct"] == pytest.approx(0.684)
    # 首位の「--」は NaN になる
    assert pd.isna(top["games_behind"])

    assert df.iloc[1]["games_behind"] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# チーム成績
# ---------------------------------------------------------------------------

def test_parse_team_batting(html):
    df = parse_team_batting(html("tmb_p.html"), "P")

    assert len(df) == 3
    assert list(df["team"]) == ["ソフトバンク", "日本ハム", "西武"]
    assert (df["league"] == "P").all()
    assert "rank" not in df.columns  # チーム成績に順位列はない

    sb = df.iloc[0]
    assert sb["batting_avg"] == pytest.approx(0.271)
    assert sb["plate_appearances"] == 745
    assert sb["at_bats"] == 662
    assert sb["home_runs"] == 18
    assert sb["total_bases"] == 270
    assert sb["rbi"] == 88
    assert sb["walks"] == 55
    assert sb["grounded_into_dp"] == 13
    assert sb["on_base_pct"] == pytest.approx(0.330)


def test_parse_team_pitching(html):
    df = parse_team_pitching(html("tmp_p.html"), "P")

    assert len(df) == 3
    assert list(df["team"]) == ["ソフトバンク", "オリックス", "ロッテ"]

    sb = df.iloc[0]
    assert sb["era"] == pytest.approx(2.41)
    assert sb["saves"] == 7
    assert sb["hold_points"] == 28       # ＨＰ（全角）が正しく対応づく
    assert sb["innings_pitched"] == pytest.approx(179.0)
    assert sb["strikeouts"] == 163
    assert sb["earned_runs"] == 48


def test_parse_team_fielding(html):
    df = parse_team_fielding(html("tmf_p.html"), "P")

    assert len(df) == 3
    sb = df.iloc[0]
    assert sb["team"] == "ソフトバンク"
    assert sb["fielding_avg"] == pytest.approx(0.991)
    assert sb["chances"] == 760
    assert sb["assists"] == 216
    assert sb["errors"] == 7
    # 「併殺・参加」「併殺・球団」は部分一致で振り分けられる
    assert sb["double_plays_participated"] == 28
    assert sb["double_plays_team"] == 16
    assert sb["passed_balls"] == 1


# ---------------------------------------------------------------------------
# 個人成績
# ---------------------------------------------------------------------------

def test_parse_player_batting(html):
    df = parse_player_batting(html("bat_p.html"), "P")

    assert len(df) == 3
    assert list(df["rank"]) == [1, 2, 3]
    # 選手名とチームコードが分離される
    assert list(df["player"]) == ["近藤　健介", "柳田　悠岐", "万波　中正"]
    assert list(df["team"]) == ["ソ", "ソ", "日"]

    kondo = df.iloc[0]
    assert kondo["batting_avg"] == pytest.approx(0.362)
    assert kondo["plate_appearances"] == 85
    assert kondo["home_runs"] == 4
    assert kondo["walks"] == 14
    assert kondo["on_base_pct"] == pytest.approx(0.471)


def test_parse_player_pitching(html):
    df = parse_player_pitching(html("pit_p.html"), "P")

    assert len(df) == 3
    assert list(df["rank"]) == [1, 2, 3]
    assert list(df["player"]) == ["有原　航平", "モイネロ", "伊藤　大海"]
    assert list(df["team"]) == ["ソ", "ソ", "日"]

    arihara = df.iloc[0]
    assert arihara["era"] == pytest.approx(1.24)
    assert arihara["games"] == 4           # 「登板」→ games
    assert arihara["innings_pitched"] == pytest.approx(29.0)
    assert arihara["strikeouts"] == 32
    assert arihara["win_pct"] == pytest.approx(1.000)


def test_parse_player_fielding(html):
    df = parse_player_fielding(html("fld_p.html"), "P")

    # 捕手2名 + 一塁手2名。「お知らせ」見出しのテーブルは取り込まれない
    assert len(df) == 4
    assert list(df["position"]) == ["C", "C", "1B", "1B"]
    assert list(df["player"]) == ["甲斐　拓也", "田村　龍弘", "山川　穂高", "頓宮　裕真"]
    assert list(df["team"]) == ["ソ", "ロ", "ソ", "オ"]

    kai = df.iloc[0]
    assert kai["fielding_avg"] == pytest.approx(1.000)
    assert kai["putouts"] == 121
    assert kai["passed_balls"] == 0

    # 一塁手テーブルには捕逸列がないため NaN で埋まる
    assert pd.isna(df.iloc[2]["passed_balls"])
    assert df.iloc[2]["double_plays"] == 14


def test_parse_player_fielding_no_position_heading():
    with pytest.raises(ValueError, match="守備ポジションテーブル"):
        parse_player_fielding("<html><h5>お知らせ</h5><table></table></html>", "P")


# ---------------------------------------------------------------------------
# ホークス試合スケジュール
# ---------------------------------------------------------------------------

def test_parse_schedule_game_urls(html):
    games = parse_schedule_game_urls(html("schedule_04.html"), 2026)

    # ホークスの3試合のみ。同一試合への重複リンクは1件に畳まれる
    assert len(games) == 3

    assert games[0] == {
        "url": "https://npb.jp/scores/2026/0403/h-l-01/box.html",
        "game_date": "2026-04-03",
        "home_away": "A",
        "opponent": "西武",
    }
    assert games[1] == {
        "url": "https://npb.jp/scores/2026/0405/f-h-01/box.html",
        "game_date": "2026-04-05",
        "home_away": "H",
        "opponent": "日本ハム",
    }
    # 2文字のチームコード（bs）も解決できる
    assert games[2]["opponent"] == "オリックス"
    assert games[2]["home_away"] == "H"


def test_parse_schedule_game_urls_no_hawks():
    html_str = '<a href="/scores/2026/0405/g-t-01/">巨人-阪神</a>'
    assert parse_schedule_game_urls(html_str, 2026) == []


def test_team_code_map_covers_12_teams():
    assert len(TEAM_CODE_MAP) == 12


# ---------------------------------------------------------------------------
# ボックススコア（打撃）
# ---------------------------------------------------------------------------

def test_parse_game_batting_home(html):
    df = parse_game_batting(html("box.html"), "H")

    # 「合計」行は除外される
    assert list(df["player"]) == ["周東　佑京", "柳田　悠岐", "山川　穂高"]
    assert list(df["position"]) == ["中", "指", "一"]

    shuto = df.iloc[0]
    assert shuto["at_bats"] == 3
    assert shuto["hits"] == 2
    assert shuto["stolen_bases"] == 1
    # 打席結果セルから集計: 遊ゴ/中安/四球/左安（"-" は打席に数えない）
    assert shuto["plate_appearances"] == 4
    assert shuto["walks"] == 1
    assert shuto["home_runs"] == 0

    yanagita = df.iloc[1]
    assert yanagita["plate_appearances"] == 5
    assert yanagita["home_runs"] == 2      # 中本 + 右本
    assert yanagita["walks"] == 1
    assert yanagita["rbi"] == 3

    yamakawa = df.iloc[2]
    assert yamakawa["walks"] == 0          # 「死球」は四球に数えない
    assert yamakawa["plate_appearances"] == 5


def test_parse_game_batting_away(html):
    df = parse_game_batting(html("box.html"), "A")

    # 「チーム計」行は除外される
    assert list(df["player"]) == ["万波　中正", "清宮　幸太郎"]
    assert df.iloc[0]["home_runs"] == 1
    assert df.iloc[1]["walks"] == 1


def test_parse_game_batting_int64_dtype(html):
    df = parse_game_batting(html("box.html"), "H")
    for col in ["at_bats", "plate_appearances", "runs", "hits",
                "home_runs", "rbi", "stolen_bases", "walks"]:
        assert str(df[col].dtype) == "Int64"


def test_parse_game_batting_no_batting_table():
    """打撃テーブルが無いページ（中止・構造変更）では ValueError になる。"""
    html_str = "<table><tr><th>状態</th></tr><tr><td>中止</td></tr></table>"
    with pytest.raises(ValueError, match="打撃テーブル"):
        parse_game_batting(html_str, "H")


def test_parse_game_batting_missing_away_table(html):
    """打撃テーブルが1つしか無いのにアウェーを要求した場合。"""
    single = html("box.html").split("<!-- ビジターチーム打撃")[0]
    with pytest.raises(ValueError, match="打撃テーブルが2個ありません"):
        parse_game_batting(single, "A")


# ---------------------------------------------------------------------------
# ボックススコア（投手）
# ---------------------------------------------------------------------------

def test_parse_game_pitching_home(html):
    df = parse_game_pitching(html("box.html"), "H")

    # 「チーム計」行と投球回端数の汚染行（".2"）が除去される
    assert list(df["pitcher"]) == ["有原　航平", "モイネロ", "オスナ"]

    arihara = df.iloc[0]
    assert arihara["result"] == "○"
    assert arihara["innings_pitched"] == pytest.approx(6.0)
    assert arihara["batters_faced"] == 23
    assert arihara["strikeouts"] == 8
    assert arihara["earned_runs"] == 1

    # 5.1 = 5回1/3、0.2 = 2/3 に変換される
    assert df.iloc[1]["innings_pitched"] == pytest.approx(5 + 1 / 3)
    assert df.iloc[2]["innings_pitched"] == pytest.approx(2 / 3)

    # ○/● 以外（セーブ記号など）は None に正規化される
    assert df.iloc[1]["result"] is None
    assert df.iloc[2]["result"] is None


def test_parse_game_pitching_away(html):
    df = parse_game_pitching(html("box.html"), "A")

    assert list(df["pitcher"]) == ["伊藤　大海", "田中　正義"]
    assert df.iloc[0]["result"] == "●"
    assert df.iloc[0]["innings_pitched"] == pytest.approx(7.0)


def test_parse_game_pitching_no_pitching_table():
    """投手テーブルが無いページ（中止・構造変更）では ValueError になる。"""
    html_str = "<table><tr><th>状態</th></tr><tr><td>中止</td></tr></table>"
    with pytest.raises(ValueError, match="投手テーブル"):
        parse_game_pitching(html_str, "H")
