"""歴代優勝データをDBに投入する。初回のみ実行。
使い方: python seed.py
"""
from scraper.store import init_db, get_conn
from pathlib import Path

SEEDS_PATH = Path(__file__).parent / "sql" / "seeds.sql"


def main() -> None:
    init_db()
    with get_conn() as conn:
        conn.executescript(SEEDS_PATH.read_text(encoding="utf-8"))
    print("Seeds loaded.")
    # 件数確認
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM season_results").fetchone()[0]
    print(f"  season_results: {count} 行")


if __name__ == "__main__":
    main()
