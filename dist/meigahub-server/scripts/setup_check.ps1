param(
    [string]$EnvPath = ""
)

if (-not $EnvPath) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $projectDir = Split-Path -Parent $scriptDir
    $EnvPath = Join-Path $projectDir ".env"
}

function Test-Required($Label, $Path) {
    if (Test-Path $Path) {
        Write-Host "[OK] ${Label}: $Path"
        return $true
    }
    Write-Host "[FALTA] ${Label}: $Path"
    return $false
}

$ok = $true

if (!(Test-Path $EnvPath)) {
    Write-Host "[FALTA] .env no encontrado: $EnvPath"
    exit 1
}

$envContent = Get-Content $EnvPath -ErrorAction Stop
$envMap = @{}
foreach ($line in $envContent) {
    if ($line.Trim().StartsWith("#") -or $line.Trim().Length -eq 0) { continue }
    $parts = $line.Split("=", 2)
    if ($parts.Count -eq 2) { $envMap[$parts[0].Trim()] = $parts[1].Trim() }
}

$llamaExe = $envMap["LLM_START_COMMAND"]
$whisperExe = $envMap["WHISPER_START_COMMAND"]
$llmModel = $envMap["LLM_MODEL_NAME"]
$whisperModel = $envMap["WHISPER_MODEL_NAME"]
$modelsDir = $envMap["MODELS_DIR"]

if ($llamaExe) {
    $llamaPath = ($llamaExe -split " ")[0]
    $ok = (Test-Required "llama-server.exe" $llamaPath) -and $ok
}
if ($whisperExe) {
    $whisperPath = ($whisperExe -split " ")[0]
    $ok = (Test-Required "whisper-server.exe" $whisperPath) -and $ok
}
if ($modelsDir) {
    $ok = (Test-Required "MODELS_DIR" $modelsDir) -and $ok
}
if ($modelsDir -and $llmModel) {
    $ok = (Test-Required "LLM_MODEL" (Join-Path $modelsDir $llmModel)) -and $ok
}
if ($modelsDir -and $whisperModel) {
    $ok = (Test-Required "WHISPER_MODEL" (Join-Path $modelsDir $whisperModel)) -and $ok
}

if ($ok) {
    Write-Host "\nTodo OK. El proyecto es portable con esta configuracion."
    exit 0
}

Write-Host "\nFaltan dependencias o rutas. Corrige .env o copia los archivos." 
exit 2
