[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$name = 'JLPT iPad Reader (Private LAN)'
$ruleParameters = [ordered]@{
    DisplayName   = $name
    Direction     = 'Inbound'
    Action        = 'Allow'
    Protocol      = 'TCP'
    LocalPort     = $Port
    Profile       = 'Private'
    RemoteAddress = 'LocalSubnet'
}

# Preview is deliberately resolved before privilege checks or firewall cmdlets.
# Automated tests can therefore inspect the exact splatted rule without UAC or
# any contact with the real Windows Firewall service.
if ($WhatIfPreference) {
    [pscustomobject]$ruleParameters | ConvertTo-Json -Compress
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Port $Port"
    try {
        $process = Start-Process `
            -FilePath 'powershell.exe' `
            -Verb RunAs `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        exit $process.ExitCode
    }
    catch {
        Write-Error "防火墙配置未完成（UAC 可能已取消）：$($_.Exception.Message)"
        exit 1
    }
}

if ($PSCmdlet.ShouldProcess($name, "configure TCP port $Port for Private LocalSubnet")) {
    Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    New-NetFirewallRule @ruleParameters | Out-Null
}
