$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Import-DotEnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
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

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $LogDir "daily-$stamp.log"

function Write-LogLine {
    param([string]$Line)
    if ($null -eq $Line) { return }
    Add-Content -LiteralPath $logFile -Value $Line -Encoding utf8
    Write-Output $Line
}

Write-LogLine "Runner started. Log: $logFile"

Import-DotEnvFile (Join-Path $Root ".env")
Import-DotEnvFile (Join-Path $env:LOCALAPPDATA "job-apply-secrets.env")

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONWARNINGS = "default"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  py -3 -m venv .venv
}
$Py = ".venv\Scripts\python.exe"

& $Py -m pip install -q -r requirements.txt 2>&1 | ForEach-Object { Write-LogLine $_ }

$exitCode = 0
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Py -u cloud_apply.py --headed --wait 90 --limit 80 2>&1 | ForEach-Object { Write-LogLine $_ }
    if ($LASTEXITCODE) { $exitCode = $LASTEXITCODE }
} finally {
    $ErrorActionPreference = $prevEap
}

Write-LogLine "Runner exiting with code $exitCode."
exit $exitCode
