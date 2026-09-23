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

# ABSOLUTE host path of ./storage: agent containers are siblings of the api and
# mount the repo through this path. If it is wrong, dispatch silently mounts the
# wrong folder, so it is always realigned with the current clone.
storage="$ROOT/storage"
mkdir -p "$storage"
host_root="$(env_get PAINKILLER_HOST_ROOT)"
host_root="${host_root%/}"
if [ "$host_root" != "$storage" ]; then
  env_set PAINKILLER_HOST_ROOT "$storage"
  if [ -n "$host_root" ]; then ok "PAINKILLER_HOST_ROOT fixed: '$host_root' -> '$storage'"
  else ok "PAINKILLER_HOST_ROOT = $storage"; fi
else
  ok "PAINKILLER_HOST_ROOT = $storage"
fi

if [ -z "$(env_get PAINKILLER_GITEA_PASSWORD)" ]; then
  env_set PAINKILLER_GITEA_PASSWORD "$(new_secret 24)"; ok "PAINKILLER_GITEA_PASSWORD generated"
else
  ok "PAINKILLER_GITEA_PASSWORD set"
fi

if [ -z "$(env_get PAINKILLER_AUTH_SECRET)" ]; then
  env_set PAINKILLER_AUTH_SECRET "$(new_secret 48)"; ok "PAINKILLER_AUTH_SECRET generated (sessions survive restarts)"
else
  ok "PAINKILLER_AUTH_SECRET set"
fi

# Without Google configured, the break-glass admin is the only way in.
generated_admin_password=""
[ -n "$(env_get PAINKILLER_ADMIN_USER)" ] || env_set PAINKILLER_ADMIN_USER admin
if [ -z "$(env_get PAINKILLER_ADMIN_PASSWORD)" ] && [ -z "$(env_get PAINKILLER_GOOGLE_CLIENT_ID)" ]; then
  generated_admin_password="$(new_secret 12)"
  env_set PAINKILLER_ADMIN_PASSWORD "$generated_admin_password"
  ok "PAINKILLER_ADMIN_PASSWORD generated (without Google sign-in it is the only access)"
fi

# LLM keys: dsh and maki use the DeepSeek one; agy uses the Gemini one.
gemini="$(env_get GEMINI_API_KEY)"
[ -n "$gemini" ] || gemini="$(env_get GOOGLE_API_KEY)"
deepseek="$(env_get DEEPSEEK_API_KEY)"
if [ -z "$gemini" ] && [ -z "$deepseek" ] && [ "$INTERACTIVE" = 1 ]; then
  warn "no LLM key in .env. Without one, the initial analysis and task dispatch fail."
  printf '    DEEPSEEK_API_KEY (dsh and maki harnesses; Enter to skip): '
  read -r k || k=""
  if [ -n "$k" ]; then env_set DEEPSEEK_API_KEY "$k"; deepseek="$k"; fi
  printf '    GEMINI_API_KEY (agy harness; Enter to skip): '
  read -r k || k=""
  if [ -n "$k" ]; then env_set GEMINI_API_KEY "$k"; gemini="$k"; fi
fi
if [ -n "$deepseek" ]; then ok "DEEPSEEK_API_KEY set (dsh and maki harnesses)"
else warn "DEEPSEEK_API_KEY empty: projects on the dsh or maki harness only work with their own project key."; fi
if [ -n "$gemini" ]; then ok "GEMINI_API_KEY set (agy harness)"
else warn "GEMINI_API_KEY empty: projects on the agy harness only work with their own project key."; fi

if [ -z "$(env_get COOLIFY_API_TOKEN)" ]; then
  coolify_port="$(env_get COOLIFY_PORT)"
  warn "COOLIFY_API_TOKEN empty: the 'Testar' button stays unavailable until you create a token at http://localhost:${coolify_port:-8008} (Keys & Tokens) and run this script again."
fi

# Compose interpolation prefers the shell variable over .env. A leftover in the
# environment would override what was set above.
for k in PAINKILLER_HOST_ROOT PAINKILLER_GITEA_PASSWORD PAINKILLER_GITEA_EXTERNAL_URL PAINKILLER_AGENT_NETWORK; do
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
admin_user="$(env_get PAINKILLER_ADMIN_USER)"
if [ -n "$generated_admin_password" ]; then
  echo "  Login: $admin_user / $generated_admin_password   (saved in .env)"
elif [ -n "$(env_get PAINKILLER_ADMIN_PASSWORD)" ]; then
  echo "  Login: $admin_user / (password in PAINKILLER_ADMIN_PASSWORD in .env)"
fi
[ -z "$(env_get PAINKILLER_GOOGLE_CLIENT_ID)" ] || echo "  Google sign-in enabled."
echo "  Logs:  docker compose logs -f api"
echo "  Stop:  docker compose down"
