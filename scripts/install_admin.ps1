param([switch]$Disable)

$ErrorActionPreference = 'Stop'
$ProjectDir = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$PythonwExe = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$Launcher = Join-Path $ProjectDir 'launcher.pyw'
$TaskName = 'Arfoxia Companion (Administrador)'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Ejecuta este instalador como administrador y acepta el aviso normal de UAC.'
}
if (-not (Test-Path -LiteralPath $PythonwExe) -or -not (Test-Path -LiteralPath $Launcher)) {
    throw 'No encuentro el entorno Python y el lanzador de este proyecto.'
}
$Arguments = '"' + $Launcher + '"'
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    $Actions = @($Existing.Actions)
    if ($Actions.Count -ne 1 -or $Actions[0].Execute -ne $PythonwExe -or $Actions[0].Arguments -ne $Arguments) {
        throw 'Hay una tarea con ese nombre que no pertenece a este proyecto; no la modificare.'
    }
}
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$Command = '"' + $PythonwExe + '" ' + $Arguments
if ($Disable) {
    if ($Existing) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    New-ItemProperty -Path $RunKey -Name 'GlaceonCompanion' -Value $Command -PropertyType String -Force | Out-Null
    Write-Output 'Inicio elevado retirado. Cambia run_as_administrator a false para volver al inicio normal.'
    exit 0
}
$Action = New-ScheduledTaskAction -Execute $PythonwExe -Argument $Arguments -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity.Name
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $TaskPrincipal -Settings $Settings -Description 'Arfoxia privada, elevada por peticion explicita del propietario; UAC permanece activo.'
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
# Remove only this application's matching startup value, never other startup apps.
$Previous = (Get-ItemProperty -Path $RunKey -Name 'GlaceonCompanion' -ErrorAction SilentlyContinue).GlaceonCompanion
if ($Previous -eq $Command) { Remove-ItemProperty -Path $RunKey -Name 'GlaceonCompanion' }
Write-Output 'Arfoxia configurada: inicio interactivo con privilegios elevados al iniciar sesion.'
