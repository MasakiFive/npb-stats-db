"""Cloud Run Job エントリーポイント。
GCS から DB をダウンロード → スクレイピング実行 → GCS へアップロード。
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from google.cloud import storage

BUCKET_NAME = os.environ.get("GCS_BUCKET", "amplified-alpha-330603-npb-stats")
GCS_DB_BLOB = os.environ.get("GCS_DB_BLOB", "npb.db")
DB_PATH = Path(__file__).resolve().parent / "data" / "npb.db"


def download_db() -> None:
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(GCS_DB_BLOB)
    if blob.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(DB_PATH))
        print(f"[GCS] DB ダウンロード完了: gs://{BUCKET_NAME}/{GCS_DB_BLOB}")
    else:
        print("[GCS] DB が存在しないため新規作成します")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def upload_db() -> None:
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(GCS_DB_BLOB)
    blob.upload_from_filename(str(DB_PATH))
    print(f"[GCS] DB アップロード完了: gs://{BUCKET_NAME}/{GCS_DB_BLOB}")


def main() -> None:
    year = datetime.now().year
    print(f"=== NPB Stats Job 開始: {datetime.now().isoformat()} ===")

    download_db()

    print(f"[scraper] python main.py --year {year} 実行中...")
    result = subprocess.run(
        [sys.executable, "main.py", "--year", str(year)],
        cwd=Path(__file__).resolve().parent,
    )
    if result.returncode != 0:
        print(f"[scraper] main.py が異常終了しました (code={result.returncode})")
        upload_db()  # 途中結果があれば保存
        sys.exit(result.returncode)

    upload_db()
    print(f"=== NPB Stats Job 完了: {datetime.now().isoformat()} ===")


if __name__ == "__main__":
    main()
