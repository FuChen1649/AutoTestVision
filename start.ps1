$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "========================================"
Write-Host "  AutoTestVision 一键启动"
Write-Host "========================================"
Write-Host ""

$PythonExe = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[错误] 后端环境未就绪，请先执行："
    Write-Host "  cd backend"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    Read-Host "按回车退出"
    exit 1
}

$NodeModules = Join-Path $Root "frontend\node_modules"
if (-not (Test-Path $NodeModules)) {
    Write-Host "[提示] 正在安装前端依赖..."
    Push-Location (Join-Path $Root "frontend")
    npm install
    Pop-Location
    Write-Host ""
}

Write-Host "[1/2] 启动后端  http://localhost:8000"
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
$backendCmd = 'cd /d "' + $Root + '\backend" & .venv\Scripts\python.exe run.py'
Start-Process cmd.exe -ArgumentList '/k', $backendCmd -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "[2/2] 启动前端  http://localhost:5173"
$frontendCmd = 'cd /d "' + $Root + '\frontend" & npm run dev'
Start-Process cmd.exe -ArgumentList '/k', $frontendCmd -WindowStyle Normal

Write-Host ""
Write-Host "前后端已在新窗口中启动。"
Write-Host "关闭对应窗口即可停止服务。"
Write-Host "3 秒后自动打开浏览器..."
Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
