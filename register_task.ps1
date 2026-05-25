# ============================================================
# AmebloCookieRefresh - Task Scheduler registration (one-time)
#
# Registers three daily scheduled tasks at different times to
# maximize the chance of firing while the PC is on:
#   - Morning   09:00
#   - Afternoon 14:00
#   - Evening   20:00
# All invoke check_and_refresh.bat, which has a 1-day age guard
# so running multiple times per day is a safe no-op.
#
# Power-condition 4-set (per CLAUDE.md crypto-bot lessons,
# 2026-04-25 gambling-PJ outage incident):
#   - AllowStartIfOnBatteries (DisallowStartIfOnBatteries=$false)
#   - DontStopIfGoingOnBatteries (StopIfGoingOnBatteries=$false)
#   - WakeToRun=$true
#   - StartWhenAvailable=$true (catch up after sleep)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File register_task.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatchFile = Join-Path $ScriptDir "check_and_refresh.bat"
$PyFile    = Join-Path $ScriptDir "auto_refresh_cookies.py"

$Tasks = @(
    @{ Name = "AmebloCookieRefresh_Morning";   Time = "09:00" },
    @{ Name = "AmebloCookieRefresh_Afternoon"; Time = "14:00" },
    @{ Name = "AmebloCookieRefresh_Evening";   Time = "20:00" }
)

Write-Host "=== AmebloCookieRefresh Task Registration ===" -ForegroundColor Cyan
Write-Host "Script directory: $ScriptDir"
Write-Host "Batch file      : $BatchFile"
Write-Host ""

# --- preflight ---
if (-not (Test-Path $BatchFile)) {
    Write-Error "check_and_refresh.bat not found: $BatchFile"
    exit 1
}
if (-not (Test-Path $PyFile)) {
    Write-Error "auto_refresh_cookies.py not found: $PyFile"
    exit 1
}

# Common task settings - power-condition 4-set + execution policy
$CommonSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

foreach ($task in $Tasks) {
    $name = $task.Name
    $time = $task.Time
    Write-Host "-> Registering: $name (daily at $time)" -ForegroundColor Yellow

    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$BatchFile`"" `
        -WorkingDirectory $ScriptDir

    $trigger = New-ScheduledTaskTrigger -Daily -At $time

    # Unregister existing task with same name before re-registering
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }

    Register-ScheduledTask `
        -TaskName $name `
        -Action $action `
        -Trigger $trigger `
        -Settings $CommonSettings `
        -Principal $Principal `
        -Description "Ameba cookie sliding refresh (touches session daily to keep AT JWT alive)" | Out-Null
}

Write-Host ""
Write-Host "All 3 tasks registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Coverage: 09:00 / 14:00 / 20:00 daily." -ForegroundColor Cyan
Write-Host "Whichever fires first while PC is on and cookie is >=1 day old will refresh."
Write-Host ""
Write-Host "Verify with:"
foreach ($task in $Tasks) {
    Write-Host "  Get-ScheduledTask -TaskName $($task.Name) | Format-List TaskName,State"
}
Write-Host ""
Write-Host "Remove with:"
foreach ($task in $Tasks) {
    Write-Host "  Unregister-ScheduledTask -TaskName $($task.Name) -Confirm:`$false"
}
Write-Host ""
Write-Host "Log file: $ScriptDir\refresh.log"
