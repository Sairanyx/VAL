#!/bin/bash
# Fallback hosting on Google Cloud Run ($300 trial). Needs: gcloud CLI, `gcloud auth login`.
# Deploys the API (same image; Cloud Run has no GPU by default, so it serves on CPU). Usage: ./deploy/cloudrun.sh
set -euo pipefail
set -a; source .env; set +a
: "${GCP_PROJECT:?set GCP_PROJECT in .env}"
gcloud config set project "$GCP_PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/sinceai/api:latest"
gcloud artifacts repositories describe sinceai --location "$GCP_REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create sinceai --repository-format=docker --location "$GCP_REGION"
docker build -t "$IMAGE" .
gcloud auth configure-docker "$GCP_REGION-docker.pkg.dev" -q
docker push "$IMAGE"
ENV_VARS=$(grep -E '^(ANTHROPIC|OPENAI|FEATHERLESS|GEMINI|LLM_PROVIDER|HF_TOKEN)' .env | grep -v '=$' | paste -sd, -)
gcloud run deploy sinceai-api --image "$IMAGE" --region "$GCP_REGION" \
  --allow-unauthenticated --memory 4Gi --cpu 2 --port 8000 ${ENV_VARS:+--set-env-vars "$ENV_VARS"}
