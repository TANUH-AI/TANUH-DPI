#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# docker_clean.sh  —  Stop & remove all NHCX Hackathon Docker resources
#
# Usage:
#   ./scripts/docker_clean.sh          # clean project containers + images
#   ./scripts/docker_clean.sh --all    # also prune unused volumes & networks
#   ./scripts/docker_clean.sh --full   # full Docker system prune (EVERYTHING)
# ─────────────────────────────────────────────────────────────────────────────

set -e

COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docker-compose.yml"
MODE="${1:-}"

echo "═══════════════════════════════════════════════════"
echo "  🧹  NHCX Docker Cleanup Script"
echo "═══════════════════════════════════════════════════"

# ── Full system prune (nuclear option) ──────────────────────────────────────
if [[ "$MODE" == "--full" ]]; then
    echo ""
    echo "⚠️  WARNING: This will remove ALL Docker containers, images,"
    echo "   volumes, and networks system-wide (not just this project)."
    echo ""
    read -p "Are you sure? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi
    docker system prune -af --volumes
    echo "✅  Full Docker system prune complete."
    exit 0
fi

# ── Step 1: Stop & remove project containers via docker-compose ─────────────
echo ""
echo "▶  Step 1: Stopping project services (docker-compose down)..."
if [[ -f "$COMPOSE_FILE" ]]; then
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
    echo "   ✅  Services stopped."
else
    echo "   ⚠️  docker-compose.yml not found, skipping compose down."
fi

# ── Step 2: Remove project containers by name ────────────────────────────────
echo ""
echo "▶  Step 2: Removing project containers..."
for name in pdf2fhir pdf2nhcx frontend-service; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
        docker rm -f "$name" 2>/dev/null && echo "   🗑️  Removed container: $name"
    fi
done

# ── Step 3: Remove project images ────────────────────────────────────────────
echo ""
echo "▶  Step 3: Removing project images..."
for pattern in nhcx_hackathon ocr_service_problem pdf2fhir pdf2nhcx frontend; do
    images=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -i "$pattern" | awk '{print $2}' || true)
    if [[ -n "$images" ]]; then
        echo "$images" | xargs -r docker rmi -f 2>/dev/null && echo "   🗑️  Removed images matching: $pattern"
    fi
done

# ── Step 4 (optional --all): Remove dangling images, volumes, networks ────────
if [[ "$MODE" == "--all" ]]; then
    echo ""
    echo "▶  Step 4: Pruning unused images, volumes, and networks..."
    docker image prune -f
    docker volume prune -f
    docker network prune -f
    echo "   ✅  Unused resources pruned."
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅  Cleanup complete!"
echo ""
echo "  Current Docker state:"
echo "  Containers: $(docker ps -a --format '{{.Names}}' | wc -l | tr -d ' ') total"
echo "  Images:     $(docker images -q | wc -l | tr -d ' ') total"
echo ""
echo "  To rebuild and restart:"
echo "    docker compose up -d --build"
echo "═══════════════════════════════════════════════════"
