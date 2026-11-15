@echo off
chcp 65001 >nul
setlocal
title 车辆车牌巡检 - 本地启动
cd /d "%~dp0app\uav-inspection-backend"

echo ============================================
echo   车辆车牌巡检平台 - 本地启动
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到 .venv 虚拟环境。
    echo        应为：%~dp0app\uav-inspection-backend\.venv\Scripts\python.exe
    echo        先在 app 目录执行 setup.bat 或手工建 venv 并装 requirements.txt。
    echo.
    pause
    exit /b 1
)

rem 端口已在监听 -> 说明服务已起，直接打开页面即可，不重复启动
netstat -ano | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 8002 端口已有服务在跑，直接打开页面。
    start "" "http://127.0.0.1:8002/plate"
    timeout /t 2 >nul
    exit /b 0
)

echo [1/2] 启动后端（127.0.0.1:8002）...
echo       这个窗口要一直开着，关掉就等于停止服务。
echo.
start "uav-plate-backend" /min ".venv\Scripts\python.exe" -m uvicorn heatmapapp.main:app --host 127.0.0.1 --port 8002

echo [2/2] 等服务就绪后自动打开页面...
set /a _try=0
:WAIT
set /a _try+=1
timeout /t 2 >nul
netstat -ano | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto OPEN
if %_try% GEQ 20 goto TIMEOUT
goto WAIT

:OPEN
start "" "http://127.0.0.1:8002/plate"
echo.
echo 已打开 http://127.0.0.1:8002/plate
echo 登录：页面上点「默认演示账号」后面的「登录」，或手填 admin / admin123
echo.
echo 停止服务：关掉任务栏里最小化的 uav-plate-backend 窗口。
timeout /t 6 >nul
exit /b 0

:TIMEOUT
echo.
echo [警告] 等了 40 秒 8002 还没监听上。看最小化的 uav-plate-backend 窗口里报了什么。
echo        常见原因：依赖没装全（先跑 setup.bat）、端口被别的程序占用。
echo.
pause
exit /b 2
