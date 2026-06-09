@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   AutoTestVision 一键启动
echo ========================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
    echo [错误] 后端环境未就绪，请先执行：
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [提示] 正在安装前端依赖...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [错误] npm install 失败
        popd
        pause
        exit /b 1
    )
    popd
    echo.
)

echo [1/2] 启动后端  http://localhost:8099
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8099" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
start "AutoTestVision-Backend" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe run.py"

timeout /t 2 /nobreak >nul

echo [2/2] 启动前端  http://localhost:5179
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5179" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
start "AutoTestVision-Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo 前后端已在新窗口中启动。
echo 关闭对应窗口即可停止服务。
echo 3 秒后自动打开浏览器...
timeout /t 3 /nobreak >nul
start "" http://localhost:5179

exit
