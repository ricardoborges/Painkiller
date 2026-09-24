# =============================================================================
# Painkiller - brings the whole platform up on Windows (Docker Desktop).
#
#   powershell -ExecutionPolicy Bypass -File .\win-run.ps1
#   powershell -ExecutionPolicy Bypass -File .\win-run.ps1 -SkipBuild
#
# Checks, in order: Docker is up, Compose >= 2.24, "coolify" network, build of
# EVERY image (api + worker and agent of each harness), verifies they exist,
# starts and waits for the api. No .env is needed: everything is configured in
# the browser (first access + setup wizard) and kept in the database.
# Any failure stops the script with its cause, instead of letting it surface
# later in the UI ("A imagem do agente ... nao foi encontrada").
#
# Kept ASCII-only: Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI.
# =============================================================================
[CmdletBinding()]
param(
    # Skip the build (the images must already exist; the script checks).
    [switch]$SkipBuild,
    # Accepted for compatibility; the script no longer prompts for anything.
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

$ApiUrl = 'http://localhost:8000'
$MinCompose = [version]'2.24.0'

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    ok  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Docker
# ---------------------------------------------------------------------------
Write-Step 'Docker'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail '"docker" command not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop/'
}
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail 'Docker is not responding. Open Docker Desktop, wait for "Engine running" and run this script again.'
}
$osType = (docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
if ($osType -ne 'linux') {
    Fail "Docker Desktop is in '$osType' containers mode. Right-click its tray icon and choose 'Switch to Linux containers'."
}
Write-Ok 'daemon responding (Linux containers)'

$composeVersion = (docker compose version --short 2>$null | Out-String).Trim().TrimStart('v')
if ($LASTEXITCODE -ne 0 -or -not $composeVersion) {
    Fail 'the "docker compose" (v2) plugin is not available. Update Docker Desktop.'
}
try { $cv = [version]($composeVersion -replace '[^0-9.].*$', '') } catch { $cv = [version]'0.0' }
if ($cv -lt $MinCompose) {
    Fail "Docker Compose $composeVersion is too old; docker-compose.yml needs $MinCompose or newer. Update Docker Desktop."
}
Write-Ok "compose $composeVersion"

# ---------------------------------------------------------------------------
# 2. Storage folder (bind-mounted into the api; its host path is detected)
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'storage') | Out-Null

# ---------------------------------------------------------------------------
# 3. External Coolify network
# ---------------------------------------------------------------------------
Write-Step 'Network "coolify"'
docker network inspect coolify 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker network create coolify | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail 'could not create the "coolify" docker network.' }
    Write-Ok 'created'
} else { Write-Ok 'already exists' }

# ---------------------------------------------------------------------------
# 4. Images
# ---------------------------------------------------------------------------
# Every locally built image (api, coolify-host and each harness's worker/agent),
# read from compose itself so this list never drifts.
$images = @(docker compose --profile build config --images 2>$null | Where-Object { $_ -like 'painkiller-*' } | Sort-Object -Unique)
if ($LASTEXITCODE -ne 0 -or $images.Count -eq 0) {
    docker compose --profile build config --quiet
    Fail 'docker-compose.yml failed validation (see the message above).'
}

if (-not $SkipBuild) {
    Write-Step "Building images ($($images.Count)); the first run takes several minutes"
    docker compose --profile build build
    if ($LASTEXITCODE -ne 0) {
        Fail 'the build failed (see the log above). Nothing was started. Fix it and run again; what was already built stays cached.'
    }
}

Write-Step 'Checking images'
$missing = @()
foreach ($img in $images) {
    docker image inspect $img 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok $img } else { $missing += $img; Write-Warn "missing: $img" }
}
if ($missing.Count -gt 0) {
    Fail "missing images: $($missing -join ', '). Run the script without -SkipBuild."
}

# ---------------------------------------------------------------------------
# 5. Start
# ---------------------------------------------------------------------------
Write-Step 'Starting services'
docker compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Fail 'docker compose up failed. If the message mentions a port in use, free 8000, 3300, 8008 or 2222 (or set PAINKILLER_GITEA_PORT / COOLIFY_PORT before running).'
}

Write-Step "Waiting for the api at $ApiUrl"
$deadline = (Get-Date).AddSeconds(180)
$up = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "$ApiUrl/api/auth/config"
        if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $up) {
    docker compose logs --tail 60 api
    Fail "the api did not respond within 3 minutes (log above). Follow it with: docker compose logs -f api"
}
Write-Ok 'api responding'

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Painkiller is up: $ApiUrl" -ForegroundColor Green
Write-Host '  Open it now: a fresh install asks you to create the administrator (first access),'
Write-Host '  then opens the setup wizard (Google sign-in, Coolify). Whoever gets there first owns it.'
Write-Host '  Forgot the admin password: docker compose exec api painkiller admin-reset; docker compose restart api'
Write-Host '  Logs:  docker compose logs -f api'
Write-Host '  Stop:  docker compose down'
