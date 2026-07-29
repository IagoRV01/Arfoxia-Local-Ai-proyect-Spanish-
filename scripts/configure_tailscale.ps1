param([switch]$Install)

$ErrorActionPreference = 'Stop'
$InstalledExe = 'C:\Program Files\Tailscale\tailscale.exe'
$TailscaleExe = (Get-Command tailscale -ErrorAction SilentlyContinue).Source

if (-not $TailscaleExe -and (Test-Path -LiteralPath $InstalledExe)) {
    $TailscaleExe = $InstalledExe
}

if (-not $TailscaleExe) {
    if (-not $Install) {
        throw 'Tailscale no está instalado. Repite con -Install o instálalo manualmente.'
    }
    & winget install --id Tailscale.Tailscale --exact --accept-package-agreements --accept-source-agreements
    if (Test-Path -LiteralPath $InstalledExe) {
        $TailscaleExe = $InstalledExe
    }
    else {
        throw 'La instalación no terminó. Aprueba el instalador de Tailscale y repite este script.'
    }
}

& $TailscaleExe status
& $TailscaleExe serve --bg 8742
& $TailscaleExe serve status

Write-Host 'Instala Tailscale en el iPhone, inicia sesión en la misma red y usa Emparejar iPhone desde la mascota.'
