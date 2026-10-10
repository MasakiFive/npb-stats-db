"""main.scrape_hawks_games とシーズン判定の統合テスト。

fetch を差し替えてフィクスチャHTMLを返し、ネットワークにも本番DBにも触れずに
中止試合のスキップ、取得済み試合のスキップ判定、シーズン期間の判定を検証する。
"""
from datetime import date

import pytest
import requests

import main
from scraper import store

SCHEDULE_URL_04 = "https://npb.jp/games/2026/schedule_04_detail.html"
BOX_AWAY = "https://npb.jp/scores/2026/0403/h-l-01/box.html"       # 西武戦（ビジター）
BOX_HOME = "https://npb.jp/scores/2026/0405/f-h-01/box.html"       # 日本ハム戦（ホーム）
BOX_CANCELLED = "https://npb.jp/scores/2026/0410/bs-h-01/box.html"  # オリックス戦（中止）


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")
    store.init_db()
    conn = store.get_conn()
    yield conn
    conn.close()


@pytest.fixture
def fake_fetch(monkeypatch, html):
    """URL に応じてフィクスチャを返す fetch を main に注入する。"""
    pages = {
        SCHEDULE_URL_04: lambda: html("schedule_04.html"),
        BOX_AWAY: lambda: html("box.html"),
        BOX_HOME: lambda: html("box.html"),
        BOX_CANCELLED: lambda: html("box_cancelled.html"),
    }
    calls = []

    def _fetch(url, **kwargs):
        calls.append(url)
        if url in pages:
            return pages[url]()
        if "schedule_" in url:
            return "<html></html>"  # 4月以外は試合なし
        raise AssertionError(f"想定外のURL: {url}")

    monkeypatch.setattr(main, "fetch", _fetch)
    return calls


def test_cancelled_game_is_skipped_without_error(conn, fake_fetch, capsys):
    main.scrape_hawks_games(2026, conn)
    out = capsys.readouterr().out

    # 中止試合は情報ログとして扱われ、パースエラーにはならない
    assert "2026-04-10 vs オリックス 中止のためスキップ" in out
    assert "打撃テーブルが見つかりません" not in out
    assert "失敗" not in out


def test_played_games_are_saved_and_cancelled_is_not(conn, fake_fetch):
    main.scrape_hawks_games(2026, conn)

    dates = [
        r[0] for r in
        conn.execute("SELECT DISTINCT game_date FROM game_batting ORDER BY game_date")
    ]
    assert dates == ["2026-04-03", "2026-04-05"]  # 中止の 04-10 は保存されない


def test_already_scraped_games_are_not_refetched(conn, fake_fetch):
    """2回目の実行では取得済み試合を再取得しない（中止試合は毎回取りに行く）。"""
    main.scrape_hawks_games(2026, conn)
    fake_fetch.clear()
    main.scrape_hawks_games(2026, conn)

    box_urls = [u for u in fake_fetch if u.endswith("box.html")]
    assert BOX_AWAY not in box_urls
    assert BOX_HOME not in box_urls
    # 中止試合は DB に行が残らないため、判定のため毎回1回だけ取得される
    assert box_urls == [BOX_CANCELLED]


def test_games_after_until_are_not_scraped(conn, fake_fetch):
    """パ閉幕日より後の試合（ポストシーズン）は取得しない。"""
    main.scrape_hawks_games(2026, conn, until="2026-04-04")

    dates = [r[0] for r in conn.execute("SELECT DISTINCT game_date FROM game_batting")]
    assert dates == ["2026-04-03"]
    assert BOX_HOME not in fake_fetch


# --- シーズン判定 ---

NOT_STARTED = (main.NOT_STARTED, None)
FINISHED = (main.FINISHED, None)


def in_progress(d):
    return (main.IN_PROGRESS, d)


