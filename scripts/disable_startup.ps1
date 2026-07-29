$ErrorActionPreference = 'Stop'
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'GlaceonCompanion' -ErrorAction SilentlyContinue
Write-Host 'Inicio automático desactivado. Los datos y la aplicación no se han borrado.'
