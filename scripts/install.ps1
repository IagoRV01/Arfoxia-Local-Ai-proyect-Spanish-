param(
    [switch]$PullModel,
    [switch]$PullPowerModel,
    [switch]$EnableStartup,
    [switch]$SkipAssets
)

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectDir '.venv'
$PythonExe = Join-Path $VenvDir 'Scripts\python.exe'
$PythonwExe = Join-Path $VenvDir 'Scripts\pythonw.exe'
$Launcher = Join-Path $ProjectDir 'launcher.pyw'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    & py -3.13 -m venv $VenvDir
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e "$ProjectDir[dev]"
if (-not $SkipAssets) {
    & $PythonExe (Join-Path $PSScriptRoot 'fetch_assets.py')
    & $PythonExe (Join-Path $PSScriptRoot 'validate_assets.py')
}

if ($PullModel) {
    & ollama pull qwen3.5:4b
    & ollama pull qwen3.5:9b-q4_K_M
}

if ($PullPowerModel) {
    & ollama pull qwen3.6:27b-q4_K_M
}

if ($EnableStartup) {
    $Command = '"' + $PythonwExe + '" "' + $Launcher + '"'
    New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'GlaceonCompanion' -Value $Command -PropertyType String -Force | Out-Null
}

Write-Host "Instalación terminada. Inicia con: $PythonExe -m glaceon_companion.app"
