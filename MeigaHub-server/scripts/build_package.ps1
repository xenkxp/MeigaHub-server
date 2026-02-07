<#
.SYNOPSIS
    Empaqueta el proyecto MeigaHub-server en una carpeta dist\ lista para distribuir.
    NO incluye modelos GGUF ni datos personales.
.DESCRIPTION
    Copia: app\, scripts\, .env.example, requirements.txt, README.md
    Copia: C:\apps\llama.cpp, C:\apps\llama.cpp-cuda, C:\apps\whisper.cpp
    Genera: installer.ps1 dentro del paquete (el instalador real)
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_package.ps1
#>

$ErrorActionPreference = "Stop"

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir
$distDir    = Join-Path $projectDir "dist\meigahub-server"
$appsSrc    = "C:\apps"

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   MeigaHub-server — Generador de paquete instalable     ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Limpiar dist anterior ──
if (Test-Path $distDir) {
    Write-Host "[1/7] Limpiando paquete anterior..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $distDir
}
Write-Host "[1/7] Creando estructura..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
foreach ($d in @("app","scripts","apps\llama.cpp","apps\llama.cpp-cuda","apps\whisper.cpp","models")) {
    New-Item -ItemType Directory -Path (Join-Path $distDir $d) -Force | Out-Null
}
Write-Host "      OK" -ForegroundColor Green

