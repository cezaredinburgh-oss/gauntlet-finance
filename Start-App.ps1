# Start API + UI with no visible console windows.
# Logs: launcher.log, api.out.log, api.err.log, ui.out.log, ui.err.log
# ASCII-only (Windows PowerShell 5.1 safe).
$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$ApiPort = 8020
$UiPort = 5190
$LogFile = Join-Path $Root "launcher.log"
$ApiOut = Join-Path $Root "api.out.log"
$ApiErr = Join-Path $Root "api.err.log"
$UiOut = Join-Path $Root "ui.out.log"
$UiErr = Join-Path $Root "ui.err.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        [System.IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine)
    } catch {}
}

function Show-ErrorPopup([string]$Message) {
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            "Gauntlet Finance - startup failed",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch {}
}

function Start-HiddenLogged {
    <#
      Launch executable with CreateNoWindow and stdout/stderr to files.
      Uses .NET ProcessStartInfo so paths with spaces work (no cmd /c quoting).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$StdOutPath,
        [Parameter(Mandatory = $true)][string]$StdErrPath,
        [hashtable]$Environment = @{}
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $false

    foreach ($key in $Environment.Keys) {
        $psi.EnvironmentVariables[$key] = [string]$Environment[$key]
    }

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()

    # Drain pipes to files on background runspace so child never blocks
    $outPath = $StdOutPath
    $errPath = $StdErrPath
    $stdout = $proc.StandardOutput
    $stderr = $proc.StandardError

    $drainScript = {
        param($Reader, $Path)
        try {
            $sw = New-Object System.IO.StreamWriter($Path, $false, [System.Text.UTF8Encoding]::new($false))
            $sw.AutoFlush = $true
            while ($null -ne ($line = $Reader.ReadLine())) {
                $sw.WriteLine($line)
            }
            $sw.Close()
        } catch {}
    }

    $outJob = [System.Management.Automation.PowerShell]::Create().AddScript($drainScript).AddArgument($stdout).AddArgument($outPath)
    $errJob = [System.Management.Automation.PowerShell]::Create().AddScript($drainScript).AddArgument($stderr).AddArgument($errPath)
    $outHandle = $outJob.BeginInvoke()
    $errHandle = $errJob.BeginInvoke()

    $proc | Add-Member -NotePropertyName _outJob -NotePropertyValue $outJob -Force
    $proc | Add-Member -NotePropertyName _errJob -NotePropertyValue $errJob -Force
    $proc | Add-Member -NotePropertyName _outHandle -NotePropertyValue $outHandle -Force
    $proc | Add-Member -NotePropertyName _errHandle -NotePropertyValue $errHandle -Force

    return $proc
}

function Stop-AppServers {
    Write-Log "Stopping leftover servers..."
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

    try {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
            $cl = $_.CommandLine
            if (-not $cl) { return }
            if ($cl -notlike ("*{0}*" -f $Root)) { return }
            if ($cl -match "uvicorn|vite|backend\.api\.main|node_modules\\vite|node_modules/vite") {
                [void]$ids.Add([int]$_.ProcessId)
            }
        }
    } catch {}

    foreach ($pidFile in @("api.pid", "ui.pid")) {
        $p = Join-Path $Root $pidFile
        if (Test-Path -LiteralPath $p) {
            $raw = (Get-Content -LiteralPath $p -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($raw -match "^\d+$") { [void]$ids.Add([int]$raw) }
        }
    }

    foreach ($procId in $ids) {
        if ($procId -le 0) { continue }
        # Do not kill ourselves
        if ($procId -eq $PID) { continue }
        Write-Log ("  taskkill /F /T /PID {0}" -f $procId)
        cmd.exe /c ("taskkill /F /T /PID {0}" -f $procId) 2>$null | Out-Null
    }
    Start-Sleep -Seconds 1
}

