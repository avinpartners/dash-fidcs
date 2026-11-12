# Dash FIDCs: helpers shared by setup.ps1, start.ps1 and stop.ps1.
# Dot-source it: . (Join-Path $PSScriptRoot "common.ps1")
# Windows PowerShell 5.1, no admin rights. Saved as UTF-8 with BOM so the
# accents in messages survive PowerShell 5.1.
#
# Layout (never inside OneDrive, which can corrupt a running database):
#   %LOCALAPPDATA%\DashFIDCs\venv              Python virtual environment
#   %LOCALAPPDATA%\DashFIDCs\pgsql             PostgreSQL 16 binaries (EDB zip)
#   %LOCALAPPDATA%\DashFIDCs\pgdata            database files
#   %LOCALAPPDATA%\DashFIDCs\raw               downloaded source files (cache)
#   %LOCALAPPDATA%\DashFIDCs\logs              app and PostgreSQL logs
#   %LOCALAPPDATA%\DashFIDCs\db_password.txt   database password (this user only)

$ErrorActionPreference = "Stop"

$RepoRoot     = Split-Path -Parent $PSScriptRoot
$BackendDir   = Join-Path $RepoRoot "backend"
$EnvFile      = Join-Path $RepoRoot ".env"
$Requirements = Join-Path $BackendDir "requirements.txt"
$AppHome      = Join-Path $env:LOCALAPPDATA "DashFIDCs"
$VenvDir      = Join-Path $AppHome "venv"
$VenvPython   = Join-Path $VenvDir "Scripts\python.exe"
$PgDir        = Join-Path $AppHome "pgsql"
$PgBin        = Join-Path $PgDir "bin"
$PgCtl        = Join-Path $PgBin "pg_ctl.exe"
$PgData       = Join-Path $AppHome "pgdata"
$RawDir       = Join-Path $AppHome "raw"
$LogDir       = Join-Path $AppHome "logs"
$PasswordFile = Join-Path $AppHome "db_password.txt"
$SetupMarker  = Join-Path $AppHome "setup_done.txt"
$AppPidFile   = Join-Path $AppHome "app.pid"
$PgLog        = Join-Path $LogDir "postgresql.log"
$AppOutLog    = Join-Path $LogDir "app.out.log"
$AppErrLog    = Join-Path $LogDir "app.err.log"
$PgHost       = "127.0.0.1"
$DefaultPgPort  = 5434          # PG_PORT in .env overrides it ($PgPort is set below Get-EnvValue)
$DefaultAppPort = 8081
$ScriptMutexName = "Local\DashFIDCsScripts"
$StatusInvalidImageHash = -1073740760   # 0xC0000428: Windows refused to load a file (code integrity)
$script:AppControlProgram = $null

function Write-Step([string]$Text) { Write-Host "-> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "   $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "   $Text" }
function Write-Warn([string]$Text) { Write-Host "   ATENÇÃO: $Text" -ForegroundColor Yellow }

function Test-AppControlText([string]$Text) {
    if (-not $Text) { return $false }
    return $Text -match "Application Control|Controle de Aplicativo|blocked by (group )?policy|bloquead[oa] pela pol|has blocked this file|bloqueou este arquivo|0xC0000428|0x800711C7|0x800704EC"
}

function Show-AppControlHelp([string]$Program, [string]$Detail) {
    Write-Host ""
    Write-Host "O Windows (App Control) bloqueou um programa necessário:" -ForegroundColor Red
    Write-Host "   $Program" -ForegroundColor Red
    if ($Detail) { Write-Host "   $Detail" }
    Write-Host ""
    Write-Host "Não tente contornar o bloqueio. O que fazer:"
    Write-Host "   1. Tire um print desta janela e envie para quem mantém o Dash FIDCs."
    Write-Host "   2. Peça à TI que libere as pastas abaixo no App Control:"
    Write-Host "      $PgBin"
    Write-Host "      $VenvDir e a pasta do Python 3.12"
}

function Assert-FullLanguage {
    # App Control can force PowerShell into ConstrainedLanguage, where these scripts cannot work.
    $mode = $ExecutionContext.SessionState.LanguageMode
    if ($mode -ne "FullLanguage") {
        $script:AppControlProgram = "PowerShell (modo de linguagem: $mode)"
        throw "O PowerShell está em modo restrito ($mode) por política do Windows."
    }
}

