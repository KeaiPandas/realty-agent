# Realty Agent 一键安装脚本
# 在新 Windows 上：右键 → 使用 PowerShell 运行，或在 PowerShell 中：
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Realty Agent 安装向导" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Python
Write-Host "[1/4] 检查 Python..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  ERROR: 未找到 Python，请先安装 Python 3.12+" -ForegroundColor Red
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Gray
    exit 1
}
$version = & python --version 2>&1
Write-Host "  OK: $version" -ForegroundColor Green

# 创建虚拟环境
Write-Host "[2/4] 创建虚拟环境..." -ForegroundColor Yellow
if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "  虚拟环境已存在，跳过" -ForegroundColor Gray
} else {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: 创建虚拟环境失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK: .venv 已创建" -ForegroundColor Green
}

# 升级 pip
Write-Host "[3/4] 升级 pip..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet 2>$null
Write-Host "  OK" -ForegroundColor Green

# 安装依赖
Write-Host "[4/4] 安装依赖..." -ForegroundColor Yellow
& .\.venv\Scripts\pip.exe install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  部分依赖安装失败，尝试逐个安装..." -ForegroundColor Yellow
    $pkgs = @(
        "langchain-core>=0.3", "langchain-openai>=0.3", "pydantic>=2.0", "pyyaml",
        "fastapi>=0.115", "uvicorn[standard]>=0.30", "apscheduler>=3.10", "httpx>=0.27",
        "psutil", "pycryptodome", "pymem", "pywin32", "pywinauto>=0.6.8", "Pillow>=10.0"
    )
    foreach ($pkg in $pkgs) {
        Write-Host "  安装 $pkg ..." -ForegroundColor Gray
        & .\.venv\Scripts\pip.exe install $pkg 2>$null
    }
}

# 检查关键包
Write-Host ""
Write-Host "检查安装结果..." -ForegroundColor Yellow
$ok = $true
foreach ($mod in @("fastapi", "uvicorn", "langchain_openai", "pydantic")) {
    $result = & .\.venv\Scripts\python.exe -c "import $mod; print('OK')" 2>&1
    if ($result -eq "OK") {
        Write-Host "  $mod OK" -ForegroundColor Green
    } else {
        Write-Host "  $mod FAILED" -ForegroundColor Red
        $ok = $false
    }
}

# 配置检查
Write-Host ""
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "已创建 .env 文件，请编辑配置后运行 start.ps1" -ForegroundColor Yellow
    } else {
        Write-Host "请创建 .env 文件并配置 LLM_API_KEY" -ForegroundColor Yellow
    }
} else {
    Write-Host ".env 已存在" -ForegroundColor Green
}

Write-Host ""
if ($ok) {
    Write-Host "======================================" -ForegroundColor Green
    Write-Host "  安装成功！运行以下命令启动：" -ForegroundColor Green
    Write-Host "  .\start.ps1" -ForegroundColor White
    Write-Host "======================================" -ForegroundColor Green
} else {
    Write-Host "======================================" -ForegroundColor Red
    Write-Host "  部分依赖安装失败，请检查上方错误" -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red
}
