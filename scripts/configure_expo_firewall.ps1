[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateRange(1, 65535)][int]$Port = 8081,
    [string]$NodeExe = '',
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'
$RuleName = "Arfoxia-Expo-Tailscale-TCP-$Port"
$RuleGroup = 'Arfoxia private mobile development'
$Principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Ejecuta este script como administrador mediante el aviso normal de UAC.'
}
$Existing = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
if ($Existing -and $Existing.Group -ne $RuleGroup) {
    throw 'Ya existe una regla con este nombre que no pertenece a Arfoxia; no se modificara.'
}
if ($Disable) {
    if ($Existing -and $PSCmdlet.ShouldProcess($RuleName, 'Remove only the Arfoxia Expo rule')) {
        Remove-NetFirewallRule -Name $RuleName
    }
    return
}
if (-not (Get-NetAdapter -Name 'Tailscale' -ErrorAction SilentlyContinue)) {
    throw 'No se encuentra la interfaz Tailscale. Instala/conecta Tailscale primero.'
}
if (-not $NodeExe) {
    $NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
}
$NodeExe = (Resolve-Path -LiteralPath $NodeExe -ErrorAction Stop).Path
if ([IO.Path]::GetFileName($NodeExe) -ine 'node.exe') {
    throw 'La regla debe apuntar al ejecutable node.exe utilizado por Expo.'
}
$Parameters = @{
    Name = $RuleName
    DisplayName = "Arfoxia Expo - Tailscale private TCP $Port"
    Group = $RuleGroup
    Description = 'Expo Go over the Tailscale interface only. No LAN/public interface access.'
    Enabled = 'True'
    Direction = 'Inbound'
    Action = 'Allow'
    Profile = 'Any'
    Program = $NodeExe
    Protocol = 'TCP'
    LocalPort = $Port
    InterfaceAlias = 'Tailscale'
    RemoteAddress = @('100.64.0.0/10', 'fd7a:115c:a1e0::/48')
    EdgeTraversalPolicy = 'Block'
}
if ($PSCmdlet.ShouldProcess("$NodeExe TCP $Port on Tailscale only", 'Configure private Expo access')) {
    if ($Existing) {
        $Parameters.NewDisplayName = $Parameters.DisplayName
        $Parameters.Remove('DisplayName')
        $Parameters.Remove('Group')
        Set-NetFirewallRule @Parameters | Out-Null
    } else {
        New-NetFirewallRule @Parameters | Out-Null
    }
    Write-Output "Expo permitido solo por Tailscale en TCP $Port. El firewall permanece activo."
}