function Invoke-Native {
    # Runs a program, returns its exit code (and output with -Capture or -Tee).
    # Output is shown on the console; with -Capture it is returned instead;
    # with -Tee it is shown and returned, stderr included.
    # Never use this for pg_ctl start (see Start-Postgres).
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$Capture,
        [switch]$Tee
    )
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = @()
    try {
        if ($Capture) {
            $output = @(& $FilePath @Arguments 2>$null)
        } elseif ($Tee) {
            $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { $line = "$_"; Write-Host $line; $line })
        } else {
            & $FilePath @Arguments | Out-Host
        }
        $code = $LASTEXITCODE
    } catch {
        $ErrorActionPreference = $saved
        if (Test-AppControlText $_.Exception.Message) { $script:AppControlProgram = $FilePath }
        throw "Não foi possível executar $FilePath : $($_.Exception.Message)"
    } finally {
        $ErrorActionPreference = $saved
    }
    if ($code -eq $StatusInvalidImageHash) {
        $script:AppControlProgram = $FilePath
        throw "O Windows recusou carregar $FilePath (código 0xC0000428)."
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $output }
}

function Join-ArgString([string[]]$Items) {
    # One command-line string for Start-Process (PowerShell 5.1 does not quote list items).
    $quoted = foreach ($item in $Items) {
        if ($item -eq "" -or $item -match '[\s"]') { '"' + ($item -replace '"', '\"') + '"' } else { $item }
    }
    return ($quoted -join " ")
}

function Initialize-AppHome {
    foreach ($dir in @($AppHome, $RawDir, $LogDir)) {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    }
}

# --- one script at a time ----------------------------------------------------

$script:ScriptMutex = $null
$script:ScriptLockHeld = $false

function Enter-ScriptLock([int]$TimeoutMs = 0) {
    # Named mutex shared by start, stop and setup, so two double-clicks never
    # run setup or start the app twice. It is re-entrant on the same thread:
    # setup.ps1 run from start.ps1 gets it at once. A mutex left by a window
    # that was closed or killed comes back as "abandoned", which is ours too.
    if (-not $script:ScriptMutex) { $script:ScriptMutex = New-Object System.Threading.Mutex($false, $ScriptMutexName) }
    $got = $false
    try { $got = $script:ScriptMutex.WaitOne($TimeoutMs) } catch [System.Threading.AbandonedMutexException] { $got = $true }
    if ($got) { $script:ScriptLockHeld = $true }
    return $got
}

function Assert-ScriptLock([int]$WaitSeconds = 0) {
    if (Enter-ScriptLock 0) { return }
    if ($WaitSeconds -gt 0) {
        Write-Note "Outra janela do Dash FIDCs está iniciando ou parando; aguardando até $WaitSeconds s..."
        if (Enter-ScriptLock ($WaitSeconds * 1000)) { return }
    }
    throw "O Dash FIDCs já está sendo iniciado ou parado em outra janela. Aguarde ela terminar e tente de novo."
}

function Exit-ScriptLock {
    if ($script:ScriptMutex -and $script:ScriptLockHeld) {
        try { $script:ScriptMutex.ReleaseMutex() } catch { }
        $script:ScriptLockHeld = $false
    }
}

# --- .env --------------------------------------------------------------------

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Read-EnvLines {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return @() }
    # ReadAllLines drops a BOM; the app reads .env as UTF-8.
    return @([System.IO.File]::ReadAllLines($EnvFile, [System.Text.Encoding]::UTF8))
}

function Get-EnvValue([string]$Key) {
    foreach ($line in Read-EnvLines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$' -and $Matches[1] -eq $Key) {
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $null
}

function Set-EnvValues {
    # Updates keys in the repo-root .env, keeping every other line (APP_PASSCODE,
    # ANTHROPIC_API_KEY, comments) as it is. Keys in -IfEmpty are only written
    # when missing or empty. Written as UTF-8 without BOM, unquoted values.
    param([System.Collections.Specialized.OrderedDictionary]$Always, [System.Collections.Specialized.OrderedDictionary]$IfEmpty)
    $lines = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($line in Read-EnvLines) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $key = $Matches[1]
            $current = $Matches[2].Trim()
            if ($seen.ContainsKey($key)) { $lines.Add($line); continue }
            $seen[$key] = $true
            if ($Always -and $Always.Contains($key)) { $lines.Add("$key=$($Always[$key])"); continue }
            if ($IfEmpty -and $IfEmpty.Contains($key) -and ($current -eq "" -or $current -eq '""' -or $current -eq "''")) {
                $lines.Add("$key=$($IfEmpty[$key])"); continue
            }
        }
        $lines.Add($line)
    }
    $added = $false
    foreach ($table in @($Always, $IfEmpty)) {
        if (-not $table) { continue }
        foreach ($key in $table.Keys) {
            if (-not $seen.ContainsKey($key)) {
                if (-not $added) {
                    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -ne "") { $lines.Add("") }
                    $lines.Add("# Written by scripts\setup.ps1 (native Windows runtime).")
                    $added = $true
                }
                $lines.Add("$key=$($table[$key])")
                $seen[$key] = $true
            }
        }
    }
    [System.IO.File]::WriteAllText($EnvFile, (($lines -join "`r`n") + "`r`n"), $Utf8NoBom)
}

