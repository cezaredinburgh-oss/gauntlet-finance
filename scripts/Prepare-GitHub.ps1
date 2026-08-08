# Prepare a safe first commit for GitHub (never stages secrets).
$ErrorActionPreference = "Stop"
# Script lives in <project>/scripts/ → project root is parent of scripts
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
if (-not (Test-Path (Join-Path $Root "backend"))) {
  $Root = (Get-Location).Path
}
Set-Location -LiteralPath $Root
Write-Host "Project: $Root"

function Assert-NoSecretsStaged {
  $bad = @()
  git diff --cached --name-only 2>$null | ForEach-Object {
    $path = $_ -replace '\\', '/'
    # Allow empty placeholder only (keeps secrets/ folder in git)
    if ($path -match '(^|/)secrets/\.gitkeep$') { return }
    if ($path -match '(^|/)\.env\.example$') { return }
    if ($path -match '(^|/)\.env(\.|$)') { $bad += $_; return }  # .env, .env.local, …
    if ($path -match '(^|/)secrets/') { $bad += $_; return }
    if ($path -match 'service-account|credentials\.json|\.pem$') { $bad += $_; return }
  }
  if ($bad.Count -gt 0) {
    throw "Refusing to commit secret-like paths: $($bad -join ', ')"
  }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "Git is not installed. Install from https://git-scm.com/downloads"
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
  Write-Host "Initializing git repository..."
  git init
  git branch -M main
}

# Ensure secrets ignored
$gi = Join-Path $Root ".gitignore"
if (-not (Test-Path $gi)) { throw ".gitignore missing" }

Write-Host "Staging project files (respecting .gitignore)..."
git add -A
Assert-NoSecretsStaged

$status = git status --porcelain
if (-not $status) {
  Write-Host "Nothing new to commit. Already clean."
} else {
  git commit -m "Gauntlet Finance: app, Sheets wizard, deploy packaging"
  Write-Host "Created commit."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Create empty repo: https://github.com/new  (name: gauntlet-finance)"
Write-Host "  2. git remote add origin https://github.com/YOUR_USER/gauntlet-finance.git"
Write-Host "  3. git push -u origin main"
Write-Host ""
Write-Host "Or with GitHub CLI:"
Write-Host "  gh repo create gauntlet-finance --private --source=. --remote=origin --push"
Write-Host ""
Write-Host "Then open http://127.0.0.1:8020/setup and continue to Deploy."
