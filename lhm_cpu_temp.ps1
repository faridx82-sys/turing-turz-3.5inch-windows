# Reads the CPU package temperature through LibreHardwareMonitor's library.
# Prints a single number (degrees Celsius) or nothing on failure.
$ErrorActionPreference = 'Stop'
$dir = Join-Path $PSScriptRoot 'lhm'
Set-Location $dir
try {
    Add-Type -Path (Join-Path $dir 'LibreHardwareMonitorLib.dll')
    $c = New-Object LibreHardwareMonitor.Hardware.Computer
    $c.IsCpuEnabled = $true
    $c.Open()
    try {
        $preferred = $null
        $fallback = $null
        foreach ($h in $c.Hardware) {
            if ("$($h.HardwareType)" -ne 'Cpu') { continue }
            $h.Update()
            foreach ($s in $h.Sensors) {
                if ("$($s.SensorType)" -eq 'Temperature' -and $null -ne $s.Value) {
                    if ($null -eq $fallback) { $fallback = $s.Value }
                    if ($s.Name -match 'Tctl|Package') { $preferred = $s.Value; break }
                }
            }
            if ($null -ne $preferred) { break }
        }
        $v = if ($null -ne $preferred) { $preferred } else { $fallback }
        if ($null -ne $v) { [math]::Round([double]$v, 1) }
    } finally {
        $c.Close()
    }
} catch {
    exit 1
}
