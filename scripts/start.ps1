# Dash FIDCs: start PostgreSQL and the app, then open the browser.
# Double-click Iniciar.cmd, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 [-NoBrowser]
#
# Runs setup.ps1 first when this computer was never set up, when
# backend\requirements.txt changed since the last setup, when the folder
# moved or when PG_PORT in .env changed.
#
# Optional, only when Ricardo asks for it: -Autostart adds a shortcut to his
# Windows Startup folder so the app starts at logon (no browser window);
# -RemoveAutostart removes it. Neither needs admin rights.
param(
    [switch]$NoBrowser,
    [switch]$Autostart,
    [switch]$RemoveAutostart
)
. (Join-Path $PSScriptRoot "common.ps1")

$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "Dash FIDCs.lnk"

function Set-Autostart {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($ShortcutPath)
    $lnk.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $PSScriptRoot 'start.ps1')`" -NoBrowser"
    $lnk.WorkingDirectory = $RepoRoot
    $lnk.Description = "Inicia o Dash FIDCs ao entrar no Windows"
    $lnk.Save()
    Write-Ok "Atalho criado: $ShortcutPath"
    Write-Note "O Dash FIDCs vai iniciar sozinho quando você entrar no Windows. Para desfazer: scripts\start.ps1 -RemoveAutostart"
}

function Test-SetupNeeded {
    if (-not (Test-Path -LiteralPath $SetupMarker)) { return $true }
    if (-not (Test-Path -LiteralPath $VenvPython) -or -not (Test-Path -LiteralPath $PgCtl)) { return $true }
    if (-not (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION")) -or -not (Test-Path -LiteralPath $EnvFile)) { return $true }
    # Packages changed with an update, or the project folder was moved (.env paths).
    $marker = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($SetupMarker, [System.Text.Encoding]::UTF8)) {
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2) { $marker[$parts[0]] = $parts[1] }
    }
    # PG_PORT changed in .env: setup rewrites postgresql.conf and DATABASE_URL.
    $markerPgPort = $marker["pg_port"]
    if (-not $markerPgPort) { $markerPgPort = "$DefaultPgPort" }   # markers written before PG_PORT existed
    $hash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    return ($marker["requirements_sha256"] -ne $hash -or $marker["repo_root"] -ne $RepoRoot -or $markerPgPort -ne "$PgPort")
}

function Move-OldLog([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        try { Move-Item -LiteralPath $Path -Destination ($Path -replace "\.log$", ".prev.log") -Force } catch { }
    }
}

function Start-App([string]$BindHost, [int]$Port) {
    Write-Step "Iniciando o Dash FIDCs ($BindHost`:$Port)"
    if (Test-Path -LiteralPath $AppPidFile) { Remove-Item -LiteralPath $AppPidFile -Force }
    Move-OldLog $AppOutLog
    Move-OldLog $AppErrLog
    # The venv python.exe is a launcher that starts the real interpreter as a
    # child, so the server writes its own PID (os.getpid()) for stop.ps1.
    $code = "import os,sys,pathlib,uvicorn;" +
            "pathlib.Path(os.environ['DASH_PID_FILE']).write_text(str(os.getpid()),encoding='ascii');" +
            "uvicorn.run('app.main:app',host=sys.argv[1],port=int(sys.argv[2]))"
    $env:DASH_PID_FILE = $AppPidFile
    $env:PYTHONUTF8 = "1"
    $env:PYTHONUNBUFFERED = "1"
    try {
        $launcher = Start-Process -FilePath $VenvPython -ArgumentList (Join-ArgString @("-c", $code, $BindHost, "$Port")) `
            -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $AppOutLog -RedirectStandardError $AppErrLog
    } catch {
        if (Test-AppControlText $_.Exception.Message) { $script:AppControlProgram = $VenvPython }
        throw "Não foi possível iniciar o Python: $($_.Exception.Message)"
    }
    $null = $launcher.Handle   # keeps the handle so ExitCode is readable later
    $probe = Get-ProbeHost $BindHost
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        $health = Get-Health $probe $Port
        if ($health) { return $health }
        if ($launcher.HasExited) { break }
    }
    Show-LogTail $AppErrLog 25
    $errText = ""
    if (Test-Path -LiteralPath $AppErrLog) { $errText = (Get-Content -LiteralPath $AppErrLog -Tail 80) -join "`n" }
    if (Test-AppControlText $errText) { $script:AppControlProgram = "Python ou um dos seus pacotes ($VenvDir)" }
    if ($launcher.HasExited) { throw "O app fechou logo ao iniciar (código $($launcher.ExitCode)). Detalhes em $AppErrLog." }
    throw "O app não respondeu em 60 s. Detalhes em $AppErrLog."
}

