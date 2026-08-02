#!/bin/bash
# GCPリソースの初回セットアップスクリプト
#
# ============================================================
# 【実行前提】
# ============================================================
#
# 1. gcloud auth login 済み
#
# 2. 通知メール用のシークレットを Secret Manager に登録済み
#    （Gmail のアプリパスワードは https://myaccount.google.com/apppasswords で発行）
#
#    PROJECT_ID="amplified-alpha-330603"
#    echo -n "YOUR_GMAIL_ADDRESS"  | gcloud secrets create npb-gmail-user         --data-file=- --project=${PROJECT_ID}
#    echo -n "YOUR_APP_PASSWORD"   | gcloud secrets create npb-gmail-app-password --data-file=- --project=${PROJECT_ID}
#
# 実行後、Web ビューアは gcp/deploy_web.sh で別途デプロイする。
# WEB_URL（通知メールに載せる URL）はその後に設定する（末尾の案内を参照）。
# ============================================================

set -e

PROJECT_ID="amplified-alpha-330603"
REGION="asia-northeast1"
BUCKET_NAME="${PROJECT_ID}-npb-stats"
REPO_NAME="npb-stats"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/scraper"
JOB_NAME="npb-stats-job"
SA_NAME="npb-stats-job"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
NOTIFY_EMAIL="mfujishiro49321@gmail.com"

echo "=== 1. API の有効化 ==="
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project=${PROJECT_ID}

echo "=== 2. GCS バケット作成 ==="
gsutil mb -p ${PROJECT_ID} -l ${REGION} gs://${BUCKET_NAME}/
echo "バケット作成完了: gs://${BUCKET_NAME}"

echo "=== 3. サービスアカウント作成 ==="
gcloud iam service-accounts create ${SA_NAME} \
  --display-name="NPB Stats Job SA" \
  --project=${PROJECT_ID}

# GCS への読み書き権限
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Cloud Run Job の起動権限（Scheduler が使用）
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

# 通知メール用シークレットの読み取り権限（事前登録が必要。冒頭の実行前提を参照）
for SECRET in npb-gmail-user npb-gmail-app-password; do
  gcloud secrets add-iam-policy-binding ${SECRET} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=${PROJECT_ID}
done

echo "=== 4. Artifact Registry リポジトリ作成 ==="
gcloud artifacts repositories create ${REPO_NAME} \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID}

echo "=== 5. Docker イメージのビルド・プッシュ ==="
cd "$(dirname "$0")/.."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
docker build -t ${IMAGE_NAME}:latest .
docker push ${IMAGE_NAME}:latest

echo "=== 6. Cloud Run Job 作成 ==="
gcloud run jobs create ${JOB_NAME} \
  --image=${IMAGE_NAME}:latest \
  --region=${REGION} \
  --service-account=${SA_EMAIL} \
  --memory=512Mi \
  --cpu=1 \
  --task-timeout=600 \
  --set-env-vars="GCS_BUCKET=${BUCKET_NAME},GCS_DB_BLOB=npb.db,NOTIFY_EMAIL=${NOTIFY_EMAIL}" \
  --set-secrets="GMAIL_USER=npb-gmail-user:latest,GMAIL_APP_PASSWORD=npb-gmail-app-password:latest" \
  --project=${PROJECT_ID}

echo "=== 7. Cloud Scheduler 設定（毎朝8時 JST）==="
gcloud scheduler jobs create http ${JOB_NAME}-trigger \
  --location=${REGION} \
  --schedule="0 8 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --message-body="{}" \
  --oauth-service-account-email=${SA_EMAIL} \
  --project=${PROJECT_ID}

echo ""
echo "=== セットアップ完了 ==="
echo "バケット    : gs://${BUCKET_NAME}"
echo "イメージ    : ${IMAGE_NAME}:latest"
echo "Cloud Run Job: ${JOB_NAME} (${REGION})"
echo "Scheduler   : 毎朝 8:00 JST"
echo "通知先      : ${NOTIFY_EMAIL}"
echo ""
echo "手動テスト実行:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT_ID}"
echo ""
echo "【次のステップ】Web ビューアをデプロイし、通知メールに載せる URL を設定する:"
echo "  bash gcp/deploy_web.sh"
echo "  # 表示された URL を gcp/update.sh の WEB_URL に反映してから:"
echo "  bash gcp/update.sh"
