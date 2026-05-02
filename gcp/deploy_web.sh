#!/bin/bash
# Web ビューアを Cloud Run Service にデプロイするスクリプト。
export PATH="$PATH:/snap/bin"
#
# ============================================================
# 【初回のみ】Secret Manager にシークレットを登録する
# ============================================================
#
# 1. Google Cloud Console で OAuth 2.0 クライアント ID を作成:
#    https://console.cloud.google.com/apis/credentials
#    - 種類: ウェブアプリケーション
#    - 承認済みリダイレクト URI は初回デプロイ後に追加（下記参照）
#
# 2. シークレットを Secret Manager に保存:
#    PROJECT_ID="amplified-alpha-330603"
#    echo -n "YOUR_CLIENT_ID"     | gcloud secrets create npb-web-client-id     --data-file=- --project=${PROJECT_ID}
#    echo -n "YOUR_CLIENT_SECRET" | gcloud secrets create npb-web-client-secret --data-file=- --project=${PROJECT_ID}
#    python3 -c "import secrets; print(secrets.token_hex(32), end='')" \
#      | gcloud secrets create npb-web-secret-key --data-file=- --project=${PROJECT_ID}
#
# 3. サービスアカウントに Secret Accessor 権限を付与:
#    SA_EMAIL="npb-stats-job@${PROJECT_ID}.iam.gserviceaccount.com"
#    for SECRET in npb-web-client-id npb-web-client-secret npb-web-secret-key; do
#      gcloud secrets add-iam-policy-binding ${SECRET} \
#        --member="serviceAccount:${SA_EMAIL}" \
#        --role="roles/secretmanager.secretAccessor" \
#        --project=${PROJECT_ID}
#    done
#
# 4. このスクリプトを実行してデプロイ
#
# 5. デプロイ後、表示された URL を使って OAuth リダイレクト URI を追加:
#    Cloud Console > 認証情報 > クライアントID > 承認済みリダイレクト URI
#    → https://<SERVICE_URL>/auth/callback
# ============================================================

set -e

PROJECT_ID="amplified-alpha-330603"
REGION="asia-northeast1"
REPO_NAME="npb-stats"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/web"
SERVICE_NAME="npb-stats-web"
SA_EMAIL="npb-stats-job@${PROJECT_ID}.iam.gserviceaccount.com"
BUCKET_NAME="${PROJECT_ID}-npb-stats"
ALLOWED_EMAIL="mfujishiro49321@gmail.com"

cd "$(dirname "$0")/.."

echo "=== Docker イメージ ビルド・プッシュ ==="
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
docker build -f Dockerfile.web -t ${IMAGE_NAME}:latest .
docker push ${IMAGE_NAME}:latest

echo "=== Cloud Run Service デプロイ ==="
gcloud run deploy ${SERVICE_NAME} \
  --image=${IMAGE_NAME}:latest \
  --region=${REGION} \
  --service-account=${SA_EMAIL} \
  --memory=512Mi \
  --cpu=1 \
  --concurrency=80 \
  --min-instances=0 \
  --max-instances=2 \
  --allow-unauthenticated \
  --set-env-vars="GCS_BUCKET=${BUCKET_NAME},ALLOWED_EMAIL=${ALLOWED_EMAIL}" \
  --set-secrets="GOOGLE_CLIENT_ID=npb-web-client-id:latest,GOOGLE_CLIENT_SECRET=npb-web-client-secret:latest,FLASK_SECRET_KEY=npb-web-secret-key:latest" \
  --project=${PROJECT_ID}

echo ""
echo "=== デプロイ完了 ==="
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --region=${REGION} --project=${PROJECT_ID} \
  --format="value(status.url)")
echo "URL: ${SERVICE_URL}"
echo ""
echo "【次のステップ】OAuth リダイレクト URI を Cloud Console に追加してください:"
echo "  ${SERVICE_URL}/auth/callback"
