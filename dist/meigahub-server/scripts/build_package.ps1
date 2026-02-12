<#
.SYNOPSIS
    Empaqueta MeigaHub-server en dist\ listo para distribuir.
    Paquete LIGERO: solo servidor + instalador.
    Los backends (llama.cpp, whisper.cpp) se descargan automaticamente al instalar.
.DESCRIPTION
    Copia: app\, scripts\, .env.example, requirements.txt, README.md
    Genera: installer.ps1 (descarga backends de GitHub) + INSTALAR.bat
    NO incluye: backends (~1 GB), modelos GGUF, datos personales
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_package.ps1
#>

$ErrorActionPreference = "Stop"

$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectDir = Split-Path -Parent $scriptDir
$distDir    = Join-Path $projectDir "dist\meigahub-server"

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  MeigaHub-server -- Generador de paquete ligero" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Limpiar y crear estructura ──
if (Test-Path $distDir) {
    Write-Host "[1/5] Limpiando paquete anterior..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $distDir
}
Write-Host "[1/5] Creando estructura..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
foreach ($d in @("app","scripts","models")) {
    New-Item -ItemType Directory -Path (Join-Path $distDir $d) -Force | Out-Null
}
Write-Host "      OK" -ForegroundColor Green

# ── 2. Copiar servidor ──
Write-Host "[2/5] Copiando servidor proxy (app\)..." -ForegroundColor Yellow
Copy-Item -Recurse -Force (Join-Path $projectDir "app\*") (Join-Path $distDir "app\")
$pycache = Join-Path $distDir "app\__pycache__"
if (Test-Path $pycache) { Remove-Item -Recurse -Force $pycache }
Write-Host "      OK" -ForegroundColor Green

# ── 3. Copiar scripts y config ──
Write-Host "[3/5] Copiando scripts y config..." -ForegroundColor Yellow
foreach ($f in @("start_server.bat","stop_server.bat","start_server.ps1","stop_server.ps1","setup_check.ps1","test_llm.py","build_package.ps1")) {
    $src = Join-Path $projectDir "scripts\$f"
    if (Test-Path $src) { Copy-Item -Force $src (Join-Path $distDir "scripts\$f") }
}
foreach ($f in @("requirements.txt",".env.example","README.md")) {
    $src = Join-Path $projectDir $f
    if (Test-Path $src) { Copy-Item -Force $src (Join-Path $distDir $f) }
}
Write-Host "      OK" -ForegroundColor Green
Write-Host "      (excluidos: .env, _gpu_test.txt, __pycache__, backends, modelos)" -ForegroundColor DarkGray

# Placeholder en models
"Los modelos GGUF van aqui. Descargalos desde la UI en /ui/models o con el instalador." | Out-File -Encoding utf8 (Join-Path $distDir "models\LEEME.txt")

# ── 4. Generar instalador ──
Write-Host "[4/5] Generando instalador..." -ForegroundColor Yellow

$installerContent = @'
<#
.SYNOPSIS
    Instalador de MeigaHub-server.
    Instala el servidor, descarga backends desde GitHub Releases, configura todo.
.EXAMPLE
    Clic derecho > Ejecutar con PowerShell
    O: powershell -ExecutionPolicy Bypass -File installer.ps1
#>

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "MeigaHub-server -- Instalador"

# ── Funciones auxiliares ──

function Write-Step($n, $total, $msg) {
    Write-Host "[$n/$total] $msg" -ForegroundColor Yellow
}
function Write-Ok($msg)   { Write-Host "        $msg" -ForegroundColor Green }
function Write-Info($msg)  { Write-Host "        $msg" -ForegroundColor DarkGray }
function Write-Warn($msg)  { Write-Host "        $msg" -ForegroundColor DarkYellow }
function Write-Fail($msg)  { Write-Host "        $msg" -ForegroundColor Red }

function Download-GithubRelease {
    param(
        [string]$Repo,
        [string]$IncludePattern,
        [string]$ExcludePattern = "",
        [string]$TargetDir,
        [string]$Label
    )
    try {
        Write-Info "Buscando ultima version de $Label..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $headers = @{ "User-Agent" = "MeigaHub-Installer" }
        $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
        $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers
        $tag = $release.tag_name
        Write-Info "Version encontrada: $tag"

        $asset = $release.assets | Where-Object {
            $_.name -like $IncludePattern -and
            ($ExcludePattern -eq "" -or $_.name -notlike $ExcludePattern)
        } | Select-Object -First 1

        if (-not $asset) {
            Write-Warn "No se encontro archivo para el patron: $IncludePattern"
            Write-Warn "Descargalo manualmente desde https://github.com/$Repo/releases"
            return $false
        }

        $url = $asset.browser_download_url
        $fileName = $asset.name
        $sizeMB = [math]::Round($asset.size / 1MB, 0)
        $tempZip = Join-Path $env:TEMP $fileName

        Write-Info "Descargando $fileName ($sizeMB MB)..."
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("User-Agent", "MeigaHub-Installer")
        $wc.DownloadFile($url, $tempZip)

        Write-Info "Extrayendo en $TargetDir..."
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

        # Extraer a carpeta temporal
        $tempExtract = Join-Path $env:TEMP "meigahub_extract_$(Get-Random)"
        Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

        # Si el ZIP tiene una sola carpeta raiz, copiar su contenido
        $items = Get-ChildItem $tempExtract
        if ($items.Count -eq 1 -and $items[0].PSIsContainer) {
            Copy-Item -Recurse -Force "$($items[0].FullName)\*" $TargetDir
        } else {
            Copy-Item -Recurse -Force "$tempExtract\*" $TargetDir
        }

        # Limpiar temporales
        Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue

        Write-Ok "$Label descargado correctamente"
        return $true
    } catch {
        Write-Warn "Error descargando ${Label}: $_"
        Write-Warn "Descargalo manualmente desde https://github.com/$Repo/releases"
        return $false
    }
}

function Find-Exe($dir, $name) {
    if (-not (Test-Path $dir)) { return $null }
    $found = Get-ChildItem -Path $dir -Filter $name -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

# ── Inicio ──

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  MeigaHub-server -- Instalador" -ForegroundColor Cyan
Write-Host "  Texto (llama.cpp) + Audio (whisper.cpp)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$totalSteps = 9

# ═══════════════════════════════════════════════════════════
#  PASO 1: Elegir carpeta de instalacion
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
    Write-Host "  Descargar e instalar Python 3.12 automaticamente? (S/N)" -ForegroundColor White
    $installPy = Read-Host "  "
    if ($installPy -in @("S","s","Y","y")) {
        Write-Info "Descargando Python 3.12.8..."
        $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $pyInstaller = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
            Write-Info "Instalando Python 3.12 (puede tardar un minuto)..."
            Start-Process -FilePath $pyInstaller -ArgumentList `
                "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_launcher=1" `
                -Wait -NoNewWindow
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
            $pyCmd = Get-Command py -ErrorAction SilentlyContinue
            if ($pyCmd) {
                $pythonOk = $true
                $pythonExe = "py"
                Write-Ok "Python 3.12 instalado correctamente"
            } else {
                Write-Fail "No se detecta Python tras instalar. Reinicia el terminal e intenta de nuevo."
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
        Write-Host "  Instala Python 3.10+ desde https://python.org/downloads" -ForegroundColor White
        Write-Host "  IMPORTANTE: Marca 'Add Python to PATH'" -ForegroundColor Yellow
        Read-Host "Pulsa Enter para salir"
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 3: Copiar archivos del servidor
# ═══════════════════════════════════════════════════════════
Write-Step 3 $totalSteps "Copiando archivos a $InstallDir..."

foreach ($d in @("app","scripts","apps","models")) {
    New-Item -ItemType Directory -Path (Join-Path $InstallDir $d) -Force | Out-Null
}

if (Test-Path (Join-Path $packageDir "app")) {
    Copy-Item -Recurse -Force (Join-Path $packageDir "app\*") (Join-Path $InstallDir "app\")
    Write-Info "app\ copiado"
}

if (Test-Path (Join-Path $packageDir "scripts")) {
    Copy-Item -Recurse -Force (Join-Path $packageDir "scripts\*") (Join-Path $InstallDir "scripts\")
    Write-Info "scripts\ copiado"
}

foreach ($f in @("requirements.txt","README.md",".env.example")) {
    $src = Join-Path $packageDir $f
    if (Test-Path $src) { Copy-Item -Force $src (Join-Path $InstallDir $f) }
}

$modelsReadme = Join-Path $packageDir "models\LEEME.txt"
if (Test-Path $modelsReadme) { Copy-Item -Force $modelsReadme (Join-Path $InstallDir "models\LEEME.txt") }

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
#  PASO 5: Detectar GPU
# ═══════════════════════════════════════════════════════════
Write-Step 5 $totalSteps "Detectando GPU..."

$hasNvidia = $false
$gpuName = "No detectada"
$vramMB = 0
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
    Write-Info "GPU NVIDIA no detectada. Se usara llama.cpp en modo CPU."
}

# ═══════════════════════════════════════════════════════════
#  PASO 6: Descargar backends desde GitHub Releases
# ═══════════════════════════════════════════════════════════
Write-Step 6 $totalSteps "Descargando backends desde GitHub..."

Write-Host ""
Write-Host "  Se descargaran los backends necesarios desde GitHub Releases." -ForegroundColor White
Write-Host "  Esto puede tardar unos minutos segun tu conexion." -ForegroundColor DarkGray
Write-Host ""

$downloadBackends = Read-Host "  Descargar backends ahora? (S/N, Enter=S)"
$llamaDir = ""
$llamaOk = $false
$whisperOk = $false

if ($downloadBackends -in @("","S","s","Y","y")) {

    # -- Descargar llama.cpp --
    if ($hasNvidia) {
        Write-Host ""
        Write-Info "GPU NVIDIA detectada. Descargando version CUDA (cu12)..."
        $llamaDir = Join-Path $InstallDir "apps\llama.cpp-cuda"
        $llamaOk = Download-GithubRelease `
            -Repo "ggerganov/llama.cpp" `
            -IncludePattern "*bin-win-cuda-cu12*x64.zip" `
            -TargetDir $llamaDir `
            -Label "llama.cpp (CUDA cu12)"

        # Fallback a cualquier version CUDA
        if (-not $llamaOk) {
            Write-Info "Intentando cualquier version CUDA..."
            $llamaOk = Download-GithubRelease `
                -Repo "ggerganov/llama.cpp" `
                -IncludePattern "*bin-win-cuda*x64.zip" `
                -TargetDir $llamaDir `
                -Label "llama.cpp (CUDA)"
        }

        # Fallback a CPU
        if (-not $llamaOk) {
            Write-Info "CUDA no disponible, descargando version CPU..."
            $llamaDir = Join-Path $InstallDir "apps\llama.cpp"
            $llamaOk = Download-GithubRelease `
                -Repo "ggerganov/llama.cpp" `
                -IncludePattern "*bin-win*x64.zip" `
                -ExcludePattern "*cuda*" `
                -TargetDir $llamaDir `
                -Label "llama.cpp (CPU)"
        }
    } else {
        $llamaDir = Join-Path $InstallDir "apps\llama.cpp"
        $llamaOk = Download-GithubRelease `
            -Repo "ggerganov/llama.cpp" `
            -IncludePattern "*bin-win*x64.zip" `
            -ExcludePattern "*cuda*" `
            -TargetDir $llamaDir `
            -Label "llama.cpp (CPU)"
    }

    # -- Descargar whisper.cpp --
    $whisperDir = Join-Path $InstallDir "apps\whisper.cpp"
    $whisperOk = Download-GithubRelease `
        -Repo "ggerganov/whisper.cpp" `
        -IncludePattern "*bin-x64.zip" `
        -ExcludePattern "*cuda*" `
        -TargetDir $whisperDir `
        -Label "whisper.cpp"

    # Fallback: intentar otro patron
    if (-not $whisperOk) {
        $whisperOk = Download-GithubRelease `
            -Repo "ggerganov/whisper.cpp" `
            -IncludePattern "*bin-win*x64.zip" `
            -ExcludePattern "*cuda*" `
            -TargetDir $whisperDir `
            -Label "whisper.cpp"
    }

} else {
    Write-Info "Omitiendo descarga de backends."
    Write-Info "Descargalos manualmente:"
    Write-Info "  llama.cpp:   https://github.com/ggerganov/llama.cpp/releases"
    Write-Info "  whisper.cpp: https://github.com/ggerganov/whisper.cpp/releases"
}

# ═══════════════════════════════════════════════════════════
#  PASO 7: Configurar .env con rutas reales
# ═══════════════════════════════════════════════════════════
Write-Step 7 $totalSteps "Configurando .env..."

$envFile = Join-Path $InstallDir ".env"
$envExample = Join-Path $InstallDir ".env.example"

if (Test-Path $envFile) {
    Write-Info ".env ya existe, no se sobreescribe"
    Write-Info "Borralo y ejecuta el instalador de nuevo para regenerarlo"
} else {
    if (Test-Path $envExample) {
        $content = Get-Content $envExample -Raw
        $content = $content.Replace("__INSTALL_DIR__", $InstallDir)

        # Detectar ruta real de llama-server.exe
        if ($llamaDir -and (Test-Path $llamaDir)) {
            $llamaExe = Find-Exe $llamaDir "llama-server.exe"
            if ($llamaExe) {
                $genericLlama = Join-Path $InstallDir "apps\llama.cpp\llama-server.exe"
                $content = $content.Replace($genericLlama, $llamaExe)
                Write-Info "LLM backend: $llamaExe"
            }
        }

        # Detectar ruta real de whisper-server.exe
        $whisperSearchDir = Join-Path $InstallDir "apps\whisper.cpp"
        if (Test-Path $whisperSearchDir) {
            $whisperExe = Find-Exe $whisperSearchDir "whisper-server.exe"
            if (-not $whisperExe) {
                $whisperExe = Find-Exe $whisperSearchDir "server.exe"
            }
            if ($whisperExe) {
                $genericWhisper = Join-Path $InstallDir "apps\whisper.cpp\whisper-server.exe"
                $content = $content.Replace($genericWhisper, $whisperExe)
                Write-Info "Whisper backend: $whisperExe"
            }
        }

        $content | Out-File -Encoding utf8 $envFile -NoNewline
        Write-Ok ".env generado con rutas de $InstallDir"
    } else {
        Write-Warn ".env.example no encontrado, no se puede generar .env"
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 8: Descargar modelo Whisper (opcional)
# ═══════════════════════════════════════════════════════════
Write-Step 8 $totalSteps "Modelos de IA"

$modelsDir = Join-Path $InstallDir "models"
New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null

Write-Host ""
Write-Host "  Los modelos LLM (texto) se descargan desde la interfaz web /ui/models" -ForegroundColor DarkGray
Write-Host "  Para Whisper (audio), puedes descargar un modelo ahora." -ForegroundColor DarkGray
Write-Host ""

$existingWhisper = Get-ChildItem -Path $modelsDir -Filter "ggml-*.bin" -ErrorAction SilentlyContinue
if ($existingWhisper.Count -gt 0) {
    Write-Info "Ya hay $($existingWhisper.Count) modelo(s) Whisper en models\"
} else {
    $dlWhisper = Read-Host "  Descargar modelo Whisper ggml-medium.bin (~1.5 GB)? (S/N)"
    if ($dlWhisper -in @("S","s","Y","y")) {
        try {
            $modelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
            $modelPath = Join-Path $modelsDir "ggml-medium.bin"
            Write-Info "Descargando ggml-medium.bin (puede tardar varios minutos)..."
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $wc = New-Object System.Net.WebClient
            $wc.DownloadFile($modelUrl, $modelPath)
            Write-Ok "ggml-medium.bin descargado"
            # Actualizar .env con el nombre del modelo
            if (Test-Path $envFile) {
                $envContent = Get-Content $envFile -Raw
                if ($envContent -match "WHISPER_MODEL_NAME=\s*$") {
                    $envContent = $envContent.Replace("WHISPER_MODEL_NAME=", "WHISPER_MODEL_NAME=ggml-medium.bin")
                    $envContent | Out-File -Encoding utf8 $envFile -NoNewline
                }
            }
        } catch {
            Write-Warn "Error descargando modelo: $_"
            Write-Info "Descargalo manualmente desde https://huggingface.co/ggerganov/whisper.cpp"
        }
    }
}

# ═══════════════════════════════════════════════════════════
#  PASO 9: Verificacion final
# ═══════════════════════════════════════════════════════════
Write-Step 9 $totalSteps "Verificando instalacion..."

$checks = @(
    @{ Label = "app\main.py";              Path = Join-Path $InstallDir "app\main.py" },
    @{ Label = "requirements.txt";         Path = Join-Path $InstallDir "requirements.txt" },
    @{ Label = ".env";                     Path = Join-Path $InstallDir ".env" },
    @{ Label = "scripts\start_server.bat"; Path = Join-Path $InstallDir "scripts\start_server.bat" }
)

# Buscar llama-server.exe
$llamaCheck = Find-Exe (Join-Path $InstallDir "apps") "llama-server.exe"
if ($llamaCheck) {
    $checks += @{ Label = "llama-server.exe"; Path = $llamaCheck }
} else {
    $checks += @{ Label = "llama-server.exe"; Path = Join-Path $InstallDir "apps\llama.cpp\llama-server.exe" }
}

# Buscar whisper-server.exe
$whisperCheck = Find-Exe (Join-Path $InstallDir "apps") "whisper-server.exe"
if (-not $whisperCheck) { $whisperCheck = Find-Exe (Join-Path $InstallDir "apps") "server.exe" }
if ($whisperCheck) {
    $checks += @{ Label = "whisper-server.exe"; Path = $whisperCheck }
} else {
    $checks += @{ Label = "whisper-server.exe"; Path = Join-Path $InstallDir "apps\whisper.cpp\whisper-server.exe" }
}

$allOk = $true
foreach ($check in $checks) {
    if (Test-Path $check.Path) {
        Write-Host "        [OK]    $($check.Label)" -ForegroundColor Green
    } else {
        Write-Host "        [FALTA] $($check.Label)" -ForegroundColor DarkYellow
        $allOk = $false
    }
}

$ggufFiles = Get-ChildItem -Path $modelsDir -Filter "*.gguf" -ErrorAction SilentlyContinue
$binFiles  = Get-ChildItem -Path $modelsDir -Filter "*.bin" -ErrorAction SilentlyContinue
$modelCount = ($ggufFiles.Count + $binFiles.Count)
if ($modelCount -gt 0) {
    Write-Host "        [OK]    $modelCount modelo(s) en models\" -ForegroundColor Green
} else {
    Write-Host "        [INFO]  Sin modelos -- descargalos desde /ui/models" -ForegroundColor DarkYellow
}

# ═══════════════════════════════════════════════════════════
#  RESUMEN FINAL
# ═══════════════════════════════════════════════════════════
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
if ($allOk) {
    Write-Host "  Instalacion completada!" -ForegroundColor Green
} else {
    Write-Host "  Instalacion completada con advertencias" -ForegroundColor Yellow
    Write-Host "  (algunos componentes faltan, revisa arriba)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  Instalado en: $InstallDir" -ForegroundColor White
Write-Host ""
Write-Host "  Para iniciar:  $InstallDir\scripts\start_server.bat" -ForegroundColor Cyan
Write-Host "  Para detener:  $InstallDir\scripts\stop_server.bat" -ForegroundColor Cyan
Write-Host "  Interfaz web:  http://127.0.0.1:3112/ui/models" -ForegroundColor Cyan
Write-Host "  Estado:        http://127.0.0.1:3112/status" -ForegroundColor Cyan
Write-Host ""
if ($modelCount -eq 0) {
    Write-Host "  Siguiente paso:" -ForegroundColor White
    Write-Host "  1. Inicia el servidor con start_server.bat" -ForegroundColor DarkGray
    Write-Host "  2. Abre http://127.0.0.1:3112/ui/models en el navegador" -ForegroundColor DarkGray
    Write-Host "  3. Descarga un modelo LLM (ej: Qwen2.5-7B Q4_K_M)" -ForegroundColor DarkGray
    Write-Host "  4. Configura el nombre del modelo en .env" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# Preguntar si crear acceso directo
$createShortcut = Read-Host "Crear acceso directo en el Escritorio? (S/N)"
if ($createShortcut -in @("S","s","Y","y")) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shell = New-Object -ComObject WScript.Shell
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

# Crear INSTALAR.bat (doble clic friendly)
$batWrapper = @'
@echo off
title MeigaHub-server - Instalador
color 0B
echo.
echo   Iniciando instalador de MeigaHub-server...
echo   Los backends se descargaran automaticamente de GitHub.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer.ps1"
'@
$batWrapper | Out-File -Encoding ascii (Join-Path $distDir "INSTALAR.bat")

Write-Host "      OK (installer.ps1 + INSTALAR.bat)" -ForegroundColor Green

# ── 5. Resumen del paquete ──
Write-Host "[5/5] Calculando tamano..." -ForegroundColor Yellow
$sizeBytes = (Get-ChildItem -Recurse -Force $distDir | Measure-Object -Property Length -Sum).Sum
$sizeMB = [math]::Round($sizeBytes / 1MB, 1)

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Paquete creado: $distDir" -ForegroundColor White
Write-Host "  Tamano: $sizeMB MB (ligero, sin backends ni modelos)" -ForegroundColor White
Write-Host ""
Write-Host "  Contenido:" -ForegroundColor DarkGray
Write-Host "    app\            Codigo del servidor proxy" -ForegroundColor DarkGray
Write-Host "    scripts\        Scripts inicio/parada/test" -ForegroundColor DarkGray
Write-Host "    models\         (placeholder)" -ForegroundColor DarkGray
Write-Host "    .env.example    Plantilla de configuracion" -ForegroundColor DarkGray
Write-Host "    installer.ps1   Instalador con descarga automatica" -ForegroundColor DarkGray
Write-Host "    INSTALAR.bat    Doble clic para instalar" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  El instalador descargara automaticamente:" -ForegroundColor Cyan
Write-Host "    - llama.cpp (CPU o CUDA segun GPU)" -ForegroundColor Cyan
Write-Host "    - whisper.cpp" -ForegroundColor Cyan
Write-Host "    - Modelo Whisper (opcional)" -ForegroundColor Cyan
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

$compress = Read-Host "Comprimir en ZIP? (S/N)"
if ($compress -in @("S","s","Y","y")) {
    $zipPath = Join-Path $projectDir "dist\meigahub-server.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Write-Host "Comprimiendo..." -ForegroundColor Yellow
    Compress-Archive -Path "$distDir\*" -DestinationPath $zipPath -Force
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "ZIP creado: $zipPath - $($zipSize) MB" -ForegroundColor Green
}

Write-Host ""
