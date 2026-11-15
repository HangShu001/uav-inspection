@echo off
chcp 936 >nul 2>&1
setlocal
title 车辆车牌巡检 - 本地启动

set "BACKEND=%~dp0app\uav-inspection-backend"
set "PY=%~dp0app\.venv-deploy\Scripts\python.exe"
if not exist "%PY%" set "PY=%BACKEND%\.venv\Scripts\python.exe"

echo ============================================
echo   车辆车牌巡检平台 - 本地启动
echo ============================================
echo.

if not exist "%PY%" (
    echo [错误] 找不到虚拟环境。
    echo        应为：%PY%
    echo        先在 app 目录执行 setup.bat（生成 .venv-deploy 与前端产物）
    echo.
    pause
    exit /b 1
)

rem 端口已在监听 -> 服务已起，只开页面不重复启动
netstat -ano | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 8002 已有服务在跑，直接打开页面。
    start "" "http://127.0.0.1:8002/plate"
    "%SystemRoot%\System32\timeout.exe" /t 2 >nul
    exit /b 0
)

echo [1/2] 启动后端 127.0.0.1:8002 ...
echo       这个窗口要一直开着，关掉等于停止服务。
echo.
cd /d "%BACKEND%"
start "uav-plate-backend" /min "%PY%" -m uvicorn heatmapapp.main:app --host 127.0.0.1 --port 8002

echo [2/2] 等服务就绪后自动打开页面 ...
set /a _try=0
:WAIT
set /a _try+=1
"%SystemRoot%\System32\timeout.exe" /t 2 >nul
netstat -ano | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto OPEN
if %_try% GEQ 20 goto TIMEOUT
goto WAIT

:OPEN
start "" "http://127.0.0.1:8002/plate"
echo.
echo 已打开 http://127.0.0.1:8002/plate
echo 登录：点「默认演示账号」后面的「登录」，或手填 admin / admin123
echo.
echo 停止服务：关掉任务栏里最小化的 uav-plate-backend 窗口。
"%SystemRoot%\System32\timeout.exe" /t 6 >nul
exit /b 0

:TIMEOUT
echo.
echo [警告] 等了 40 秒 8002 还没监听上。
echo        在 backend 目录手工跑一次看报错：
echo          cd /d "%BACKEND%"
echo          "%PY%" -m uvicorn heatmapapp.main:app --host 127.0.0.1 --port 8002
echo.
pause
exit /b 2
