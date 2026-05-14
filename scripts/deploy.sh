#!/usr/bin/env bash
# Saathi — Lightsail deploy convenience script.
# Run this on the Lightsail box after `git pull`.
# Idempotent: safe to re-run after every push.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/saathi}"
SERVICE="${SERVICE:-saathi}"

cd "$REPO_DIR"

echo "[saathi] git pull"
git pull --ff-only

echo "[saathi] uv sync"
uv sync --frozen 2>/dev/null || uv sync

echo "[saathi] restart $SERVICE"
sudo systemctl restart "$SERVICE"
sudo systemctl --no-pager status "$SERVICE" | head -n 12

echo "[saathi] healthz"
sleep 2
curl -fsS http://127.0.0.1:8000/healthz && echo
