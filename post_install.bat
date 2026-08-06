@echo off
setlocal enabledelayedexpansion

echo Setting up Python environment...

cd "%~dp0"

:: ============================================================
:: Check and install Visual C++ Redistributable (required for Python native modules)
:: ============================================================
echo Checking for Visual C++ Redistributable...

:: Check if VC++ Redistributable is already installed (check registry)
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Version >nul 2>&1
if %errorlevel% neq 0 (
    reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Visual C++ Redistributable not found. Installing...
        
        :: Try to download and install VC++ Redistributable
        :: Note: For offline installation, include VC++ Redistributable installer in vcredist folder
        if exist "vcredist\vcredist_x64.exe" (
            echo Installing VC++ Redistributable from local package...
            vcredist\vcredist_x64.exe /install /quiet /norestart
            timeout /t 10 /nobreak >nul
        ) else (
            echo WARNING: VC++ Redistributable not found in vcredist folder.
            echo The application may require Microsoft Visual C++ Redistributable.
            echo Download from: https://aka.ms/vs/16/release/vc_redist.x64.exe
        )
    ) else (
    echo Visual C++ Redistributable already installed.
)

:: ============================================================
:: Extract Python embeddable
:: ============================================================
echo Extracting Python environment...
powershell -Command "Expand-Archive -Path 'python-embed.zip' -DestinationPath 'python' -Force"

:: Update python.ini to enable site-packages
echo [Defaults] > python\python3119._pth
echo python3119.zip >> python\python3119._pth
echo . >> python\python3119._pth
echo import site >> python\python3119._pth

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
