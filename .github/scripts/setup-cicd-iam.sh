#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TANUH DPI — CI/CD IAM Setup Script
# ──────────────────────────────────────────────────────────────────────────────
# Run this once by someone with IAM Admin (roles/iam.admin) or Owner on
# proj-dpi-shared. It sets up everything needed for the GitHub Actions
# deploy.yml workflow to auto-deploy on every merge to main.
#
# What it does:
#   1. Grants deployment roles to sa-dpi-github-deploy
#   2. Creates a Workload Identity Federation pool + GitHub OIDC provider
#   3. Binds the GitHub repo to the SA via WIF
#   4. Prints the GitHub secrets you need to set
#
# Usage:
#   chmod +x .github/scripts/setup-cicd-iam.sh
#   ./.github/scripts/setup-cicd-iam.sh
#
# Prerequisites:
#   - gcloud CLI authenticated as a project Owner or IAM Admin
#   - The GitHub CLI (gh) for setting secrets (optional — can do manually)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="proj-dpi-shared"
PROJECT_NUMBER="334982157374"
REGION="asia-south1"
SA_EMAIL="sa-dpi-github-deploy@${PROJECT_ID}.iam.gserviceaccount.com"
POOL_NAME="github-actions"
PROVIDER_NAME="github-oidc"
GITHUB_ORG="TRANSLATIONAL-FOUNDATION"
GITHUB_REPO="TANUH-DPI"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  TANUH DPI — CI/CD IAM Setup"
echo "  Project: ${PROJECT_ID}"
echo "  SA:      ${SA_EMAIL}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Enable required APIs ────────────────────────────────────────────
echo "▸ Step 1: Enabling required APIs..."
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  compute.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}" --quiet
echo "  Done."

# ── Step 2: Grant deployment roles to the SA ────────────────────────────────
echo ""
echo "▸ Step 2: Granting deployment roles to ${SA_EMAIL}..."

ROLES=(
  "roles/compute.instanceAdmin.v1"
  "roles/iap.tunnelResourceAccessor"
  "roles/compute.viewer"
)

for ROLE in "${ROLES[@]}"; do
  echo "  Granting ${ROLE}..."
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet > /dev/null
done
echo "  Done."

# ── Step 3: Create Workload Identity Federation pool ────────────────────────
echo ""
echo "▸ Step 3: Creating WIF pool '${POOL_NAME}'..."
if gcloud iam workload-identity-pools describe "${POOL_NAME}" \
  --location=global --project="${PROJECT_ID}" &>/dev/null; then
  echo "  Pool already exists — skipping."
else
  gcloud iam workload-identity-pools create "${POOL_NAME}" \
    --location=global \
    --display-name="GitHub Actions" \
    --project="${PROJECT_ID}"
  echo "  Created."
fi

# ── Step 4: Create OIDC provider for GitHub ─────────────────────────────────
echo ""
echo "▸ Step 4: Creating OIDC provider '${PROVIDER_NAME}' in pool..."
if gcloud iam workload-identity-pools providers describe "${PROVIDER_NAME}" \
  --workload-identity-pool="${POOL_NAME}" \
  --location=global --project="${PROJECT_ID}" &>/dev/null; then
  echo "  Provider already exists — skipping."
else
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_NAME}" \
    --workload-identity-pool="${POOL_NAME}" \
    --location=global \
    --project="${PROJECT_ID}" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository_owner == '${GITHUB_ORG}'"
  echo "  Created."
fi

# ── Step 5: Allow GitHub repo to impersonate the SA ─────────────────────────
echo ""
echo "▸ Step 5: Binding WIF to SA (allowing GitHub repo to impersonate)..."
WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${WIF_MEMBER}" \
  --quiet > /dev/null
echo "  Done."

# ── Step 6: Print the values for GitHub secrets ─────────────────────────────
WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete! Set these GitHub secrets:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  GCP_SERVICE_ACCOUNT = ${SA_EMAIL}"
echo ""
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = ${WIF_PROVIDER}"
echo ""
echo "To set them via gh CLI (run from the repo):"
echo ""
echo "  gh secret set GCP_SERVICE_ACCOUNT -b '${SA_EMAIL}' -R ${GITHUB_ORG}/${GITHUB_REPO}"
echo "  gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER -b '${WIF_PROVIDER}' -R ${GITHUB_ORG}/${GITHUB_REPO}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  The deploy.yml workflow will now auto-deploy on merge."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
