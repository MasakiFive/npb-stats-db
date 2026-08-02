"""main.scrape_hawks_games の統合テスト。

fetch を差し替えてフィクスチャHTMLを返し、ネットワークにも本番DBにも触れずに
中止試合のスキップと取得済み試合のスキップ判定を検証する。
"""
import pytest

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
