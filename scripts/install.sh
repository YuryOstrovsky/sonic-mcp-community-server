#!/usr/bin/env bash
#
# One-shot installer for the SONiC MCP Community Server.
#
# Usage (on a fresh Linux host with Docker + docker-compose plugin):
#
#     curl -fsSL https://raw.githubusercontent.com/YuryOstrovsky/sonic-mcp-community-server/main/scripts/install.sh | bash
#
# What it does:
#   1. Clones this repo (or pulls latest if already cloned).
#   2. Creates .env from .env.example if it doesn't exist.
#   3. Makes sure ./config, ./logs, ./snapshots directories exist.
#   4. Builds the image and starts the container via docker compose.
#
# It does NOT:
#   - install docker (checked for; installer asks you to handle it)
#   - populate SONiC credentials — you must edit .env first
#
# Interrupt after step 2 and edit .env if it's your first run.

set -euo pipefail

REPO_URL="${SONIC_MCP_SERVER_REPO:-https://github.com/YuryOstrovsky/sonic-mcp-community-server.git}"
TARGET_DIR="${SONIC_MCP_SERVER_DIR:-$HOME/sonic-mcp-community-server}"

blue()  { printf "\033[1;34m%s\033[0m\n" "$1"; }
green() { printf "\033[1;32m%s\033[0m\n" "$1"; }
red()   { printf "\033[1;31m%s\033[0m\n" "$1" >&2; }

need() { command -v "$1" >/dev/null 2>&1 || { red "missing required command: $1"; exit 1; }; }
need git
need docker
if ! docker compose version >/dev/null 2>&1; then
  red "docker compose plugin not installed — see https://docs.docker.com/compose/install/"
  exit 1
fi

blue "→ clone / update repo at $TARGET_DIR"
if [ -d "$TARGET_DIR/.git" ]; then
  git -C "$TARGET_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$TARGET_DIR"
fi
cd "$TARGET_DIR"

if [ ! -f .env ]; then
  blue "→ creating .env from .env.example"
  cp .env.example .env
  green "edit $TARGET_DIR/.env and set SONIC_DEFAULT_USERNAME / _PASSWORD"
  green "then re-run: cd $TARGET_DIR && docker compose up -d --build"
  exit 0
fi

blue "→ ensuring runtime directories exist"
mkdir -p config logs snapshots

blue "→ docker compose up -d --build"
docker compose up -d --build

blue "→ waiting for /health"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    green "server healthy after ${i}s — $(curl -sf http://127.0.0.1:8000/tools | python3 -c 'import json,sys;print(f"{len(json.load(sys.stdin))} tools loaded")' 2>/dev/null || echo "tools unknown")"
    green "http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):8000"
    exit 0
  fi
  sleep 1
done
red "server did not become healthy within 30s — check: docker compose logs mcp"
exit 1
