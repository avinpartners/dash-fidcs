# Dash FIDCs: one-time setup on Windows, without admin rights. Safe to run
# again: every step is skipped when it is already done.
#
#   1. Python virtual environment + packages (backend\requirements.txt)
#   2. PostgreSQL 16 binaries (reused when %LOCALAPPDATA%\DashFIDCs\pgsql exists)
#   3. Database cluster (initdb, random password) on 127.0.0.1:5434 (PG_PORT in .env)
#   4. Database "dash"
#   5. .env in the project folder (DATABASE_URL, RAW_DATA_DIR, PG_BIN_DIR, ...)
#
# A running app is stopped first, so pip can replace its packages.
# Normally started by Iniciar.cmd (start.ps1) the first time. By hand:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
param(
    # EDB "zip binaries" of PostgreSQL 16 for Windows x64. Used only when
    # %LOCALAPPDATA%\DashFIDCs\pgsql does not exist yet. This is the 16.15
    # file tried on the laptop on 2026-10-06 (373 MB); check
    # https://www.enterprisedb.com/download-postgresql-binaries for a newer 16.x.
    [string]$PgZipUrl = "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260623"
)
. (Join-Path $PSScriptRoot "common.ps1")

function Find-BasePython {
    # Python 3.12 (or 3.11+) installed for this user; never the Microsoft Store stub.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += , @("py", "-3.12") }
    $candidates += , @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"))
    if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @("python") }
    foreach ($c in $candidates) {
        $exe = $c[0]
        if ($exe -like "*\*" -and -not (Test-Path -LiteralPath $exe)) { continue }
        $prefix = @()
        if ($c.Count -gt 1) { $prefix = @($c[1..($c.Count - 1)]) }
        try {
            $r = Invoke-Native $exe ($prefix + @("-c", "import sys; print(sys.executable); print(sys.version_info >= (3, 11))")) -Capture
        } catch {
            if ($script:AppControlProgram) { throw }
            continue
        }
        if ($r.ExitCode -eq 0 -and $r.Output.Count -ge 2 -and "$($r.Output[1])".Trim() -eq "True") {
            $path = "$($r.Output[0])".Trim()
            if ($path -notlike "*\WindowsApps\*") { return $path }
        }
    }
    throw "Python 3.12 não encontrado. Instale o Python 3.12 de python.org (opção 'Install for me only') e rode de novo."
}

function Test-PipFilesInUse([string]$Text) {
    # Windows refuses to replace a .pyd that a running python has loaded.
    return $Text -match "WinError 5\b|WinError 32\b|Access is denied|Acesso negado"
}

function Install-Venv {
    Write-Step "Ambiente Python ($VenvDir)"
    $ok = $false
    if (Test-Path -LiteralPath $VenvPython) {
        try { $ok = ((Invoke-Native $VenvPython @("-c", "import sys") -Capture).ExitCode -eq 0) } catch { if ($script:AppControlProgram) { throw } }
        if (-not $ok) {
            Write-Note "Ambiente Python existente não funciona (Python atualizado?); recriando."
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        }
    }
    if (-not $ok) {
        $base = Find-BasePython
        Write-Note "Criando o ambiente com $base"
        $r = Invoke-Native $base @("-m", "venv", $VenvDir)
        if ($r.ExitCode -ne 0) { throw "Falha ao criar o ambiente Python (código $($r.ExitCode))." }
    }
    Write-Step "Instalando pacotes Python (pode levar alguns minutos na primeira vez)"
    $r = Invoke-Native $VenvPython @("-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location", "-r", $Requirements) -Tee
    if ($r.ExitCode -ne 0) {
        if (Test-PipFilesInUse ($r.Output -join "`n")) {
            throw "pip não conseguiu substituir arquivos em uso: feche o Dash FIDCs (Parar.cmd) e rode Iniciar.cmd de novo."
        }
        throw "pip install falhou (código $($r.ExitCode)). Verifique a internet/proxy e rode de novo."
    }
    Write-Ok "Pacotes Python instalados."
}

