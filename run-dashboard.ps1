$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

$python = 'python'
$venvPath = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    & $python -m venv $venvPath
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
& $venvPython -m streamlit run (Join-Path $PSScriptRoot 'dashboard.py') --server.address 127.0.0.1 --server.port 8501
