#!/usr/bin/env bash
# =============================================================================
# Painkiller - brings the whole platform up on Linux (and macOS, via mac-run.sh).
#
#   ./linux-run.sh                  # check, build everything and start
#   ./linux-run.sh --skip-build     # start only (the images must already exist)
#   ./linux-run.sh --non-interactive
#
# Checks, in order: Docker is up, Compose >= 2.24, .env is complete (generates
# what can be generated), "coolify" network, build of EVERY image (api + worker
# and agent of each harness), verifies they exist, starts and waits for the api.
# Any failure stops the script with its cause, instead of letting it surface
# later in the UI ("A imagem do agente ... nao foi encontrada").
#
# Compatible with macOS's bash 3.2 and BSD sed/awk: no associative arrays,
# no ${v,,}, no sed -i.
# =============================================================================
set -u

SKIP_BUILD=0
INTERACTIVE=1
[ -t 0 ] || INTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --non-interactive) INTERACTIVE=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

ENV_FILE="$ROOT/.env"
ENV_EXAMPLE="$ROOT/.env.example"
API_URL="http://localhost:8000"
MIN_COMPOSE="2.24.0"
PLATFORM="${PAINKILLER_PLATFORM:-linux}"   # mac-run.sh sets "mac"

if [ -t 1 ]; then
  C_STEP=$'\033[36m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_STEP=; C_OK=; C_WARN=; C_ERR=; C_OFF=
fi
step() { printf '\n%s==> %s%s\n' "$C_STEP" "$1" "$C_OFF"; }
ok()   { printf '    %sok%s  %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '    %s!!%s  %s\n' "$C_WARN" "$C_OFF" "$1"; }
fail() { printf '\n%sERROR:%s %s\n' "$C_ERR" "$C_OFF" "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# .env: read and write while keeping comments and order
# ---------------------------------------------------------------------------
env_get() {
  [ -f "$ENV_FILE" ] || return 0
  awk -v k="$1" '
    { line=$0; sub(/^[ \t]+/, "", line) }
    index(line, k"=") == 1 || line ~ ("^" k "[ \t]*=") {
      v=line; sub(/^[^=]*=/, "", v); gsub(/^[ \t]+|[ \t\r]+$/, "", v)
      if (v ~ /^".*"$/ || v ~ /^\x27.*\x27$/) v=substr(v, 2, length(v)-2)
      print v; exit
    }' "$ENV_FILE"
}

env_set() {
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")" || fail "could not write .env"
  awk -v k="$1" -v v="$2" '
    BEGIN { done=0 }
    { line=$0; sub(/^[ \t]+/, "", line) }
    !done && (index(line, k"=") == 1 || line ~ ("^" k "[ \t]*=")) { print k "=" v; done=1; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
}

new_secret() {
  # Only characters that are safe in .env and URLs.
  head -c "$1" /dev/urandom | base64 | tr -d '/+=\n'
}

version_ge() {
  # version_ge A B -> true when A >= B (digits and dots only).
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]
}

docker_hint() {
  if [ "$PLATFORM" = mac ]; then
    echo 'Open Docker Desktop (open -a Docker), wait for "Engine running" and run again.'
  else
    echo 'Start the service (sudo systemctl start docker). If the error is "permission denied", add your user to the docker group: sudo usermod -aG docker "$USER" and open a new session.'
  fi
}

# ---------------------------------------------------------------------------
# 1. Docker
# ---------------------------------------------------------------------------
step "Docker"
command -v docker >/dev/null 2>&1 || fail '"docker" command not found. Install it: https://docs.docker.com/engine/install/'
if ! err="$(docker info 2>&1 >/dev/null)"; then
  case "$err" in
    *"permission denied"*) fail "no permission to talk to Docker. $(docker_hint)" ;;
    *) fail "Docker is not responding. $(docker_hint)" ;;
  esac
fi
ok "daemon responding"

compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//; s/[^0-9.].*$//')"
[ -n "$compose_version" ] || fail 'the "docker compose" (v2) plugin is not available. Install docker-compose-plugin (or update Docker Desktop).'
version_ge "$compose_version" "$MIN_COMPOSE" \
  || fail "Docker Compose $compose_version is too old; docker-compose.yml needs $MIN_COMPOSE or newer."
ok "compose $compose_version"

command -v curl >/dev/null 2>&1 || fail '"curl" command not found; install it so the script can wait for the api.'

