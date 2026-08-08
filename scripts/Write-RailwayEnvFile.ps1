# Builds railway-env.txt in the project root for paste into Railway "Raw Editor".
# Contains secrets — file is gitignored. Do not share or commit it.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $Root

function Read-DotEnv {
  $map = @{}
  $p = Join-Path $Root ".env"
  if (-not (Test-Path $p)) { return $map }
  Get-Content $p | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
    $i = $line.IndexOf("=")
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim()
    $map[$k] = $v
  }
  return $map
}

$envMap = Read-DotEnv
$sid = $envMap["SPREADSHEET_ID"]
if (-not $sid) { throw "SPREADSHEET_ID missing from .env — finish /setup first." }

$credRel = $envMap["GOOGLE_APPLICATION_CREDENTIALS"]
if (-not $credRel) { $credRel = "secrets/service-account.json" }
$saPath = Join-Path $Root $credRel
if (-not (Test-Path -LiteralPath $saPath)) {
  throw "Service account file not found: $saPath"
}
# One line JSON for Railway
$saJson = (Get-Content -LiteralPath $saPath -Raw -Encoding UTF8).Trim()
$saJson = $saJson -replace "(\r?\n)+\s*", ""

$secret = $envMap["SECRET_KEY"]
if (-not $secret -or $secret -match "change-me|dev-change") {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secret = [Convert]::ToBase64String($bytes) -replace "[+/=]", "x"
}

$publicUrl = $args[0]
if (-not $publicUrl) {
  $publicUrl = "https://REPLACE_WITH_YOUR_RAILWAY_DOMAIN.up.railway.app"
}

$cors = $publicUrl.Trim().TrimEnd("/")

$out = @"
APP_ENV=production
DEBUG=false
AUTH_MODE=dev
REQUIRE_SHEETS=true
SPREADSHEET_ID=$sid
SECRET_KEY=$secret
SESSION_COOKIE_NAME=gf_session
CORS_ORIGINS=$cors
GOOGLE_SERVICE_ACCOUNT_JSON=$saJson
"@

$outPath = Join-Path $Root "railway-env.txt"
[System.IO.File]::WriteAllText($outPath, $out.Trim() + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host ""
Write-Host "Wrote: $outPath"
Write-Host ""
Write-Host "NEXT (in Railway):"
Write-Host "  1. Open your service -> Variables"
Write-Host "  2. Click Raw Editor (or bulk edit) if available"
Write-Host "  3. Paste the FULL contents of railway-env.txt"
Write-Host "  4. Save"
Write-Host "  5. Settings -> Networking -> Generate domain"
Write-Host "  6. Edit CORS_ORIGINS to that exact https://....up.railway.app URL"
Write-Host "  7. Redeploy"
Write-Host ""
Write-Host "Opening railway-env.txt and Railway dashboard..."
Start-Process notepad.exe $outPath
Start-Process "https://railway.app/dashboard"
