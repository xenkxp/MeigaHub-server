param(
    [ValidateSet("start","stop")]
    [string]$Action = "start",
    [string]$EnvPath = ""
)

# ── Resolver rutas ──────────────────────────────────────────────
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir
if (-not $EnvPath) { $EnvPath = Join-Path $projectDir ".env" }

# ── Leer .env ───────────────────────────────────────────────────
function Read-EnvFile($Path) {
    $map = @{}
    if (!(Test-Path $Path)) { return $map }
    foreach ($line in (Get-Content $Path)) {
        $t = $line.Trim()
        if ($t.StartsWith("#") -or $t.Length -eq 0) { continue }
        $parts = $t.Split("=", 2)
        if ($parts.Count -eq 2) { $map[$parts[0].Trim()] = $parts[1].Trim() }
    }
    return $map
}

# ── Encontrar Python ────────────────────────────────────────────
function Find-PythonExe {
    # Devuelve la ruta completa al ejecutable python, o $null
    # 1. Intentar py launcher (instalación estándar de python.org)
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        # Verificar que puede ejecutar Python 3
        try {
            $ver = & py -3 --version 2>&1
            if ($LASTEXITCODE -eq 0) { return $pyLauncher.Source }
        } catch {}
    }
    # 2. Buscar en rutas comunes de instalación
    $commonPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $commonPaths) {
        if (Test-Path $p) { return $p }
    }
    # 3. Buscar en PATH
    $cmd = Get-Command python3 -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# ── Matar procesos propios ──────────────────────────────────────
function Stop-OurProcesses {
    # 1. Matar uvicorn (proxy)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "app\.main" } |
        ForEach-Object {
            Write-Host "  Matando uvicorn (PID $($_.ProcessId))..." -ForegroundColor DarkYellow
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    # 2. Matar llama-server / whisper-server (libera VRAM)
    foreach ($name in @("llama-server","whisper-server")) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "  Matando $name (PID $($_.Id))..." -ForegroundColor DarkYellow
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }

    # 3. Matar cmd.exe huérfanos que lanzaron llama/whisper (pueden retener GPU)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "cmd.exe" -and $_.CommandLine -match "llama-server|whisper-server" } |
        ForEach-Object {
            Write-Host "  Matando cmd wrapper (PID $($_.ProcessId))..." -ForegroundColor DarkYellow
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    # Esperar un momento para que la GPU libere VRAM
    Start-Sleep -Seconds 2
}

function Wait-PortFree($Port, $Seconds = 8) {
    # Solo considera el puerto "ocupado" si hay un proceso python escuchando.
    # Ignora VS Code port-forwards y otros servicios.
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $pythonListeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq $Port } |
            Where-Object {
                $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                $proc -and $proc.ProcessName -eq "python"
            }
        if (-not $pythonListeners) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# ══════════════════════════════════════════════════════════════════
#  STOP
# ══════════════════════════════════════════════════════════════════
if ($Action -eq "stop") {
    Write-Host ""
    Write-Host "=== Deteniendo servidor ===" -ForegroundColor Cyan
    Stop-OurProcesses
    Start-Sleep -Seconds 1
    Write-Host "Servidor detenido." -ForegroundColor Green
    Write-Host ""
    exit 0
}

# ══════════════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "   MeigaHub Server - Iniciando...      " -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

$envMap     = Read-EnvFile $EnvPath
$serverHost = if ($envMap["SERVER_HOST"]) { $envMap["SERVER_HOST"] } else { "0.0.0.0" }
$serverPort = if ($envMap["SERVER_PORT"]) { $envMap["SERVER_PORT"] } else { "3112" }
$llmStart   = $envMap["LLM_START_COMMAND"]

# ── 1. Matar procesos anteriores ────────────────────────────────
Write-Host "[1/4] Limpiando procesos anteriores..." -ForegroundColor Yellow
Stop-OurProcesses
if (-not (Wait-PortFree $serverPort 5)) {
    Write-Host "  AVISO: Puerto $serverPort aún ocupado, verificando..." -ForegroundColor Red
    # Solo matar procesos python que usen nuestro puerto — NUNCA procesos de VS Code u otros
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $serverPort }
    foreach ($conn in $listeners) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "python") {
            Write-Host "  Matando python zombie (PID $($proc.Id))..." -ForegroundColor DarkYellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host "  Puerto $serverPort usado por $($proc.ProcessName) (PID $($conn.OwningProcess)) - NO se toca (posible VS Code port-forward)" -ForegroundColor DarkGray
        }
    }
    Start-Sleep -Seconds 2
}
Write-Host "  OK" -ForegroundColor Green

# ── 2. Encontrar Python ─────────────────────────────────────────
Write-Host "[2/4] Buscando Python..." -ForegroundColor Yellow
$pythonExe = Find-PythonExe
if (-not $pythonExe) {
    Write-Host "  ERROR: No se encontro Python" -ForegroundColor Red
    pause
    exit 1
}
Write-Host "  Python: $pythonExe" -ForegroundColor Green

# ── 3. Iniciar llama-server (si configurado) ────────────────────
Write-Host "[3/4] Backend LLM..." -ForegroundColor Yellow
if ($llmStart) {
    $llamaRunning = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
    if ($llamaRunning) {
        Write-Host "  llama-server ya corriendo (PID $($llamaRunning[0].Id)), no se relanza" -ForegroundColor DarkGreen
    } else {
        Write-Host "  Iniciando llama-server (ventana oculta)..." -ForegroundColor DarkGray
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $llmStart -WindowStyle Hidden
        Write-Host "  OK" -ForegroundColor Green
    }
} else {
    Write-Host "  LLM_START_COMMAND vacio, se asume backend externo" -ForegroundColor DarkGray
}

# ── 4. Iniciar uvicorn EN ESTA VENTANA ──────────────────────────
Write-Host "[4/4] Iniciando proxy en http://${serverHost}:${serverPort}" -ForegroundColor Yellow
Write-Host ""
Write-Host "  UI:     http://127.0.0.1:${serverPort}/ui/models" -ForegroundColor Cyan
Write-Host "  Status: http://127.0.0.1:${serverPort}/status" -ForegroundColor Cyan
Write-Host "  Ctrl+C para detener" -ForegroundColor DarkGray
Write-Host ""

Set-Location $projectDir
& $pythonExe -m uvicorn app.main:app --host $serverHost --port $serverPort

Write-Host ""
Write-Host "Servidor detenido." -ForegroundColor Yellow