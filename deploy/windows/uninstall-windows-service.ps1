param(
    [string]$TaskName = "AGY-Router-Gateway"
)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

$existing = Get-ScheduledTask -TaskName $TaskName
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Scheduled Task '$TaskName' dihentikan dan dihapus." -ForegroundColor Green
} else {
    Write-Host "Scheduled Task '$TaskName' tidak ditemukan." -ForegroundColor Yellow
}

# Stop running python run.py processes belonging to this repository
$procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($RepoDir) -and $_.CommandLine.Contains("run.py")
}
foreach ($p in $procs) {
    Stop-Process -Id $p.ProcessId -Force
    Write-Host "[OK] Proses background PID $($p.ProcessId) dihentikan." -ForegroundColor Green
}