# ── Copiar servidor ──
Write-Host "[2/7] Copiando servidor proxy (app\)..." -ForegroundColor Yellow
Copy-Item -Recurse -Force (Join-Path $projectDir "app\*") (Join-Path $distDir "app\")
# Eliminar __pycache__
$pycache = Join-Path $distDir "app\__pycache__"
if (Test-Path $pycache) { Remove-Item -Recurse -Force $pycache }
Write-Host "      OK" -ForegroundColor Green

# ── Copiar scripts (sin datos personales) ──
Write-Host "[3/7] Copiando scripts y config..." -ForegroundColor Yellow
foreach ($f in @("start_server.bat","stop_server.bat","start_server.ps1","stop_server.ps1","setup_check.ps1","test_llm.py")) {
    $src = Join-Path $projectDir "scripts\$f"
    if (Test-Path $src) { Copy-Item -Force $src (Join-Path $distDir "scripts\$f") }
}
Copy-Item -Force (Join-Path $projectDir "requirements.txt") (Join-Path $distDir "requirements.txt")
Copy-Item -Force (Join-Path $projectDir ".env.example")     (Join-Path $distDir ".env.example")
Copy-Item -Force (Join-Path $projectDir "README.md")        (Join-Path $distDir "README.md")
Write-Host "      OK" -ForegroundColor Green

# ── NO copiar: .env, _gpu_test.txt, __pycache__, .git, dist ──
Write-Host "      (excluidos: .env, _gpu_test.txt, __pycache__)" -ForegroundColor DarkGray

# ── Copiar llama.cpp ──
Write-Host "[4/7] Copiando llama.cpp (CPU)..." -ForegroundColor Yellow
$llamaCpu = Join-Path $appsSrc "llama.cpp"
if (Test-Path $llamaCpu) {
    Copy-Item -Recurse -Force "$llamaCpu\*" (Join-Path $distDir "apps\llama.cpp\")
    Write-Host "      OK" -ForegroundColor Green
} else {
    Write-Host "      OMITIDO — $llamaCpu no encontrada" -ForegroundColor DarkGray
}

Write-Host "[4/7] Copiando llama.cpp-cuda (GPU)..." -ForegroundColor Yellow
$llamaGpu = Join-Path $appsSrc "llama.cpp-cuda"
if (Test-Path $llamaGpu) {
    Copy-Item -Recurse -Force "$llamaGpu\*" (Join-Path $distDir "apps\llama.cpp-cuda\")
    Write-Host "      OK" -ForegroundColor Green
} else {
    Write-Host "      OMITIDO — $llamaGpu no encontrada" -ForegroundColor DarkGray
}

# ── Copiar whisper.cpp ──
Write-Host "[5/7] Copiando whisper.cpp..." -ForegroundColor Yellow
$whisperSrc = Join-Path $appsSrc "whisper.cpp"
if (Test-Path $whisperSrc) {
    Copy-Item -Recurse -Force "$whisperSrc\*" (Join-Path $distDir "apps\whisper.cpp\")
    Write-Host "      OK" -ForegroundColor Green
} else {
    Write-Host "      OMITIDO — $whisperSrc no encontrada" -ForegroundColor DarkGray
}

# ── Crear placeholder en models ──
"Los modelos GGUF van aqui. Descargalos desde la UI en /ui/models" | Out-File -Encoding utf8 (Join-Path $distDir "models\LEEME.txt")

# ── Generar installer.ps1 (script de instalación para el usuario final) ──
Write-Host "[6/7] Generando instalador (installer.ps1)..." -ForegroundColor Yellow

$installerContent = @'
<#
.SYNOPSIS
    Instalador de MeigaHub-server.
    Despliega todo en la carpeta elegida, instala Python si hace falta,
    instala dependencias y configura .env con las rutas correctas.
.EXAMPLE
    Clic derecho → Ejecutar con PowerShell
    O: powershell -ExecutionPolicy Bypass -File installer.ps1
#>

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "MeigaHub-server — Instalador"

function Write-Step($n, $total, $msg) {
    Write-Host "[$n/$total] $msg" -ForegroundColor Yellow
}
function Write-Ok($msg)   { Write-Host "        $msg" -ForegroundColor Green }
function Write-Info($msg)  { Write-Host "        $msg" -ForegroundColor DarkGray }
function Write-Warn($msg)  { Write-Host "        $msg" -ForegroundColor DarkYellow }
function Write-Fail($msg)  { Write-Host "        $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       MeigaHub-server — Instalador                      ║" -ForegroundColor Cyan
Write-Host "║       Texto (llama.cpp) + Audio (whisper.cpp)            ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$totalSteps = 7

# ═══════════════════════════════════════════════════════════
#  PASO 1: Elegir carpeta de instalación
# ═══════════════════════════════════════════════════════════
Write-Step 1 $totalSteps "Carpeta de instalacion"

if (-not $InstallDir) {
    $defaultDir = "C:\MeigaHub"
    Write-Host ""
    Write-Host "  Donde quieres instalar? " -NoNewline -ForegroundColor White
    Write-Host "(Enter = $defaultDir)" -ForegroundColor DarkGray
    $userInput = Read-Host "  Ruta"
    $InstallDir = if ($userInput.Trim()) { $userInput.Trim() } else { $defaultDir }
}

Write-Ok "Destino: $InstallDir"

if (Test-Path $InstallDir) {
    Write-Warn "La carpeta ya existe. Se actualizaran los archivos (modelos no se tocan)."
    $confirm = Read-Host "  Continuar? (S/N)"
    if ($confirm -notin @("S","s","Y","y","")) {
        Write-Host "Instalacion cancelada." -ForegroundColor Red
        exit 0
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 2: Verificar / Instalar Python
# ═══════════════════════════════════════════════════════════
Write-Step 2 $totalSteps "Verificando Python..."

$pythonOk = $false
$pythonExe = $null

# Intentar py launcher
$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
    try {
        $ver = & py -3 --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonOk = $true
                $pythonExe = "py"
                Write-Ok "Encontrado: $ver (py launcher)"
            }
        }
    } catch {}
}

# Intentar python en PATH
if (-not $pythonOk) {
    foreach ($name in @("python3","python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $ver = & $cmd.Source --version 2>&1
                if ($ver -match "Python 3\.(\d+)") {
                    $minor = [int]$Matches[1]
                    if ($minor -ge 10) {
                        $pythonOk = $true
                        $pythonExe = $cmd.Source
                        Write-Ok "Encontrado: $ver ($($cmd.Source))"
                        break
                    }
                }
            } catch {}
        }
    }
}

# Buscar en rutas comunes
if (-not $pythonOk) {
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
        if (Test-Path $p) {
            $pythonOk = $true
            $pythonExe = $p
            Write-Ok "Encontrado: $p"
            break
        }
    }
}

if (-not $pythonOk) {
    Write-Fail "Python 3.10+ no encontrado."
    Write-Host ""
    Write-Host "  ¿Deseas descargar e instalar Python 3.12 automaticamente? (S/N)" -ForegroundColor White
    $installPy = Read-Host "  "
    if ($installPy -in @("S","s","Y","y")) {
        Write-Info "Descargando Python 3.12.8..."
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $pyInstaller = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
            Write-Info "Instalando Python 3.12 (esto puede tardar un minuto)..."
            # Instalación silenciosa: agrega al PATH, instala pip, py launcher
            Start-Process -FilePath $pyInstaller -ArgumentList `
                "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_launcher=1" `
                -Wait -NoNewWindow
            # Refrescar PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            # Verificar
            $pyCmd = Get-Command py -ErrorAction SilentlyContinue
            if ($pyCmd) {
                $pythonOk = $true
                $pythonExe = "py"
                Write-Ok "Python 3.12 instalado correctamente"
            } else {
                Write-Fail "La instalacion termino pero no se detecta Python. Reinicia el terminal e intenta de nuevo."
                Read-Host "Pulsa Enter para salir"
                exit 1
            }
        } catch {
            Write-Fail "Error descargando Python: $_"
            Write-Host "  Instalalo manualmente desde https://python.org/downloads" -ForegroundColor White
            Read-Host "Pulsa Enter para salir"
            exit 1
        } finally {
            if (Test-Path $pyInstaller) { Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue }
        }
    } else {
        Write-Host ""
        Write-Host "  Instala Python 3.10+ desde https://python.org/downloads" -ForegroundColor White
        Write-Host "  IMPORTANTE: Marca 'Add Python to PATH' durante la instalacion" -ForegroundColor Yellow
        Read-Host "Pulsa Enter para salir"
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 3: Copiar archivos
# ═══════════════════════════════════════════════════════════
Write-Step 3 $totalSteps "Copiando archivos a $InstallDir..."

# Crear estructura
foreach ($d in @("app","scripts","apps","models")) {
    New-Item -ItemType Directory -Path (Join-Path $InstallDir $d) -Force | Out-Null
}

# Copiar servidor
if (Test-Path (Join-Path $packageDir "app")) {
    Copy-Item -Recurse -Force (Join-Path $packageDir "app\*") (Join-Path $InstallDir "app\")
    Write-Info "app\ copiado"
}

# Copiar scripts
if (Test-Path (Join-Path $packageDir "scripts")) {
    Copy-Item -Recurse -Force (Join-Path $packageDir "scripts\*") (Join-Path $InstallDir "scripts\")
    Write-Info "scripts\ copiado"
}

# Copiar requirements.txt, README, .env.example
foreach ($f in @("requirements.txt","README.md",".env.example")) {
    $src = Join-Path $packageDir $f
    if (Test-Path $src) { Copy-Item -Force $src (Join-Path $InstallDir $f) }
}
Write-Info "requirements.txt, README.md, .env.example copiados"

# Copiar apps (backends)
$appsSource = Join-Path $packageDir "apps"
if (Test-Path $appsSource) {
    foreach ($backend in @("llama.cpp","llama.cpp-cuda","whisper.cpp")) {
        $src = Join-Path $appsSource $backend
        $dst = Join-Path $InstallDir "apps\$backend"
        if (Test-Path $src) {
            New-Item -ItemType Directory -Path $dst -Force | Out-Null
            Copy-Item -Recurse -Force "$src\*" $dst
            Write-Info "apps\$backend copiado"
        }
    }
}

Write-Ok "Archivos copiados"

# ═══════════════════════════════════════════════════════════
#  PASO 4: Instalar dependencias Python
# ═══════════════════════════════════════════════════════════
Write-Step 4 $totalSteps "Instalando dependencias Python..."

$reqFile = Join-Path $InstallDir "requirements.txt"
if (Test-Path $reqFile) {
    if ($pythonExe -eq "py") {
        & py -3 -m pip install -r $reqFile --quiet 2>&1 | Out-Null
    } else {
        & $pythonExe -m pip install -r $reqFile --quiet 2>&1 | Out-Null
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Dependencias instaladas"
    } else {
        Write-Warn "Hubo warnings al instalar dependencias (puede funcionar igual)"
    }
} else {
    Write-Warn "requirements.txt no encontrado, saltando"
}

# ═══════════════════════════════════════════════════════════
#  PASO 5: Generar .env con rutas reales
# ═══════════════════════════════════════════════════════════
Write-Step 5 $totalSteps "Configurando .env..."

$envFile = Join-Path $InstallDir ".env"
$envExample = Join-Path $InstallDir ".env.example"

if (Test-Path $envFile) {
    Write-Info ".env ya existe, no se sobreescribe"
    Write-Info "Si quieres regenerarlo, borralo y ejecuta el instalador de nuevo"
} else {
    if (Test-Path $envExample) {
        $content = Get-Content $envExample -Raw
        $content = $content.Replace("__INSTALL_DIR__", $InstallDir)
        $content | Out-File -Encoding utf8 $envFile -NoNewline
        Write-Ok ".env generado con rutas de $InstallDir"
    } else {
        Write-Warn ".env.example no encontrado, no se puede generar .env"
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 6: Detectar GPU y elegir backend LLM
# ═══════════════════════════════════════════════════════════
Write-Step 6 $totalSteps "Detectando GPU..."

$hasNvidia = $false
$gpuName = "No detectada"
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    try {
        $gpuResult = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>&1
        if ($LASTEXITCODE -eq 0 -and $gpuResult) {
            $parts = $gpuResult.ToString().Split(",")
            $gpuName = $parts[0].Trim()
            $vramMB = if ($parts.Count -ge 2) { [int]$parts[1].Trim() } else { 0 }
            $hasNvidia = $true
            Write-Ok "GPU NVIDIA: $gpuName ($([math]::Round($vramMB/1024, 1)) GB VRAM)"
        }
    } catch {}
}

if (-not $hasNvidia) {
    Write-Info "GPU NVIDIA no detectada — se usara llama.cpp CPU"
}

# Actualizar .env para usar el backend correcto
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    if ($hasNvidia) {
        # Si tiene GPU CUDA, usar llama.cpp-cuda
        $cudaExe = Join-Path $InstallDir "apps\llama.cpp-cuda\llama-server.exe"
        $cpuExe  = Join-Path $InstallDir "apps\llama.cpp\llama-server.exe"
        if (Test-Path $cudaExe) {
            Write-Info "Configurando backend LLM: llama.cpp-cuda (GPU)"
            # Ya deberia apuntar a llama.cpp por defecto, cambiar a cuda
            $envContent = $envContent.Replace("apps\llama.cpp\llama-server.exe", "apps\llama.cpp-cuda\llama-server.exe")
        } elseif (Test-Path $cpuExe) {
            Write-Info "llama.cpp-cuda no encontrado, usando CPU"
        }
    }
    $envContent | Out-File -Encoding utf8 $envFile -NoNewline
}

# ═══════════════════════════════════════════════════════════
#  PASO 7: Verificación final
# ═══════════════════════════════════════════════════════════
Write-Step 7 $totalSteps "Verificando instalacion..."

$checks = @(
    @{ Label = "app\main.py";              Path = Join-Path $InstallDir "app\main.py" },
    @{ Label = "requirements.txt";         Path = Join-Path $InstallDir "requirements.txt" },
    @{ Label = ".env";                     Path = Join-Path $InstallDir ".env" },
    @{ Label = "scripts\start_server.bat"; Path = Join-Path $InstallDir "scripts\start_server.bat" },
    @{ Label = "llama-server (CPU)";       Path = Join-Path $InstallDir "apps\llama.cpp\llama-server.exe" },
    @{ Label = "llama-server (CUDA)";      Path = Join-Path $InstallDir "apps\llama.cpp-cuda\llama-server.exe" },
    @{ Label = "whisper-server";           Path = Join-Path $InstallDir "apps\whisper.cpp\Release\whisper-server.exe" }
)

$allOk = $true
foreach ($check in $checks) {
    if (Test-Path $check.Path) {
        Write-Host "        [OK]    $($check.Label)" -ForegroundColor Green
    } else {
        Write-Host "        [FALTA] $($check.Label)" -ForegroundColor DarkYellow
        $allOk = $false
    }
}

# Verificar modelos
$modelsDir = Join-Path $InstallDir "models"
$ggufFiles = Get-ChildItem -Path $modelsDir -Filter "*.gguf" -ErrorAction SilentlyContinue
$binFiles  = Get-ChildItem -Path $modelsDir -Filter "*.bin" -ErrorAction SilentlyContinue
$modelCount = ($ggufFiles.Count + $binFiles.Count)
if ($modelCount -gt 0) {
    Write-Host "        [OK]    $modelCount modelo(s) encontrados en models\" -ForegroundColor Green
} else {
    Write-Host "        [INFO]  Sin modelos — descargalos desde la UI o manualmente" -ForegroundColor DarkYellow
}

# ═══════════════════════════════════════════════════════════
#  RESUMEN FINAL
# ═══════════════════════════════════════════════════════════
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
if ($allOk) {
    Write-Host "  ✅ Instalacion completada!" -ForegroundColor Green
} else {
    Write-Host "  ⚠  Instalacion completada con advertencias" -ForegroundColor Yellow
    Write-Host "     (algunos ejecutables o backends no se encontraron)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  📂 Instalado en:  $InstallDir" -ForegroundColor White
Write-Host ""
Write-Host "  ▶  Para iniciar:  $InstallDir\scripts\start_server.bat" -ForegroundColor Cyan
Write-Host "  ■  Para detener:  $InstallDir\scripts\stop_server.bat" -ForegroundColor Cyan
Write-Host "  🌐 Interfaz web:  http://127.0.0.1:3112/ui/models" -ForegroundColor Cyan
Write-Host "  📡 Estado:        http://127.0.0.1:3112/status" -ForegroundColor Cyan
Write-Host ""
Write-Host "  📋 Siguiente paso:" -ForegroundColor White
if ($modelCount -eq 0) {
    Write-Host "     1. Descarga modelos GGUF desde la interfaz web o manualmente" -ForegroundColor DarkGray
    Write-Host "     2. Edita .env si necesitas ajustar configuracion" -ForegroundColor DarkGray
    Write-Host "     3. Ejecuta scripts\start_server.bat" -ForegroundColor DarkGray
} else {
    Write-Host "     1. Revisa .env para confirmar la configuracion" -ForegroundColor DarkGray
    Write-Host "     2. Ejecuta scripts\start_server.bat" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Preguntar si crear acceso directo en escritorio
$createShortcut = Read-Host "Crear acceso directo en el Escritorio? (S/N)"
if ($createShortcut -in @("S","s","Y","y")) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shell = New-Object -ComObject WScript.Shell
        # Acceso directo para iniciar
        $lnk = $shell.CreateShortcut((Join-Path $desktop "MeigaHub Server.lnk"))
        $lnk.TargetPath = Join-Path $InstallDir "scripts\start_server.bat"
        $lnk.WorkingDirectory = $InstallDir
        $lnk.Description = "Iniciar MeigaHub Server"
        $lnk.Save()
        Write-Ok "Acceso directo creado en el Escritorio"
    } catch {
        Write-Warn "No se pudo crear el acceso directo: $_"
    }
}

Write-Host ""
Read-Host "Pulsa Enter para salir"
'@

$installerContent | Out-File -Encoding utf8 (Join-Path $distDir "installer.ps1")

# Crear un .bat wrapper para el installer (doble clic friendly)
$batWrapper = @'
@echo off
title MeigaHub-server - Instalador
color 0B
echo.
echo   Iniciando instalador...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer.ps1"
'@
$batWrapper | Out-File -Encoding ascii (Join-Path $distDir "INSTALAR.bat")

Write-Host "      OK" -ForegroundColor Green

# ── Resumen del paquete ──
Write-Host "[7/7] Calculando tamaño..." -ForegroundColor Yellow
$sizeBytes = (Get-ChildItem -Recurse -Force $distDir | Measure-Object -Property Length -Sum).Sum
$sizeMB = [math]::Round($sizeBytes / 1MB, 1)

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Paquete creado: $distDir" -ForegroundColor White
Write-Host "  Tamaño: $sizeMB MB" -ForegroundColor White
Write-Host ""
Write-Host "  Contenido:" -ForegroundColor DarkGray
Write-Host "    app\            Codigo del servidor proxy" -ForegroundColor DarkGray
Write-Host "    apps\           Ejecutables llama.cpp + whisper.cpp" -ForegroundColor DarkGray
Write-Host "    scripts\        Scripts inicio/parada/test" -ForegroundColor DarkGray
Write-Host "    models\         (vacio — el usuario descarga modelos)" -ForegroundColor DarkGray
Write-Host "    .env.example    Plantilla de configuracion" -ForegroundColor DarkGray
Write-Host "    installer.ps1   Instalador PowerShell" -ForegroundColor DarkGray
Write-Host "    INSTALAR.bat    Doble clic para instalar" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  EXCLUIDO:" -ForegroundColor DarkYellow
Write-Host "    .env            (datos personales, se genera al instalar)" -ForegroundColor DarkYellow
Write-Host "    _gpu_test.txt   (info personal de GPU)" -ForegroundColor DarkYellow
Write-Host "    __pycache__     (cache compilado)" -ForegroundColor DarkYellow
Write-Host "    models\*.gguf   (muy grandes, el usuario los descarga)" -ForegroundColor DarkYellow
Write-Host ""
Write-Host "  Para distribuir: comprime dist\meigahub-server en ZIP" -ForegroundColor White
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$compress = Read-Host "Comprimir en ZIP? (S/N)"
if ($compress -in @("S","s","Y","y")) {
    $zipPath = Join-Path $projectDir "dist\meigahub-server.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Write-Host "Comprimiendo..." -ForegroundColor Yellow
    Compress-Archive -Path "$distDir\*" -DestinationPath $zipPath -Force
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "ZIP creado: $zipPath ($zipSize MB)" -ForegroundColor Green
}

Write-Host ""