# ---------------------------------------------------------------------------
# 2. .env
# ---------------------------------------------------------------------------
step "Configuration (.env)"
if [ ! -f "$ENV_FILE" ]; then
  [ -f "$ENV_EXAMPLE" ] || fail ".env.example not found; the clone looks incomplete."
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok ".env created from .env.example"
fi

# ./storage is bind-mounted into the api; the api detects its host path by
# inspecting its own container (shown and testable in the setup wizard).
mkdir -p "$ROOT/storage"

if [ -z "$(env_get PAINKILLER_GITEA_PASSWORD)" ]; then
  env_set PAINKILLER_GITEA_PASSWORD "$(new_secret 24)"; ok "PAINKILLER_GITEA_PASSWORD generated"
else
  ok "PAINKILLER_GITEA_PASSWORD set"
fi

# The administrator, the session-signing key, Google sign-in and Coolify all
# live in the database: the first access creates the admin in the browser and
# the setup wizard does the rest. LLM keys are per project.

# Compose interpolation prefers the shell variable over .env. A leftover in the
# environment would override what was set above.
for k in PAINKILLER_GITEA_PASSWORD PAINKILLER_GITEA_EXTERNAL_URL PAINKILLER_AGENT_NETWORK; do
  if [ -n "$(eval "printf '%s' \"\${$k:-}\"")" ]; then
    warn "ignoring $k set in the shell; the .env value wins"
    unset "$k"
  fi
done

# ---------------------------------------------------------------------------
# 3. External Coolify network
# ---------------------------------------------------------------------------
step 'Network "coolify"'
if docker network inspect coolify >/dev/null 2>&1; then
  ok "already exists"
else
  docker network create coolify >/dev/null || fail 'could not create the "coolify" docker network.'
  ok "created"
fi

# ---------------------------------------------------------------------------
# 4. Images
# ---------------------------------------------------------------------------
# Every locally built image (api, coolify-host and each harness's worker/agent),
# read from compose itself so this list never drifts.
if ! images="$(docker compose --profile build config --images 2>/dev/null)"; then
  docker compose --profile build config --quiet
  fail "docker-compose.yml failed validation (see the message above; usually a variable missing from .env)."
fi
images="$(printf '%s\n' "$images" | grep '^painkiller-' | sort -u)"
[ -n "$images" ] || fail "compose listed no painkiller-* image."
count="$(printf '%s\n' "$images" | wc -l | tr -d ' ')"

if [ "$SKIP_BUILD" = 0 ]; then
  step "Building images ($count); the first run takes several minutes"
  docker compose --profile build build \
    || fail "the build failed (see the log above). Nothing was started. Fix it and run again; what was already built stays cached."
fi

step "Checking images"
missing=""
for img in $images; do
  if docker image inspect "$img" >/dev/null 2>&1; then ok "$img"
  else warn "missing: $img"; missing="$missing $img"; fi
done
[ -z "$missing" ] || fail "missing images:$missing. Run the script without --skip-build."

# ---------------------------------------------------------------------------
# 5. Start
# ---------------------------------------------------------------------------
step "Starting services"
docker compose up -d --remove-orphans \
  || fail "docker compose up failed. If the message mentions a port in use, free 8000, 3300, 8008 or 2222 (or change PAINKILLER_GITEA_PORT / COOLIFY_PORT in .env)."

step "Waiting for the api at $API_URL"
up=0
i=0
while [ "$i" -lt 90 ]; do
  if curl -fsS -o /dev/null --max-time 3 "$API_URL/api/auth/config" 2>/dev/null; then up=1; break; fi
  i=$((i + 1))
  sleep 2
done
if [ "$up" != 1 ]; then
  docker compose logs --tail 60 api
  fail "the api did not respond within 3 minutes (log above). Follow it with: docker compose logs -f api"
fi
ok "api responding"

# ---------------------------------------------------------------------------
printf '\n%sPainkiller is up: %s%s\n' "$C_OK" "$API_URL" "$C_OFF"
echo "  Open it now: a fresh install asks you to create the administrator (first access),"
echo "  then opens the setup wizard (Google sign-in, Coolify). Whoever gets there first owns it."
echo "  Forgot the admin password: docker compose exec api painkiller admin-reset && docker compose restart api"
echo "  Logs:  docker compose logs -f api"
echo "  Stop:  docker compose down"
