# Print Railway/Render env vars from local .env + service account JSON.
# Never writes secrets into the repo.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root ".env.example"))) {
  $Root = Get-Location
}
Set-Location -LiteralPath $Root

$PublicUrl = $args[0]
if (-not $PublicUrl) {
  $PublicUrl = Read-Host "Public HTTPS URL (e.g. https://xxx.up.railway.app) or leave blank"
}

# Prefer wizard API if running
try {
  $q = if ($PublicUrl) { "?public_url=$([uri]::EscapeDataString($PublicUrl))" } else { "" }
  $r = Invoke-RestMethod -Uri "http://127.0.0.1:8020/setup/api/deploy-env$q" -TimeoutSec 5
  Write-Host $r.env_file_text
  Write-Host "# ---"
  Write-Host "# $($r.message)"
  exit 0
} catch {
  Write-Host "# API not reachable; building from local files..."
}

function Get-EnvMap {
  $map = @{}
  $envPath = Join-Path $Root ".env"
  if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
      if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
      $k, $v = $_.Split('=', 2)
      $map[$k.Trim()] = $v.Trim()
    }
  }
  return $map
}

$m = Get-EnvMap
$saPath = Join-Path $Root ($(if ($m.ContainsKey("GOOGLE_APPLICATION_CREDENTIALS") -and $m["GOOGLE_APPLICATION_CREDENTIALS"]) { $m["GOOGLE_APPLICATION_CREDENTIALS"] } else { "secrets/service-account.json" }))
$saJson = ""
if (Test-Path $saPath) {
  $saJson = (Get-Content -Raw $saPath) -replace "[\r\n]", ""
}

$cors = if ($PublicUrl) { $PublicUrl.TrimEnd('/') } else { "https://YOUR-APP.up.railway.app" }
$secret = $m["SECRET_KEY"]
if (-not $secret -or $secret -match "change-me|dev-change") {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secret = [Convert]::ToBase64String($bytes)
}

Write-Output "APP_ENV=production"
Write-Output "DEBUG=false"
Write-Output "AUTH_MODE=dev"
Write-Output "REQUIRE_SHEETS=true"
Write-Output "SPREADSHEET_ID=$($m['SPREADSHEET_ID'])"
Write-Output "SECRET_KEY=$secret"
Write-Output "CORS_ORIGINS=$cors"
Write-Output "SESSION_COOKIE_NAME=gf_session"
if ($saJson) {
  Write-Output "GOOGLE_SERVICE_ACCOUNT_JSON=$saJson"
} else {
  Write-Output "# MISSING secrets/service-account.json — complete /setup first"
}

