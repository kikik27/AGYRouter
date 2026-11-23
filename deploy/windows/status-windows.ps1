param(
    [string]$TaskName = "AGY-Router-Gateway"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$LogFile = Join-Path $RepoDir "logs\agy-router.log"

Write-Host "=== Status Scheduled Task ===" -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task  : $TaskName"
    Write-Host "State : $($task.State)"
    Write-Host "Last Run : $($info.LastRunTime)"
} else {
    Write-Host "Task '$TaskName' belum terpasang." -ForegroundColor Yellow
}

Write-Host "`n=== Health Check ===" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
    Write-Host ($health | ConvertTo-Json -Compress) -ForegroundColor Green
} catch {
    Write-Host "Server tidak merespons di http://127.0.0.1:8000/health" -ForegroundColor Red
}

if (Test-Path $LogFile) {
    Write-Host "`n=== 25 Baris Terakhir Log ===" -ForegroundColor Cyan
    Get-Content $LogFile -Tail 25
}