function Test-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Quote-Arg([string]$s) {
    if ($null -eq $s) { return '""' }
    if ($s -match '\s' -or $s -match '"') {
        return '"' + ($s -replace '"', '\"') + '"'
    }
    return $s
}

try {
    try { [System.IO.File]::WriteAllText($LogFile, "") } catch {}

    Write-Log "Starting Gauntlet Finance (no-console mode)"
    Write-Log ("Project: {0}" -f $Root)
    Write-Log ("Launcher PID: {0}" -f $PID)

    $pyCmd = $null
    foreach ($candidate in @(
            (Join-Path $Root ".venv\Scripts\python.exe"),
            (Join-Path $Root "venv\Scripts\python.exe")
        )) {
        if (Test-Path -LiteralPath $candidate) {
            $pyCmd = $candidate
            break
        }
    }
    if (-not $pyCmd) {
        $c = Get-Command python -ErrorAction SilentlyContinue
        if ($c) { $pyCmd = $c.Source }
    }
    if (-not $pyCmd) {
        throw "Python not found. Install Python 3.12+ and add it to PATH."
    }
    Write-Log ("Python: {0}" -f $pyCmd)

    $nodeCmd = $null
    $n = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($n) { $nodeCmd = $n.Source }
    if (-not $nodeCmd) {
        $n = Get-Command node -ErrorAction SilentlyContinue
        if ($n) { $nodeCmd = $n.Source }
    }
    if (-not $nodeCmd) {
        throw "node.exe not found. Install Node.js LTS and add it to PATH."
    }
    Write-Log ("Node: {0}" -f $nodeCmd)

    $frontendDir = Join-Path $Root "frontend"
    $viteJs = Join-Path $frontendDir "node_modules\vite\bin\vite.js"

    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
        Write-Log "frontend/node_modules missing - running npm install..."
        $npmCmd = $null
        $nm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($nm) { $npmCmd = $nm.Source }
        if (-not $npmCmd) {
            throw "npm.cmd not found (needed once to install frontend deps)."
        }
        $install = Start-Process -FilePath $npmCmd `
            -ArgumentList "install" `
            -WorkingDirectory $frontendDir `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($install.ExitCode -ne 0) {
            throw ("npm install failed (exit {0})." -f $install.ExitCode)
        }
    }
    if (-not (Test-Path -LiteralPath $viteJs)) {
        throw ("Vite not found at {0}. Run: cd frontend ; npm install" -f $viteJs)
    }

    Stop-AppServers

    foreach ($f in @($ApiOut, $ApiErr, $UiOut, $UiErr)) {
        try { [System.IO.File]::WriteAllText($f, "") } catch {}
    }

    $childEnv = @{
        "PYTHONPATH"       = $Root
        "API_PORT"         = "$ApiPort"
        "PYTHONUNBUFFERED" = "1"
        "VITE_DEV_PORT"    = "$UiPort"
    }

    $apiArgs = "-m uvicorn backend.api.main:app --host 127.0.0.1 --port $ApiPort"
    Write-Log ("Launching API on port {0}..." -f $ApiPort)
    Write-Log ("  cmd: {0} {1}" -f $pyCmd, $apiArgs)
    $api = Start-HiddenLogged `
        -FilePath $pyCmd `
        -Arguments $apiArgs `
        -WorkingDirectory $Root `
        -StdOutPath $ApiOut `
        -StdErrPath $ApiErr `
        -Environment $childEnv
    Write-Log ("  API PID {0}" -f $api.Id)
    [System.IO.File]::WriteAllText((Join-Path $Root "api.pid"), [string]$api.Id)

    # Quote vite path for Argument string (path has spaces)
    $uiArgs = "$(Quote-Arg $viteJs) --port $UiPort --strictPort --host 127.0.0.1"
    Write-Log ("Launching UI on port {0}..." -f $UiPort)
    Write-Log ("  cmd: {0} {1}" -f $nodeCmd, $uiArgs)
    $ui = Start-HiddenLogged `
        -FilePath $nodeCmd `
        -Arguments $uiArgs `
        -WorkingDirectory $frontendDir `
        -StdOutPath $UiOut `
        -StdErrPath $UiErr `
        -Environment $childEnv
    Write-Log ("  UI PID {0}" -f $ui.Id)
    [System.IO.File]::WriteAllText((Join-Path $Root "ui.pid"), [string]$ui.Id)

    $apiReady = $false
    $uiReady = $false
    for ($i = 1; $i -le 60; $i++) {
        if (-not $apiReady) {
            $apiReady = Test-Url ("http://127.0.0.1:{0}/health" -f $ApiPort)
        }
        if (-not $uiReady) {
            $uiReady = Test-Url ("http://127.0.0.1:{0}/" -f $UiPort)
        }
        if ($apiReady -and $uiReady) { break }

        if ($api.HasExited -and -not $apiReady) {
            $err = ""
            Start-Sleep -Milliseconds 300
            if (Test-Path $ApiErr) { $err = [System.IO.File]::ReadAllText($ApiErr) }
            if (Test-Path $ApiOut) { $err += [System.IO.File]::ReadAllText($ApiOut) }
            throw ("API process exited early.`n{0}" -f $err)
        }
        if ($ui.HasExited -and -not $uiReady) {
            $err = ""
            Start-Sleep -Milliseconds 300
            if (Test-Path $UiErr) { $err = [System.IO.File]::ReadAllText($UiErr) }
            if (Test-Path $UiOut) { $err += [System.IO.File]::ReadAllText($UiOut) }
            throw ("UI process exited early.`n{0}" -f $err)
        }

        if ($i -eq 10 -or $i -eq 25 -or $i -eq 40) {
            Write-Log ("Waiting... api={0} ui={1} t={2}" -f $apiReady, $uiReady, $i)
        }
        Start-Sleep -Seconds 1
    }

    if (-not $apiReady) {
        $err = ""
        if (Test-Path $ApiErr) { $err = [System.IO.File]::ReadAllText($ApiErr) }
        throw ("API not ready on port {0}.`n{1}" -f $ApiPort, $err)
    }
    if (-not $uiReady) {
        $err = ""
        if (Test-Path $UiErr) { $err = [System.IO.File]::ReadAllText($UiErr) }
        if (Test-Path $UiOut) { $err += [System.IO.File]::ReadAllText($UiOut) }
        throw ("UI not ready on port {0}.`n{1}" -f $UiPort, $err)
    }

    $openPath = "/"
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $ApiPort) -TimeoutSec 5
        if (-not $health.spreadsheet_configured) {
            Write-Log "Sheets not configured - opening /settings"
            $openPath = "/settings"
        }
    } catch {
        Write-Log ("WARN: health check for open path failed: {0}" -f $_.Exception.Message)
    }

    Write-Log ("API ready http://127.0.0.1:{0}" -f $ApiPort)
    Write-Log ("UI ready  http://127.0.0.1:{0}" -f $UiPort)
    Start-Process ("http://localhost:{0}{1}" -f $UiPort, $openPath)
    Write-Log "Browser opened."

    # Stay alive (hidden) so stdout/stderr drain jobs keep working.
    # Stop-App.bat kills the server PIDs; this process exits when both children exit.
    Write-Log "Hidden launcher staying alive to keep log pipes open. Use Stop-App.bat to stop."
    while (-not ($api.HasExited -and $ui.HasExited)) {
        Start-Sleep -Seconds 3
    }
    Write-Log "Both servers exited. Launcher done."
    exit 0
}
catch {
    $msg = $_.Exception.Message
    Write-Log ("ERROR: {0}" -f $msg)
    Show-ErrorPopup ("Gauntlet Finance failed to start.`n`n{0}`n`nSee launcher.log, api.err.log, ui.err.log in:`n{1}" -f $msg, $Root)
    exit 1
}
