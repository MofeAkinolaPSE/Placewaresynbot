# install_task.ps1 — Register the Placeware invoice bridge as a Windows
# Scheduled Task: starts at logon/boot, restarts automatically on failure.
# Deliberately NOT a Windows Service — Task Scheduler needs no service
# wrapper, no admin install headaches, just this script.
#
# Run as Administrator on the target Windows 7 server, from the folder
# containing placeware_bridge.exe + bridge_config.ini.

param(
    [string]$TaskName = "PlacewareInvoiceBridge",
    [string]$ExePath  = "$PSScriptRoot\placeware_bridge.exe"
)

if (-not (Test-Path $ExePath)) {
    Write-Error "placeware_bridge.exe not found at $ExePath — build it first with build_exe.bat"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $ExePath -Argument "--config `"$PSScriptRoot\bridge_config.ini`"" -WorkingDirectory $PSScriptRoot
$trigger1 = New-ScheduledTaskTrigger -AtStartup
$trigger2 = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger @($trigger1, $trigger2) `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "Registered scheduled task '$TaskName'. Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Write-Host "Done. Check $PSScriptRoot\bridge.log for output."
Write-Host "To stop:      Stop-ScheduledTask -TaskName $TaskName"
Write-Host "To uninstall: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