function Install-PgBinaries {
    Write-Step "PostgreSQL 16 ($PgDir)"
    if (Test-Path -LiteralPath $PgCtl) {
        Write-Ok "Binários já presentes; reaproveitando."
    } else {
        $downloads = Join-Path $AppHome "downloads"
        New-Item -ItemType Directory -Force -Path $downloads | Out-Null
        $zip = Join-Path $downloads "postgresql-16-windows-x64-binaries.zip"
        if (-not (Test-Path -LiteralPath $zip)) {
            Write-Note "Baixando $PgZipUrl (cerca de 370 MB)..."
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            if ([Net.WebRequest]::DefaultWebProxy) {
                [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
            }
            $ProgressPreference = "SilentlyContinue"   # the progress bar makes large downloads very slow in 5.1
            $partial = "$zip.part"
            Invoke-WebRequest -Uri $PgZipUrl -OutFile $partial -UseBasicParsing
            Move-Item -LiteralPath $partial -Destination $zip -Force
        }
        Write-Note "Descompactando (sem pgAdmin, StackBuilder e documentação)..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $staging = Join-Path $AppHome "pgsql_unzip"
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $staging | Out-Null
        $root = [System.IO.Path]::GetFullPath($staging) + "\"
        $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
        try {
            foreach ($entry in $archive.Entries) {
                $name = $entry.FullName -replace "/", "\"
                if ($name -match '^pgsql\\(pgAdmin[^\\]*|StackBuilder|doc|symbols)\\') { continue }
                $dest = [System.IO.Path]::GetFullPath((Join-Path $staging $name))
                if (-not $dest.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { continue }
                if ($name.EndsWith("\")) { New-Item -ItemType Directory -Force -Path $dest | Out-Null; continue }
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
            }
        } finally {
            $archive.Dispose()
        }
        $unpacked = Join-Path $staging "pgsql"
        if (-not (Test-Path -LiteralPath (Join-Path $unpacked "bin\pg_ctl.exe"))) {
            throw "O zip baixado não tem pgsql\bin\pg_ctl.exe. Confira o endereço em -PgZipUrl."
        }
        Move-Item -LiteralPath $unpacked -Destination $PgDir
        Remove-Item -LiteralPath $staging -Recurse -Force
        Remove-Item -LiteralPath $zip -Force
        Write-Ok "Binários instalados."
    }
    # Fails fast (with the App Control message) if Windows blocks the binaries.
    $r = Invoke-Native $PgCtl @("--version") -Capture
    if ($r.ExitCode -ne 0) { throw "pg_ctl não executou (código $($r.ExitCode))." }
    Write-Ok ("Versão: " + ($r.Output -join " "))
}

function New-RandomPassword([int]$Length = 24) {
    $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $buffer = New-Object byte[] 1
    $sb = New-Object System.Text.StringBuilder
    try {
        while ($sb.Length -lt $Length) {
            $rng.GetBytes($buffer)
            if ($buffer[0] -lt 248) { [void]$sb.Append($chars[$buffer[0] % 62]) }   # 248 = 4 * 62: no modulo bias
        }
    } finally {
        $rng.Dispose()
    }
    return $sb.ToString()
}

function Initialize-Cluster {
    Write-Step "Banco de dados ($PgData)"
    if (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION")) {
        if (-not (Test-Path -LiteralPath $PasswordFile)) {
            throw "O banco já existe mas a senha ($PasswordFile) sumiu. Sem ela o app não conecta; peça ajuda antes de apagar qualquer coisa."
        }
        Write-Ok "Banco já inicializado; reaproveitando."
        return
    }
    if ((Test-Path -LiteralPath $PgData) -and (Get-ChildItem -LiteralPath $PgData -Force | Select-Object -First 1)) {
        throw "A pasta $PgData não está vazia mas não é um banco PostgreSQL. Mova-a para outro lugar e rode de novo."
    }
    if (-not (Test-Path -LiteralPath $PasswordFile)) {
        [System.IO.File]::WriteAllText($PasswordFile, (New-RandomPassword 24), [System.Text.Encoding]::ASCII)
        Write-Note "Senha aleatória gerada em $PasswordFile."
    }
    $initdb = Join-Path $PgBin "initdb.exe"
    $r = Invoke-Native $initdb @("-D", $PgData, "-U", "dash", "--auth=scram-sha-256", "--pwfile=$PasswordFile",
                                 "-E", "UTF8", "--locale=C")
    if ($r.ExitCode -ne 0) { throw "initdb falhou (código $($r.ExitCode))." }
    Write-Ok "Banco inicializado (usuário dash, UTF8, locale C)."
}

function Set-PgConfig {
    # Local connections only, on our own port. Lines tagged "# DashFIDCs" are
    # ours and replaced on every run; the last setting in the file wins.
    $conf = Join-Path $PgData "postgresql.conf"
    $text = [System.IO.File]::ReadAllText($conf)
    $kept = @($text -split "`r?`n" | Where-Object { $_ -notmatch "#\s*DashFIDCs\s*$" })
    while ($kept.Count -gt 0 -and $kept[-1].Trim() -eq "") { $kept = @($kept | Select-Object -First ($kept.Count - 1)) }
    $kept += ""
    $kept += "listen_addresses = '$PgHost'`t# DashFIDCs"
    $kept += "port = $PgPort`t# DashFIDCs"
    $new = ($kept -join "`n") + "`n"
    if ($new -ne $text) {
        [System.IO.File]::WriteAllText($conf, $new, $Utf8NoBom)
        Write-Ok "postgresql.conf: $PgHost, porta $PgPort."
    }
}

function Initialize-Database {
    Write-Step "Banco 'dash'"
    $psql = Join-Path $PgBin "psql.exe"
    $env:PGPASSWORD = Get-DbPassword
    try {
        $common = @("-h", $PgHost, "-p", "$PgPort", "-U", "dash", "-d", "postgres", "-X", "-q", "-t", "-A")
        $r = Invoke-Native $psql ($common + @("-c", "SELECT 1 FROM pg_database WHERE datname = 'dash'")) -Capture
        if ($r.ExitCode -ne 0) { throw "Não foi possível conectar ao PostgreSQL (código $($r.ExitCode)). Veja $PgLog." }
        if (($r.Output -join "").Trim() -eq "1") {
            Write-Ok "Já existe."
        } else {
            $r = Invoke-Native $psql ($common + @("-c", "CREATE DATABASE dash"))
            if ($r.ExitCode -ne 0) { throw "CREATE DATABASE dash falhou (código $($r.ExitCode))." }
            Write-Ok "Criado. As tabelas são criadas pelo app na primeira vez que ele abre."
        }
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Write-DotEnv {
    Write-Step "Arquivo de configuração ($EnvFile)"
    $password = [Uri]::EscapeDataString((Get-DbPassword))
    # BACKUP_DIR follows the project folder (start.ps1 re-runs setup after a move).
    $always = [ordered]@{
        DATABASE_URL = "postgresql://dash:$password@${PgHost}:$PgPort/dash"
        PG_BIN_DIR   = $PgBin
        BACKUP_DIR   = (Join-Path $RepoRoot "backups")
    }
    # Kept when already set: the cache may have been moved on purpose, and
    # APP_HOST becomes 0.0.0.0 once IT opens port 8081 (README.md).
    $ifEmpty = [ordered]@{
        RAW_DATA_DIR = $RawDir
        APP_HOST     = "127.0.0.1"
    }
    Set-EnvValues -Always $always -IfEmpty $ifEmpty
    Write-Ok ".env atualizado (APP_PASSCODE e outras chaves suas foram mantidas)."
}

function Write-SetupMarker {
    $hash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $lines = @("requirements_sha256=$hash", "repo_root=$RepoRoot", "pg_port=$PgPort", "completed_at=$((Get-Date).ToString('s'))")
    [System.IO.File]::WriteAllLines($SetupMarker, $lines, $Utf8NoBom)
}

try {
    Assert-FullLanguage
    # Re-entrant: start.ps1 already holds it when it runs this script.
    Assert-ScriptLock 0
    Write-Host "Dash FIDCs: preparando este computador (pode ser rodado mais de uma vez)." -ForegroundColor White
    Initialize-AppHome
    if (Get-AppProcess) {
        # pip cannot replace packages the running server has loaded (WinError 5/32).
        Write-Note "Fechando o app para atualizar os pacotes."
        Stop-App
    }
    Install-Venv
    Install-PgBinaries
    Initialize-Cluster
    Set-PgConfig
    Start-Postgres
    Initialize-Database
    Write-DotEnv
    Write-SetupMarker
    Write-Host ""
    Write-Host "Preparação concluída. Para abrir o painel: Iniciar.cmd" -ForegroundColor Green
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
