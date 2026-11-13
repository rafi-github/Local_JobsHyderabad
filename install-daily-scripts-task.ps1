param(
  [string]$Time = "11:00",
  [string]$TaskName = "LocalJobsHyderabad-Daily-Scripts"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$Runner = Join-Path $Root "run-local.ps1"
if (-not (Test-Path $Runner)) {
  throw "run-local.ps1 not found at $Runner"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
  -WorkingDirectory $Root

# Interactive logon: same Chrome profile/CDP (9222) while the screen is locked.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -WakeToRun `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 12)

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered '$TaskName' daily at $Time (runs in your logon session when the PC is locked)."
Write-Host "Runner: $Runner"