function Get-AppPort {
    $value = Get-EnvValue "APP_PORT"
    $port = 0
    if ($value -and [int]::TryParse($value, [ref]$port) -and $port -gt 0) { return $port }
    return $DefaultAppPort
}

function Get-AppHost {
    $value = Get-EnvValue "APP_HOST"
    if ($value) { return $value }
    return "127.0.0.1"
}

function Get-PgPort {
    # Database port: 5434 unless PG_PORT is set in .env (another program holds 5434).
    # A change makes start.ps1 re-run setup.ps1, which rewrites postgresql.conf
    # and DATABASE_URL; Start-Postgres restarts a server on the old port.
    $value = Get-EnvValue "PG_PORT"
    $port = 0
    if ($value -and [int]::TryParse($value, [ref]$port) -and $port -gt 0 -and $port -lt 65536) { return $port }
    if ($value) { Write-Warn "PG_PORT=$value no .env não é uma porta válida; usando $DefaultPgPort." }
    return $DefaultPgPort
}

$PgPort = Get-PgPort

function Get-ProbeHost([string]$BindHost) {
    # Address this script uses to reach the app on this laptop.
    if ($BindHost -in @("0.0.0.0", "127.0.0.1", "localhost", "")) { return "127.0.0.1" }
    return $BindHost
}

# --- network -----------------------------------------------------------------

function Test-PortOpen([string]$TargetHost, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($TargetHost, $Port)
        return ($task.Wait(700) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-PortOwner([int]$Port) {
    # "name (PID n)" of the process listening on the port, or $null.
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
        return "$($proc.ProcessName) (PID $($proc.Id))"
    } catch {
        return $null
    }
}

function Get-Health([string]$TargetHost, [int]$Port) {
    # /api/health as an object, or $null. Bypasses any proxy: this is a local call.
    try {
        $req = [System.Net.WebRequest]::Create("http://${TargetHost}:$Port/api/health")
        $req.Proxy = $null
        $req.Timeout = 3000
        $resp = $req.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            return ($reader.ReadToEnd() | ConvertFrom-Json)
        } finally {
            $resp.Close()
        }
    } catch {
        return $null
    }
}

function Get-LanAddresses {
    try {
        return @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.AddressState -eq "Preferred" } |
            ForEach-Object { [pscustomobject]@{ Address = $_.IPAddress; Interface = $_.InterfaceAlias } })
    } catch {
        return @()
    }
}

# --- PostgreSQL --------------------------------------------------------------

function Get-DbPassword {
    if (-not (Test-Path -LiteralPath $PasswordFile)) { throw "Senha do banco não encontrada em $PasswordFile." }
    $text = [System.IO.File]::ReadAllText($PasswordFile).Trim()
    $first = ($text -split "`r?`n")[0].Trim()
    if (-not $first) { throw "O arquivo $PasswordFile está vazio." }
    return $first
}

function Test-PgRunning {
    # pg_ctl status: 0 = running, 3 = not running, 4 = no data directory.
    if (-not (Test-Path -LiteralPath $PgCtl)) { return $false }
    $r = Invoke-Native $PgCtl @("status", "-D", $PgData) -Capture
    return ($r.ExitCode -eq 0)
}

function Test-PgReady {
    $isready = Join-Path $PgBin "pg_isready.exe"
    $r = Invoke-Native $isready @("-h", $PgHost, "-p", "$PgPort", "-q") -Capture
    return ($r.ExitCode -eq 0)
}

function Show-LogTail([string]$Path, [int]$Lines = 15) {
    if (Test-Path -LiteralPath $Path) {
        Write-Host "   Últimas linhas de ${Path}:"
        try { Get-Content -LiteralPath $Path -Tail $Lines | ForEach-Object { Write-Host "     $_" } } catch { }
    }
}

function Get-PgRunningPort {
    # Port of the running server, from line 4 of postmaster.pid; $null if unknown.
    try {
        $lines = [System.IO.File]::ReadAllLines((Join-Path $PgData "postmaster.pid"))
        $port = 0
        if ($lines.Count -ge 4 -and [int]::TryParse($lines[3].Trim(), [ref]$port)) { return $port }
    } catch { }
    return $null
}

