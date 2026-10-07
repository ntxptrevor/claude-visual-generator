#!/usr/bin/env bash
# One-time NTXP Google Workspace access setup. Run as a Workspace super admin
# with gcloud installed and logged in (gcloud auth login).
#
#   bash scripts/google_workspace/setup_dwd.sh [PROJECT_ID]
#
# Creates a service account for domain-wide delegation, enables the Workspace
# APIs, creates a Maps API key, and prints the one manual Admin-console step.
# Secrets are written outside the repo (~/.config/ntxp, mode 600) — move them
# into the NTXP secrets vault, then delete the local copies.
set -euo pipefail

PROJECT_ID="${1:-ntxp-workspace-agent}"
SA_NAME="ntxp-workspace-agent"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
OUT_DIR="${HOME}/.config/ntxp"
KEY_FILE="${OUT_DIR}/ntxp-workspace-sa.json"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v gcloud >/dev/null || { echo "gcloud not found: https://cloud.google.com/sdk/docs/install"; exit 1; }
ADMIN="$(gcloud config get-value account 2>/dev/null)"
[ -n "$ADMIN" ] || { echo "Run: gcloud auth login"; exit 1; }
echo "==> Admin: $ADMIN   Project: $PROJECT_ID"

if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name="NTXP Workspace Agent"
fi
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs"
gcloud services enable \
  gmail.googleapis.com drive.googleapis.com calendar-json.googleapis.com \
  sheets.googleapis.com docs.googleapis.com slides.googleapis.com \
  people.googleapis.com tasks.googleapis.com admin.googleapis.com \
  forms.googleapis.com chat.googleapis.com \
  iamcredentials.googleapis.com apikeys.googleapis.com \
  places.googleapis.com geocoding-backend.googleapis.com \
  routes.googleapis.com timezone-backend.googleapis.com

echo "==> Service account"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="NTXP Workspace Agent"
CLIENT_ID="$(gcloud iam service-accounts describe "$SA_EMAIL" --format='value(oauth2ClientId)')"

mkdir -p "$OUT_DIR" && chmod 700 "$OUT_DIR"
if [ ! -f "$KEY_FILE" ]; then
  if gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$SA_EMAIL" 2>/dev/null; then
    chmod 600 "$KEY_FILE"
    echo "==> Key written to $KEY_FILE"
  else
    echo "==> Key creation blocked by org policy; using keyless mode instead."
    gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
      --member="user:${ADMIN}" --role="roles/iam.serviceAccountTokenCreator" >/dev/null
    echo "    Keyless: set NTXP_GOOGLE_SA_EMAIL=$SA_EMAIL and run"
    echo "    'gcloud auth application-default login' on each machine."
  fi
fi

echo "==> Maps API key"
MAPS_KEY_FILE="${OUT_DIR}/ntxp-maps-api-key.txt"
if [ ! -f "$MAPS_KEY_FILE" ]; then
  gcloud services api-keys create --display-name="NTXP Maps" \
    --api-target=service=places.googleapis.com \
    --api-target=service=geocoding-backend.googleapis.com \
    --api-target=service=routes.googleapis.com \
    --api-target=service=timezone-backend.googleapis.com \
    --format='value(response.keyString)' > "$MAPS_KEY_FILE"
  chmod 600 "$MAPS_KEY_FILE"
fi

SCOPES="$(python3 "$HERE/ntxp_google_access.py" scopes --csv)"

cat <<EOF

================  ONE MANUAL STEP (super admin, ~1 minute)  ================
Open: https://admin.google.com/ac/owl/domainwidedelegation
Click "Add new", then paste:

  Client ID:     $CLIENT_ID
  OAuth scopes:  $SCOPES

================  STORE THE SECRETS (then delete local copies)  ===========
  NTXP_GOOGLE_SA_KEY        = contents of $KEY_FILE   (if key mode)
  NTXP_GOOGLE_SA_EMAIL      = $SA_EMAIL                 (if keyless mode)
  NTXP_GOOGLE_ADMIN_SUBJECT = $ADMIN
  NTXP_GOOGLE_MAPS_KEY      = contents of $MAPS_KEY_FILE

Put them in the NTXP secrets vault / Claude Code environment variables.
Never commit them. Then test:

  python3 scripts/google_workspace/ntxp_google_access.py whoami
============================================================================
EOF
