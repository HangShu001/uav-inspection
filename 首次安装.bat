@echo off
chcp 936 >nul 2>&1
setlocal
title 车辆车牌巡检 - 首次安装
cd /d "%~dp0app"

echo ============================================
echo   车辆车牌巡检 - 首次安装（只需做一次）
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 python 命令。
    echo        请先装 Python 3.12（安装时勾选 Add python.exe to PATH），
    echo        装完关掉所有命令行窗口再双击本文件。
    echo.
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<(3,14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [错误] Python 版本不对，需要 3.10 ~ 3.13。
    python --version
    echo.
    pause
    exit /b 1
)

echo 正在安装运行环境（约 100 MB，需要联网，几分钟）
echo   默认走阿里云镜像，国内更快；连不上的话会自动退回官方 PyPI。
echo.
set "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "PIP_TRUSTED_HOST=mirrors.aliyun.com"
set "PIP_NO_CACHE_DIR=1"
python deploy.py install --backend-only
if errorlevel 1 (
    echo.
    echo [提示] 阿里云镜像没装上，改用官方 PyPI 重试...
    echo.
    set "PIP_INDEX_URL=https://pypi.org/simple/"
    set "PIP_TRUSTED_HOST=pypi.org"
    python deploy.py install --backend-only
    if errorlevel 1 (
        echo.
        echo [失败] 两个源都没装上。请把上面的报错整段发回给发送者。
        echo        也可手工重试（复制这一整行，在 app 目录里执行）：
        echo        .venv-deploy\Scripts\python.exe -m pip install -r uav-inspection-backend\requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/
        pause
        exit /b 1
    )
)

echo.
echo ============================================
echo   安装完成
echo ============================================
echo   下一步：双击 打开车牌巡检.bat 启动
echo   想做真检测，再双击 安装推理依赖.bat（约 300 MB）
echo.
pause
exit /b 0
