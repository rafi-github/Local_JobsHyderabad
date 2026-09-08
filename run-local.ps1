$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

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

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3 -m venv .venv
}
$Py = ".venv\Scripts\python.exe"
& $Py -m pip install -r requirements.txt
& $Py -m playwright install chromium
& $Py cloud_apply.py --headed
