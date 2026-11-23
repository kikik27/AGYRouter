param(
    [string]$TaskName = "AGY-Router-Gateway"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$VbsPath = Join-Path $ScriptDir "start-hidden.vbs"
$VenvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VbsPath)) {
    throw "File tidak ditemukan: $VbsPath"
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Membuat .venv dan menginstall dependensi..." -ForegroundColor Cyan
    Set-Location $RepoDir
    python -m venv .venv
    & $VenvPython -m pip install -r (Join-Path $RepoDir "requirements.txt")
}

Write-Host "Mendaftarkan background task '$TaskName'..." -ForegroundColor Cyan

$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`"" -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "AGY Router Official Local AI Gateway (Open Source by kikik27)" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Menunggu server aktif di http://127.0.0.1:8000/health ..." -ForegroundColor Cyan
$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($resp.status) {
            $healthy = $true
            break
        }
    } catch {}
}

if ($healthy) {
    Write-Host "[OK] AGY Router berjalan di background dan otomatis start saat login!" -ForegroundColor Green
    Write-Host "Dashboard : http://127.0.0.1:8000/"
    Write-Host "Log file  : $RepoDir\logs\agy-router.log"
} else {
    Write-Warning "Task sudah terdaftar dan dijalankan, tetapi /health belum merespons dalam 10 detik. Cek log: $RepoDir\logs\agy-router.log"
}
