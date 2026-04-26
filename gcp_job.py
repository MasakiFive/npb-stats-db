"""Cloud Run Job エントリーポイント。
GCS から DB をダウンロード → スクレイピング実行 → GCS へアップロード → メール通知。
"""
import os
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from google.cloud import storage

BUCKET_NAME    = os.environ.get("GCS_BUCKET", "amplified-alpha-330603-npb-stats")
GCS_DB_BLOB    = os.environ.get("GCS_DB_BLOB", "npb.db")
DB_PATH        = Path(__file__).resolve().parent / "data" / "npb.db"
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL", "")


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


def send_notification(subject: str, body: str) -> None:
    """Gmail SMTP でメール通知を送る。設定が未完了の場合はスキップ。"""
    if not all([GMAIL_USER, GMAIL_PASSWORD, NOTIFY_EMAIL]):
        print("[Mail] 通知設定が未完了のためスキップ")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_EMAIL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.send_message(msg)
        print(f"[Mail] 通知送信完了: {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"[Mail] 通知送信失敗: {e}")


def main() -> None:
    from zoneinfo import ZoneInfo
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.now(jst)
    year = now_jst.year
    today = now_jst.strftime("%Y-%m-%d")
    print(f"=== NPB Stats Job 開始: {now_jst.isoformat()} ===")

    download_db()

    print(f"[scraper] python main.py --year {year} 実行中...")
    result = subprocess.run(
        [sys.executable, "main.py", "--year", str(year)],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print(f"[scraper] main.py が異常終了しました (code={result.returncode})")
        upload_db()
        send_notification(
            subject=f"[NPB] スクレイピング失敗 {today}",
            body=(
                f"スクレイピングが失敗しました。\n\n"
                f"日付: {today}\n"
                f"終了コード: {result.returncode}\n\n"
                f"--- エラー出力 ---\n{result.stderr or '(なし)'}\n\n"
                f"--- 標準出力 ---\n{result.stdout or '(なし)'}"
            ),
        )
        sys.exit(result.returncode)

    upload_db()
    print(f"=== NPB Stats Job 完了: {datetime.now().isoformat()} ===")

    send_notification(
        subject=f"[NPB] スクレイピング完了 {today}",
        body=(
            f"スクレイピングが正常に完了しました。\n\n"
            f"日付: {today}\n\n"
            f"--- 実行結果 ---\n{result.stdout}"
        ),
    )


if __name__ == "__main__":
    main()