function Wait-PgReady([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PgReady) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Start-Postgres {
    if (Test-PgRunning) {
        $runningPort = Get-PgRunningPort
        if ($runningPort -and $runningPort -ne $PgPort) {
            # e.g. the 5432 of the first laptop trial: restart with our postgresql.conf.
            Write-Note "PostgreSQL rodando na porta $runningPort; reiniciando na porta $PgPort."
            Stop-Postgres
        } elseif (Wait-PgReady 60) {
            Write-Ok "PostgreSQL já está rodando ($PgHost`:$PgPort)."
            return
        } else {
            Show-LogTail $PgLog
            throw "O PostgreSQL está rodando mas não aceita conexões em $PgHost`:$PgPort."
        }
    }
    if (Test-PortOpen $PgHost $PgPort) {
        $owner = Get-PortOwner $PgPort
        throw "A porta $PgPort já está em uso por outro programa ($owner). Feche esse programa e tente de novo."
    }
    if ((Test-Path -LiteralPath $PgLog) -and (Get-Item -LiteralPath $PgLog).Length -gt 20MB) {
        Move-Item -LiteralPath $PgLog -Destination "$PgLog.old" -Force
    }
    Write-Step "Iniciando o PostgreSQL ($PgHost`:$PgPort)"
    # Detached and never piped: a piped pg_ctl start crashed the server
    # (0xC0000142) once the parent window closed (laptop trial).
    try {
        Start-Process -FilePath $PgCtl -ArgumentList (Join-ArgString @("start", "-D", $PgData, "-l", $PgLog)) -WindowStyle Hidden | Out-Null
    } catch {
        if (Test-AppControlText $_.Exception.Message) { $script:AppControlProgram = $PgCtl }
        throw "Não foi possível iniciar o PostgreSQL: $($_.Exception.Message)"
    }
    if (Wait-PgReady 60) { Write-Ok "PostgreSQL pronto."; return }
    Show-LogTail $PgLog
    if (Test-Path -LiteralPath $PgLog) {
        $text = (Get-Content -LiteralPath $PgLog -Tail 50) -join "`n"
        if (Test-AppControlText $text) { $script:AppControlProgram = (Join-Path $PgBin "postgres.exe") }
    }
    throw "O PostgreSQL não respondeu em 60 s."
}

function Stop-Postgres {
    if (-not (Test-PgRunning)) { Write-Ok "PostgreSQL já estava parado."; return }
    Write-Step "Parando o PostgreSQL"
    $r = Invoke-Native $PgCtl @("stop", "-D", $PgData, "-m", "fast", "-w", "-t", "60")
    if ($r.ExitCode -ne 0) { throw "pg_ctl stop terminou com código $($r.ExitCode)." }
    Write-Ok "PostgreSQL parado."
}

# --- the app process ---------------------------------------------------------

function Get-AppProcess {
    # The running Dash FIDCs server process from app.pid, verified to be our
    # python running app.main:app; $null otherwise. The venv python.exe is only
    # a launcher, so the PID file is written by the real interpreter itself.
    if (-not (Test-Path -LiteralPath $AppPidFile)) { return $null }
    $text = ([System.IO.File]::ReadAllText($AppPidFile)).Trim()
    $procId = 0
    if (-not [int]::TryParse($text, [ref]$procId)) { return $null }
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.ProcessName -notlike "python*") { return $null }
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction Stop
        if ($cim.CommandLine -and $cim.CommandLine -notlike "*app.main:app*") { return $null }
    } catch {
        # Without CIM the process name check above has to do.
    }
    return $proc
}

function Wait-AppHealth([string]$TargetHost, [int]$Port, [int]$ProcId, [int]$Seconds) {
    # /api/health of a server that may still be starting, polled for up to
    # $Seconds; $null when it never answers or the process ends first.
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($true) {
        $health = Get-Health $TargetHost $Port
        if ($health) { return $health }
        if (-not (Get-Process -Id $ProcId -ErrorAction SilentlyContinue)) { return $null }
        if ((Get-Date) -ge $deadline) { return $null }
        Start-Sleep -Seconds 1
    }
}

function Stop-App {
    # Stops the server started by start.ps1 (PID from app.pid) and waits until
    # its port is free. Used by stop.ps1 and by setup.ps1 before pip runs.
    Write-Step "Parando o Dash FIDCs"
    $port = Get-AppPort
    $probe = Get-ProbeHost (Get-AppHost)
    $proc = Get-AppProcess
    if (-not $proc) {
        Write-Ok "O app não estava rodando."
        if (Test-PortOpen $probe $port) {
            Write-Warn "a porta $port está em uso por $(Get-PortOwner $port), que não foi aberto pelo Iniciar.cmd; não foi parado."
        }
    } else {
        $procId = $proc.Id
        # The venv launcher (parent) exits by itself when the server process ends.
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        try { Wait-Process -Id $procId -Timeout 15 -ErrorAction SilentlyContinue } catch { }
        $deadline = (Get-Date).AddSeconds(15)
        while ((Test-PortOpen $probe $port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        Write-Ok "App parado (PID $procId)."
    }
    if (Test-Path -LiteralPath $AppPidFile) { Remove-Item -LiteralPath $AppPidFile -Force }
}
