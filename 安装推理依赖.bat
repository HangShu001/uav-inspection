@echo off
chcp 936 >nul 2>&1
setlocal
title 车辆车牌巡检 - 安装推理依赖（可选）
cd /d "%~dp0app"

echo ============================================
echo   安装 AI 推理依赖（可选，约 300 MB）
echo ============================================
echo.
echo 不装也能启动，也能看「巡检结果 / 过程回放 / 覆盖质量」三个页签，
echo 只是「实时检测」会返回 503。
echo.

if not exist "%~dp0app\.venv-deploy\Scripts\python.exe" (
    echo [错误] 还没做首次安装。请先双击 首次安装.bat。
    echo.
    pause
    exit /b 1
)

echo 开始下载并安装（国内网络可能十几分钟）
echo   Torch 走 PyTorch 官方 CPU 源，其余走阿里云镜像。
echo.
set "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "PIP_TRUSTED_HOST=mirrors.aliyun.com"
set "PIP_NO_CACHE_DIR=1"
python deploy.py install --backend-only --inference
if errorlevel 1 (
    echo.
    echo [失败] 没装上。可以按顺序手工试，两行各自是一整行，都在 app 目录执行：
    echo   1) .venv-deploy\Scripts\python.exe -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu
    echo   2) .venv-deploy\Scripts\python.exe -m pip install -r uav-inspection-backend\requirements-inference.txt --index-url https://mirrors.aliyun.com/pypi/simple/
    pause
    exit /b 1
)

echo.
echo 安装完成，可以双击 打开车牌巡检.bat 做真检测了。
echo.
pause
exit /b 0
