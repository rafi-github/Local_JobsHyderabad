# Local daily apply: Python + Playwright only. Never calls Cursor agent CLI.
$ErrorActionPreference = "Stop"

function Add-NativeOutput {
  param($Item)
  if ($null -eq $Item) { return }
  $text = if ($Item -is [System.Management.Automation.ErrorRecord]) { $Item.ToString() } else { [string]$Item }
  foreach ($line in ($text -split "`r?`n", -1)) {
    if ($script:logFile) { Add-Content -LiteralPath $script:logFile -Value $line -Encoding utf8 }
    Write-Host $line
  }
}
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$env:CLOUD_APPLY_CDP_PORT = "9223"
$rc = 1
$logFile = $null
function Write-RunLog([string]$Message) {
  $stamp = Get-Date -Format "HH:mm:ss"
  $line = "[$stamp] $Message"
  if ($script:logFile) { Add-Content -LiteralPath $script:logFile -Value $line -Encoding utf8 }
  Write-Host $Message
}
try {
  Set-Location $Root
  $logDir = Join-Path $Root "data\logs"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $logFile = Join-Path $logDir ("daily-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
  New-Item -ItemType File -Force -Path $logFile | Out-Null
  Write-RunLog "Runner started. Log: $logFile"

  $envFiles = @(
    (Join-Path $Root ".env"),
    (Join-Path $Root "data\.secrets.env"),
    (Join-Path $Root "job-apply-secrets.env"),
    (Join-Path $Root "data\job-apply-secrets.env"),
    (Join-Path $env:USERPROFILE ".job-apply-secrets.env"),
    (Join-Path $env:LOCALAPPDATA "job-apply-secrets.env")
  )
  foreach ($envPath in $envFiles) {
    if (-not (Test-Path -LiteralPath $envPath)) { continue }
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
      $trim = ($line -as [string]).Trim()
      if (-not $trim -or $trim.StartsWith("#")) { continue }
      if ($trim.StartsWith("export ")) { $trim = $trim.Substring(7).Trim() }
      $eq = $trim.IndexOf("=")
      if ($eq -lt 1) { continue }
      $name = $trim.Substring(0, $eq).Trim()
      $val = $trim.Substring($eq + 1).Trim().Trim('"').Trim("'")
      if (-not $name -or -not $val) { continue }
      if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
        Set-Item -Path "Env:$name" -Value $val
      }
    }
  }

  $chromeCandidates = @(
    $env:CHROME_BIN,
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  ) | Where-Object { $_ -and (Test-Path $_) }

  if (-not $chromeCandidates) {
    throw "Chrome was not found. Set CHROME_BIN to chrome.exe."
  }
  $env:CHROME_BIN = $chromeCandidates[0]

  if (-not (Test-Path $Py)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Py)) {
      throw "Could not create the Python environment (exit $LASTEXITCODE)."
    }
  }

  & $Py -c "import playwright.sync_api, selenium, tzdata"
  if ($LASTEXITCODE -ne 0) {
    & $Py -m pip install -q -r requirements.txt *>&1 | ForEach-Object {
      $_ | Out-String -Stream | ForEach-Object { Add-Content -LiteralPath $logFile -Value $_ -Encoding utf8; $_ }
    }
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit $LASTEXITCODE)." }
  }

  # Keep blocked forms short so one dead-end does not consume the daily batch.
  # Continue (not Stop) while Python runs. Python 3.15 prints ResourceWarning
  # and Chrome/Playwright notes on stderr. With Stop, the first stderr line
  # aborts this script and cloud_apply dies before it submits anything.
  $ErrorActionPreference = "Continue"
  & $Py -u cloud_apply.py --headed --wait 90 --limit 80 2>&1 | ForEach-Object { Add-NativeOutput $_ }
  $rc = $LASTEXITCODE
  $ErrorActionPreference = "Stop"
  if ($rc -ne 0) { Write-RunLog "Apply runner exited with code $rc." }
} catch {
  Write-RunLog "Daily apply setup/run failed: $_"
  $rc = 1
} finally {
  # Run this even when Chrome/Python/dependency setup fails. The notifier skips
  # duplicate messages sent in the last 10 minutes.
  try {
    if (Test-Path $Py) {
      $ErrorActionPreference = "Continue"
      & $Py -u notify_daily_email.py --allow-start-chrome 2>&1 | ForEach-Object { Add-NativeOutput $_ }
      $ErrorActionPreference = "Stop"
      if ($LASTEXITCODE -ne 0) {
        Write-RunLog "Daily results email failed (exit $LASTEXITCODE)."
        if ($rc -eq 0) { $rc = $LASTEXITCODE }
      }
    } else {
      Write-RunLog "Could not send the daily results email: Python environment is unavailable."
    }
  } catch {
    Write-RunLog "Daily results email failed: $_"
    $rc = 1
  }
  try { Write-RunLog "Runner exiting with code $rc." } catch { }
}
exit $rc