@pytest.mark.parametrize("status, final_dates, yesterday, expected", [
    # 開幕前
    ({"C": NOT_STARTED, "P": NOT_STARTED}, {}, "2027-01-09", (None, {})),
    # 両リーグシーズン中
    ({"C": in_progress("2026-07-01"), "P": in_progress("2026-07-01")}, {}, "2026-07-01",
     ("2026-07-01", {})),
    # パだけ閉幕した翌朝: セの基準日で取り込み、パの最終戦日を前日として記録
    ({"C": in_progress("2026-10-06"), "P": FINISHED}, {}, "2026-10-06",
     ("2026-10-06", {"P": "2026-10-06"})),
    # パ閉幕を記録済みでセはシーズン中: 引き続き取り込む
    ({"C": in_progress("2026-10-07"), "P": FINISHED}, {"P": "2026-10-06"}, "2026-10-07",
     ("2026-10-07", {})),
    # セも閉幕した翌朝: セの最終戦日で最終成績を取り込む
    ({"C": FINISHED, "P": FINISHED}, {"P": "2026-10-06"}, "2026-10-08",
     ("2026-10-08", {"C": "2026-10-08"})),
    # 両リーグの最終成績を取り込み済み: スキップ
    ({"C": FINISHED, "P": FINISHED}, {"C": "2026-10-08", "P": "2026-10-06"}, "2026-10-09",
     (None, {})),
])
def test_plan_run(status, final_dates, yesterday, expected):
    assert main.plan_run(status, final_dates, yesterday) == expected


def _http_error(status_code):
    res = requests.Response()
    res.status_code = status_code
    return requests.HTTPError(str(status_code), response=res)


@pytest.fixture
def season_fetch(monkeypatch, html):
    """両リーグ閉幕後の公式サイトを模した fetch。成績ページから日付表記が消えている。"""
    def _fetch(url, **kwargs):
        if url == "https://npb.jp/games/2026/":
            return html("games_top.html").replace("10月7日現在", "全日程終了")
        if "/bis/2026/stats/" in url:
            path = url.rsplit("/", 1)[1].replace("_c.html", "_p.html")
            return html(path).replace("2026年4月17日 現在", "")
        if "schedule_" in url:
            return "<html></html>"
        raise AssertionError(f"想定外のURL: {url}")

    monkeypatch.setattr(main, "fetch", _fetch)


def test_run_captures_final_stats_once(tmp_path, monkeypatch, season_fetch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")

    # 閉幕翌朝: 前日を基準日として両リーグの最終成績を取り込み、最終戦日を記録する
    assert main.run(2026, date(2026, 10, 9)) is True
    conn = store.get_conn()
    assert [r[0] for r in conn.execute("SELECT stats_date FROM snapshots")] == ["2026-10-08"]
    assert store.get_final_dates(conn, 2026) == {"C": "2026-10-08", "P": "2026-10-08"}
    assert conn.execute("SELECT COUNT(DISTINCT league) FROM team_standings").fetchone()[0] == 2

    # 翌日以降は取り込み済みなのでスキップし、スナップショットも増えない
    assert main.run(2026, date(2026, 10, 10)) is False
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
    conn.close()


def test_run_final_override(tmp_path, monkeypatch, season_fetch):
    """--final で最終戦日を明示すると、前日ではなくその日付で記録する。"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")

    assert main.run(2026, date(2026, 10, 11), {"C": "2026-10-08", "P": "2026-10-06"}) is True
    conn = store.get_conn()
    assert store.get_final_dates(conn, 2026) == {"C": "2026-10-08", "P": "2026-10-06"}
    assert [r[0] for r in conn.execute("SELECT stats_date FROM snapshots")] == ["2026-10-08"]
    conn.close()


def test_run_skips_before_season(tmp_path, monkeypatch):
    """翌年の公式戦ページが未公開（404）ならスキップし、成績ページを取りに行かない。"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "npb.db")
    calls = []

    def _fetch(url, **kwargs):
        calls.append(url)
        raise _http_error(404)

    monkeypatch.setattr(main, "fetch", _fetch)
    assert main.run(2027, date(2027, 1, 10)) is False
    assert calls == ["https://npb.jp/games/2027/"]


def test_season_status_propagates_other_http_errors(monkeypatch):
    """404 以外の取得失敗はシーズン外と誤判定せず例外にする。"""
    def _fetch(url, **kwargs):
        raise _http_error(503)

    monkeypatch.setattr(main, "fetch", _fetch)
    with pytest.raises(requests.HTTPError):
        main.get_season_status(2026)
