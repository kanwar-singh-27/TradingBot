# Open the Zerodha Kite login flow for manual authorization.
# Requires KITE_API_KEY and KITE_API_SECRET in the current environment or in .env.

$ErrorActionPreference = 'Stop'

function Load-DotEnv {
    param([string]$FilePath)

    if (-not (Test-Path $FilePath)) {
        return
    }

    foreach ($line in Get-Content $FilePath) {
        if ($line -match '^\s*#' -or $line -match '^\s*$') {
            continue
        }
        if ($line -match '^\s*([^#=]+?)\s*=\s*(.*)\s*$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            $envName = "env:" + $name
            if ($value -and -not (Get-Item -Path $envName -ErrorAction SilentlyContinue)) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Load-DotEnv -FilePath (Join-Path $repoRoot '.env')

$apiKey = $env:KITE_API_KEY
$apiSecret = $env:KITE_API_SECRET

if (-not $apiKey) {
    Write-Error 'KITE_API_KEY is missing. Set it in the environment or in .env before running this script.'
    exit 1
}

if (-not $apiSecret) {
    Write-Error 'KITE_API_SECRET is missing. Set it in the environment or in .env before running this script.'
    exit 1
}

$loginUrl = "https://kite.zerodha.com/connect/login?v=3&api_key=$([uri]::EscapeDataString($apiKey))"
Write-Host 'Opening Kite login in your default browser...' -ForegroundColor Cyan
Start-Process $loginUrl

Write-Host ''
Write-Host 'Authorize the app in the browser.' -ForegroundColor Green
Write-Host 'After the redirect, copy the request_token from the URL and set it in .env as:' -ForegroundColor Yellow
Write-Host '  KITE_REQUEST_TOKEN=your_request_token_here' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Then run:' -ForegroundColor Gray
Write-Host '  .\.venv\Scripts\python paper.py check --source kite' -ForegroundColor Gray
Write-Host 'or' -ForegroundColor Gray
Write-Host '  .\run-kite.ps1 -Command check' -ForegroundColor Gray