function Get-LocalUrl([string]$BindHost, [int]$Port) {
    if ($BindHost -in @("0.0.0.0", "127.0.0.1", "localhost")) { return "http://localhost:$Port" }
    return "http://${BindHost}:$Port"
}

function Show-Status([string]$BindHost, [int]$Port, $Health) {
    Write-Host ""
    Write-Host "Dash FIDCs está rodando." -ForegroundColor Green
    Write-Host "   Neste computador: $(Get-LocalUrl $BindHost $Port)"
    if ($Health -and -not $Health.db) {
        Write-Warn "o app abriu, mas não conectou ao banco de dados. Veja $PgLog e $AppErrLog."
    }
    if ($BindHost -in @("127.0.0.1", "localhost")) {
        Write-Note "Acesso pela rede do escritório: desligado (APP_HOST=$BindHost no .env)."
        Write-Note "Depois que a TI liberar a porta $Port no firewall (README.md), troque para APP_HOST=0.0.0.0"
        Write-Note "no arquivo .env, rode Parar.cmd e depois Iniciar.cmd."
    } else {
        foreach ($a in Get-LanAddresses) { Write-Note "Pela rede: http://$($a.Address):$Port  ($($a.Interface))" }
        Write-Note "Pelo nome: http://$($env:COMPUTERNAME.ToLower()):$Port"
        Write-Note "Os colegas só conseguem abrir se a TI tiver liberado a porta $Port no firewall (README.md)."
    }
    Write-Note "Primeira carga e atualizações: página 'Status dos dados'."
    Write-Note "Para parar: Parar.cmd. Logs: $LogDir"
}

try {
    Assert-FullLanguage
    if ($RemoveAutostart) {
        if (Test-Path -LiteralPath $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath -Force; Write-Ok "Início automático removido." }
        else { Write-Ok "Início automático não estava ativado." }
        exit 0
    }
    if ($Autostart) { Set-Autostart; exit 0 }

    # One start/stop at a time: a second double-click waits for the first.
    Assert-ScriptLock 120
    Initialize-AppHome
    if (Test-SetupNeeded) {
        Write-Step "Primeira vez (ou o código/pasta mudou): rodando a preparação"
        # setup.ps1 closes a running app before pip replaces its packages.
        & (Join-Path $PSScriptRoot "setup.ps1")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $bindHost = Get-AppHost
    $port = Get-AppPort
    Start-Postgres

    $running = Get-AppProcess
    $health = $null
    if ($running) {
        # It may still be starting (e.g. the logon autostart): give it a minute.
        $health = Wait-AppHealth (Get-ProbeHost $bindHost) $port $running.Id 60
        if ($health) {
            Write-Ok "O app já estava rodando (PID $($running.Id))."
        } elseif (Get-Process -Id $running.Id -ErrorAction SilentlyContinue) {
            throw "O app está aberto (PID $($running.Id)) mas não responde. Rode Parar.cmd e depois Iniciar.cmd."
        }
    }
    if (-not $health) {
        if (Test-PortOpen (Get-ProbeHost $bindHost) $port) {
            $owner = Get-PortOwner $port
            throw "A porta $port já está em uso por outro programa ($owner). Feche-o, ou escolha outra porta com APP_PORT no .env."
        }
        $health = Start-App $bindHost $port
        $running = Get-AppProcess
        if ($running) { Write-Ok "App iniciado (PID $($running.Id))." }
    }

    Show-Status $bindHost $port $health
    if (-not $NoBrowser) { Start-Process (Get-LocalUrl $bindHost $port) }
    exit 0
} catch {
    Write-Host ""
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    if ($script:AppControlProgram -or (Test-AppControlText $_.Exception.Message)) {
        $program = $script:AppControlProgram
        if (-not $program) { $program = "(veja a mensagem acima)" }
        Show-AppControlHelp $program $_.Exception.Message
    }
    exit 1
} finally {
    Exit-ScriptLock
}
