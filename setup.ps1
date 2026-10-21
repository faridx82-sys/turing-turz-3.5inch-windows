<#
.SYNOPSIS
    Installs the Turing 3.5" dashboard as an auto-start Windows service.

.DESCRIPTION
    - Installs the Python dependencies (pyserial, pillow, psutil)
    - Downloads NSSM (service wrapper) and LibreHardwareMonitor (CPU temperature)
    - Pauses the vendor "UsbMonitor" app / scheduled task
    - Registers the "TuringDashboard" service and starts it

    Run this script from an elevated PowerShell in the repository folder.

.EXAMPLE
    .\setup.ps1
#>
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = $PSScriptRoot
$serviceName = 'TuringDashboard'
$logDir = Join-Path $env:ProgramData 'TuringDashboard'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# ---------------------------------------------------------------- Python ----
Write-Step 'Checking Python'
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw 'Python 3.10+ was not found in PATH. Install it from https://www.python.org/ and enable "Add python.exe to PATH".'
}
$python = $pythonCmd.Source
Write-Host "    $python"

Write-Step 'Installing Python packages (pyserial, pillow, psutil)'
& $python -m pip install --upgrade pip | Out-Null
& $python -m pip install --upgrade pyserial pillow psutil
if ($LASTEXITCODE -ne 0) {
    throw 'pip install failed.'
}

# ------------------------------------------------------------------ NSSM ----
Write-Step 'Preparing NSSM'
$nssm = Join-Path $root 'nssm.exe'
if (-not (Test-Path $nssm)) {
    $zip = Join-Path $env:TEMP 'nssm-2.24.zip'
    $tmp = Join-Path $env:TEMP 'nssm-2.24'
    Invoke-WebRequest 'https://nssm.cc/release/nssm-2.24.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $tmp -Force
    Copy-Item (Join-Path $tmp 'nssm-2.24\win64\nssm.exe') $nssm -Force
}

# ------------------------------------------------- LibreHardwareMonitor -----
Write-Step 'Preparing LibreHardwareMonitor (CPU temperature library)'
$lhm = Join-Path $root 'lhm'
if (-not (Test-Path (Join-Path $lhm 'LibreHardwareMonitorLib.dll'))) {
    $zip = Join-Path $env:TEMP 'LibreHardwareMonitor.zip'
    Invoke-WebRequest 'https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest/download/LibreHardwareMonitor.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $lhm -Force
}

# ------------------------------------------------------- Vendor app pause ---
Write-Step 'Pausing the vendor UsbMonitor app'
Stop-Process -Name 'UsbMonitor' -Force -ErrorAction SilentlyContinue
$null = schtasks /Query /TN 'UsbMonitor' 2>$null
if ($LASTEXITCODE -eq 0) {
    schtasks /Change /TN 'UsbMonitor' /DISABLE | Out-Null
    Write-Host '    Scheduled task "UsbMonitor" disabled (uninstall.ps1 re-enables it).'
} else {
    Write-Host '    No "UsbMonitor" scheduled task found - skipping.'
}

# ---------------------------------------------------------------- Service ---
Write-Step 'Registering the service'
$script = Join-Path $root 'monitor_win.py'

& $nssm stop $serviceName 2>$null | Out-Null
& $nssm remove $serviceName confirm 2>$null | Out-Null

& $nssm install $serviceName $python
& $nssm set $serviceName AppParameters "`"$script`""
& $nssm set $serviceName AppDirectory $root
& $nssm set $serviceName DisplayName 'Turing 3.5" Dashboard'
& $nssm set $serviceName Description 'System monitor for Turing / TURZX 3.5" USB displays'
& $nssm set $serviceName Start SERVICE_AUTO_START
& $nssm set $serviceName ObjectName LocalSystem
& $nssm set $serviceName AppStdout (Join-Path $logDir 'stdout.log')
& $nssm set $serviceName AppStderr (Join-Path $logDir 'stderr.log')
& $nssm set $serviceName AppRotateFiles 1
& $nssm set $serviceName AppRotateBytes 1048576
& $nssm start $serviceName

Start-Sleep -Seconds 3
Write-Host ''
Write-Host "Service status : $((Get-Service $serviceName).Status)"
Write-Host "Log file       : $(Join-Path $logDir 'monitor.log')"
Write-Host 'Done. The panel should update within a few seconds.'
