# Stop Gauntlet Finance (ports 8020/5190 + project uvicorn/vite). ASCII-only.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiPort = 8020
$UiPort = 5190
$LogFile = Join-Path $Root "launcher.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        [System.IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine)
    } catch {}
}

$ids = New-Object "System.Collections.Generic.HashSet[int]"

foreach ($port in @($ApiPort, $UiPort)) {
    try {
        Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object {
                if ($_ -gt 0) { [void]$ids.Add([int]$_) }
            }
    } catch {}
    netstat -ano 2>$null | ForEach-Object {
        if ($_ -match (":$port\s+\S+\s+\S+\s+LISTENING\s+(\d+)")) {
            [void]$ids.Add([int]$Matches[1])
        }
    }
}

foreach ($pidFile in @("api.pid", "ui.pid")) {
    $p = Join-Path $Root $pidFile
    if (Test-Path -LiteralPath $p) {
        $raw = (Get-Content -LiteralPath $p -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($raw -match "^\d+$") { [void]$ids.Add([int]$raw) }
    }
}

try {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
        $cl = $_.CommandLine
        if (-not $cl) { return }
        if ($cl -notlike ("*{0}*" -f $Root)) { return }
        if ($cl -match "uvicorn|vite|backend\.api\.main|node_modules\\vite|node_modules/vite|Start-App\.ps1") {
            [void]$ids.Add([int]$_.ProcessId)
        }
    }
} catch {}

Write-Log ("Stop-App: killing {0} process tree(s)" -f $ids.Count)
foreach ($procId in $ids) {
    if ($procId -le 0) { continue }
    Write-Log ("  taskkill /F /T /PID {0}" -f $procId)
    cmd.exe /c ("taskkill /F /T /PID {0}" -f $procId) 2>$null | Out-Null
}

foreach ($pidFile in @("api.pid", "ui.pid")) {
    Remove-Item -LiteralPath (Join-Path $Root $pidFile) -Force -ErrorAction SilentlyContinue
}

exit 0
