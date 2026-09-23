#!/usr/bin/env bash
# =============================================================================
# Painkiller - brings the whole platform up on macOS (Docker Desktop, OrbStack
# or Colima). The checks and startup are the same as on Linux, in linux-run.sh;
# only the Mac-specific part lives here: waking Docker Desktop if it is closed.
#
#   ./mac-run.sh                  # check, build everything and start
#   ./mac-run.sh --skip-build     # start only (the images must already exist)
# =============================================================================
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"

if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1 \
   && [ -d /Applications/Docker.app ]; then
  echo "==> Docker Desktop is closed; opening it and waiting for the engine (up to 2 min)..."
  open -a Docker
  i=0
  while [ "$i" -lt 60 ] && ! docker info >/dev/null 2>&1; do
    i=$((i + 1))
    sleep 2
  done
fi

PAINKILLER_PLATFORM=mac exec bash "$ROOT/linux-run.sh" "$@"
