$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonwExe = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$Launcher = Join-Path $ProjectDir 'launcher.pyw'

if (-not (Test-Path -LiteralPath $PythonwExe)) {
    throw 'Primero ejecuta scripts\install.ps1'
}

Start-Process -FilePath $PythonwExe -ArgumentList ('"' + $Launcher + '"') -WorkingDirectory $ProjectDir -WindowStyle Hidden
