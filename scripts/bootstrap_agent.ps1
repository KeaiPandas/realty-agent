param(
    [switch]$RunTests,
    [switch]$StartServer
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $root ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
$envExample = Join-Path $root ".env.example"
$envFile = Join-Path $root ".env"

Write-Host "[1/6] Checking Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not installed or not in PATH."
}

Write-Host "[2/6] Creating virtual environment if needed..."
if (-not (Test-Path $pythonExe)) {
    python -m venv $venvDir
}

Write-Host "[3/6] Installing Python dependencies..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r (Join-Path $root "requirements.txt")

Write-Host "[4/6] Installing wxauto backend..."
& $pythonExe -m pip install "git+https://github.com/cluic/wxauto.git"

Write-Host "[5/6] Preparing local files..."
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
}

foreach ($dir in @("data", "decrypted", "logs")) {
    $path = Join-Path $root $dir
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

Write-Host "[6/6] Summary"
Write-Host "Virtualenv: $venvDir"
Write-Host "Python: $pythonExe"
Write-Host "Env file: $envFile"
Write-Host ""
Write-Host "Next manual step:"
Write-Host "  1. Fill LLM_API_KEY in .env"
Write-Host "  2. Confirm WeChat is logged in"
Write-Host "  3. Start API: .\.venv\Scripts\python.exe -m uvicorn api.server:app --host 127.0.0.1 --port 8000"

if ($RunTests) {
    Write-Host ""
    Write-Host "[extra] Running bot tests..."
    & $pythonExe -m pytest (Join-Path $root "tests\test_bot.py") -q
}

if ($StartServer) {
    Write-Host ""
    Write-Host "[extra] Starting API server..."
    Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $root `
        -WindowStyle Hidden
    Write-Host "Server started at http://127.0.0.1:8000"
}
