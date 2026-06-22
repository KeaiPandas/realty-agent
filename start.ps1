# Realty Agent 启动脚本
# 双击运行，或在 PowerShell 中: .\start.ps1

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "虚拟环境不存在，请先运行 setup.ps1" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host ""
Write-Host "Starting Realty Agent..." -ForegroundColor Cyan
Write-Host "  PC:  http://localhost:8000" -ForegroundColor White
Write-Host "  手机: http://<你的IP>:8000" -ForegroundColor White
Write-Host ""

& .\.venv\Scripts\python.exe -m uvicorn api.server:app --host 0.0.0.0 --port 8000
