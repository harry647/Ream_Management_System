@echo off
setlocal enabledelayedexpansion

echo Setting up runtime environment...

cd "%~dp0"

:: ============================================================
:: Check and install Visual C++ Redistributable (required for Python native modules)
:: ============================================================
echo Checking for Visual C++ Redistributable...

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Version >nul 2>&1
if %errorlevel% neq 0 (
    reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Visual C++ Redistributable not found.

        if exist "vcredist\vcredist_x64.exe" (
            echo Installing VC++ Redistributable from local package...
            vcredist\vcredist_x64.exe /install /quiet /norestart
            timeout /t 10 /nobreak >nul
        ) else (
            echo Downloading Visual C++ Redistributable...
            powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/16/release/vc_redist.x64.exe' -OutFile 'vcredist\vcredist_x64.exe' -UseBasicParsing"
            if exist "vcredist\vcredist_x64.exe" (
                echo Installing VC++ Redistributable...
                vcredist\vcredist_x64.exe /install /quiet /norestart
                timeout /t 10 /nobreak >nul
            ) else (
                echo WARNING: Failed to download VC++ Redistributable.
                echo The application may require Microsoft Visual C++ Redistributable.
                echo Download manually from: https://aka.ms/vs/16/release/vc_redist.x64.exe
            )
        )
    ) else (
        echo Visual C++ Redistributable already installed.
    )
) else (
    echo Visual C++ Redistributable already installed.
)

:: ============================================================
:: Detect Python 3.8.10
:: ============================================================
echo Checking for Python 3.8.10...

python --version 2>nul | findstr /C:"3.8.10" >nul
if %errorlevel% equ 0 (
    echo Python 3.8.10 detected.
    echo Installing dependencies from requirements.txt...
    python -m pip install -r requirements.txt
    if %errorlevel% equ 0 (
        echo Dependencies installed successfully.
    ) else (
        echo WARNING: Failed to install some dependencies.
    )
) else (
    py -3.8 --version 2>nul | findstr /C:"3.8.10" >nul
    if %errorlevel% equ 0 (
        echo Python 3.8.10 detected via py launcher.
        echo Installing dependencies from requirements.txt...
        py -3.8 -m pip install -r requirements.txt
        if %errorlevel% equ 0 (
            echo Dependencies installed successfully.
        ) else (
            echo WARNING: Failed to install some dependencies.
        )
    ) else (
        echo Python 3.8.10 not found on this system.
        echo The standalone executable (ReamManagement.exe) will be used instead.
    )
)

echo.
echo ============================================================
echo Setup complete!
echo.
echo IMPORTANT: If the application fails to start, please install:
echo   Microsoft Visual C++ Redistributable from:
echo   https://aka.ms/vs/16/release/vc_redist.x64.exe
echo ============================================================
echo.

exit /b 0
