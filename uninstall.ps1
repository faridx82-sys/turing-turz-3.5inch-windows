<#
.SYNOPSIS
    Removes the Turing dashboard service and re-enables the vendor app.

.DESCRIPTION
    - Stops and deletes the "TuringDashboard" service
    - Re-enables the vendor "UsbMonitor" scheduled task (if it exists)

    The Python packages and the downloaded lhm/ folder are left in place.

.EXAMPLE
    .\uninstall.ps1
#>
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'
$serviceName = 'TuringDashboard'
$nssm = Join-Path $PSScriptRoot 'nssm.exe'

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

Write-Step "Stopping and removing service '$serviceName'"
if (Test-Path $nssm) {
    & $nssm stop $serviceName 2>$null | Out-Null
    & $nssm remove $serviceName confirm 2>$null | Out-Null
} else {
    sc.exe stop $serviceName 2>$null | Out-Null
    sc.exe delete $serviceName 2>$null | Out-Null
}

Write-Step 'Re-enabling the vendor UsbMonitor task'
$null = schtasks /Query /TN 'UsbMonitor' 2>$null
if ($LASTEXITCODE -eq 0) {
    schtasks /Change /TN 'UsbMonitor' /ENABLE | Out-Null
    Write-Host '    Vendor task "UsbMonitor" enabled.'
} else {
    Write-Host '    No "UsbMonitor" task found - nothing to re-enable.'
}

Write-Host ''
Write-Host 'Done. You can start the vendor app again (UsbMonitor.exe) if you want it driving the panel.'
