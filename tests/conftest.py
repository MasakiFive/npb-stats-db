"""テスト共通の設定とフィクスチャ。"""
import sys
from pathlib import Path

import pytest

# リポジトリルートを import パスに追加（scraper パッケージを解決するため）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> str:
    """tests/fixtures/<name> を文字列で読み込む。"""
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def html():
    """フィクスチャHTMLを名前で読み込むローダーを返す。"""
    return load_fixture
