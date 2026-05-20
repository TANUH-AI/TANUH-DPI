#!/bin/bash

# refresh_token.sh
# Fetches a fresh gcloud access token and updates the API_KEY in .env

ENV_FILE="$(dirname "$0")/../.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: .env file not found at $ENV_FILE"
  exit 1
fi

echo "Fetching fresh gcloud access token..."
FRESH_TOKEN=$(gcloud auth print-access-token)

if [ -z "$FRESH_TOKEN" ]; then
  echo "Error: Failed to retrieve token. Are you logged in? Run: gcloud auth login"
  exit 1
fi

# Update API_KEY in .env (no quotes — compatible with docker-compose env_file)
sed -i '' "s|API_KEY=.*|API_KEY=${FRESH_TOKEN}|" "$ENV_FILE"

echo "✅ API_KEY updated successfully in .env"
echo "Token expires in ~1 hour."
