#!/bin/bash
# コード更新時: イメージを再ビルドして Cloud Run Job に反映する
set -e

PROJECT_ID="amplified-alpha-330603"
REGION="asia-northeast1"
REPO_NAME="npb-stats"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/scraper"
JOB_NAME="npb-stats-job"

cd "$(dirname "$0")/.."

echo "=== Docker イメージ再ビルド・プッシュ ==="
docker build -t ${IMAGE_NAME}:latest .
docker push ${IMAGE_NAME}:latest

echo "=== Cloud Run Job を最新イメージに更新 ==="
gcloud run jobs update ${JOB_NAME} \
  --image=${IMAGE_NAME}:latest \
  --region=${REGION} \
  --project=${PROJECT_ID}

echo "更新完了。次回の Scheduler 実行から新しいイメージが使われます。"
echo ""
echo "すぐに動作確認する場合:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT_ID}"
