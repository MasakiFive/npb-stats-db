"""NPB公式サイトからHTMLを取得する。マナー設定とローカルキャッシュを内包。"""
from pathlib import Path
import time
import requests
from datetime import date

USER_AGENT = "npb-personal-db/0.1 (personal research; contact: mfujishiro49321@gmail.com)"
SLEEP_SEC = 2.5
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def fetch(url: str, *, force: bool = False) -> str:
    """URLからHTMLを取得。同日中の再取得はキャッシュを返す。"""
    today = date.today().strftime("%Y%m%d")
    cache_path = CACHE_DIR / today / (url.replace("https://", "").replace("/", "_") + ".html")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8")

    time.sleep(SLEEP_SEC)
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    res.raise_for_status()
    res.encoding = res.apparent_encoding  # NPBサイトはShift_JIS系
    cache_path.write_text(res.text, encoding="utf-8")
    return res.text