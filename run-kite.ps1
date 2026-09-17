# Zerodha Kite Paper Trading Runner
# Loads environment variables from .env and runs paper.py

param(
    [float]$DurationMinutes = 30,
    [float]$PollSeconds = 1,
    [string]$OutputDir = "runtime/kite",
    [string]$Command = "run",
    [string]$RequestToken = "",
    [switch]$OpenBrowser
)

Set-Location $PSScriptRoot

# Load .env file
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env file not found at $envFile" -ForegroundColor Red
    Write-Host "Copy .env.example to .env and fill in your Kite credentials" -ForegroundColor Yellow
    exit 1
}

Write-Host "Loading credentials from .env..." -ForegroundColor Cyan
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([^#=]+)\s*=\s*(.*)\s*$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        if ($value) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
            Write-Host "  ✓ $name" -ForegroundColor Green
        }
    }
}

if ($RequestToken) {
    [Environment]::SetEnvironmentVariable("KITE_REQUEST_TOKEN", $RequestToken, "Process")
    Write-Host "  ✓ KITE_REQUEST_TOKEN supplied via command-line argument" -ForegroundColor Green
}

if (-not $env:KITE_API_KEY) {
    Write-Host "ERROR: KITE_API_KEY is missing from .env" -ForegroundColor Red
    exit 1
}

if (-not $env:KITE_API_SECRET) {
    Write-Host "ERROR: KITE_API_SECRET is missing from .env" -ForegroundColor Red
    exit 1
}

if (-not $env:KITE_REQUEST_TOKEN) {
    $loginUrl = "https://kite.zerodha.com/connect/login?v=3&api_key=$([uri]::EscapeDataString($env:KITE_API_KEY))"
    if ($OpenBrowser) {
        Start-Process $loginUrl
    }
    Write-Host "`nKite request token is missing." -ForegroundColor Yellow
    Write-Host "Open this URL in your browser and authorize the app:" -ForegroundColor Yellow
    Write-Host $loginUrl -ForegroundColor Cyan
    Write-Host "`nAfter login, copy the request_token from the redirect URL and either:" -ForegroundColor Yellow
    Write-Host "  1) paste it into .env as KITE_REQUEST_TOKEN, or" -ForegroundColor Yellow
    Write-Host "  2) rerun this script with -RequestToken <token>." -ForegroundColor Yellow
    Write-Host "`nThe access token is exchanged at runtime in memory and is never persisted to disk." -ForegroundColor Gray
    exit 2
}

Write-Host "`nStarting Kite paper trading session..." -ForegroundColor Cyan
Write-Host "Duration: $DurationMinutes minutes | Poll: $PollSeconds seconds | Output: $OutputDir`n" -ForegroundColor Gray

# Activate virtual environment and run paper.py
& ".\.venv\Scripts\Activate.ps1"

if ($Command -eq "check") {
    python paper.py check --source kite
} else {
    python paper.py run --source kite `
        --duration-minutes $DurationMinutes `
        --poll-seconds $PollSeconds `
        --output $OutputDir
}

Write-Host "`nSession finished." -ForegroundColor Cyan
