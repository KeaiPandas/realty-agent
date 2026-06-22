param(
    [string]$WeChatPath = "",
    [switch]$SkipPatch
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$pythonExe = if (Test-Path $venvPython) { $venvPython } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
$patchScript = Join-Path $PSScriptRoot "wechat_39_login_patch.py"

function Resolve-WeChatPath {
    param([string]$UserPath)

    if ($UserPath -and (Test-Path $UserPath)) {
        return (Resolve-Path $UserPath).Path
    }

    $candidates = @(
        "C:\Program Files\Tencent\WeChat\WeChat.exe",
        "C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
        "D:\Program Files\Tencent\WeChat\WeChat.exe",
        "D:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
        "$env:LOCALAPPDATA\Tencent\WeChat\WeChat.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    return $null
}

$resolvedWeChat = Resolve-WeChatPath -UserPath $WeChatPath
if (-not $resolvedWeChat) {
    throw "Unable to find WeChat.exe automatically. Re-run with -WeChatPath <full path>."
}

Write-Host "[1/3] Launching WeChat 3.9 from $resolvedWeChat"
if (-not (Get-Process WeChat -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $resolvedWeChat
    Start-Sleep -Seconds 3
} else {
    Write-Host "WeChat.exe is already running."
}

if ($SkipPatch) {
    Write-Host "[2/3] Patch skipped by request."
    Write-Host "[3/3] Leave WeChat on the login page and patch it later with:"
    Write-Host "        $pythonExe $patchScript"
    exit 0
}

if (-not $pythonExe) {
    throw "Python was not found. Install Python or activate the project's virtual environment first."
}

Write-Host "[2/3] Running login patch helper"
& $pythonExe $patchScript

Write-Host "[3/3] After the patch, follow the console instructions to finish login."
