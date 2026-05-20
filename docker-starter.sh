#!/bin/bash
set -e

# Ensure git submodules (e.g. privacy-filter-app) are present
echo "Initialising git submodules..."
git submodule update --init --recursive

# Build and start the docker containers in detached mode
echo "Starting docker-compose build and up..."
docker compose build && docker compose up -d

echo "Docker containers started successfully!"

# ── Configure host Apache2 reverse proxy ─────────────────────────────────────
PROXY_SCRIPT="$(dirname "$0")/scripts/setup_apache_proxy.sh"

if [ -f "$PROXY_SCRIPT" ]; then
    echo ""
    echo "▶ Configuring Apache2 reverse proxy..."
    bash "$PROXY_SCRIPT"
else
    echo "⚠  Proxy script not found at $PROXY_SCRIPT — skipping Apache2 configuration."
fi
