# setup.py
import os
import sys
import subprocess
import shutil
from pathlib import Path
from PIL import Image
import logging
import sqlite3
from datetime import datetime

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/setup.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def _shutdown_logging():
    """Close all log handlers to release file locks before running Inno Setup."""
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)

try:
    LANCZOS = Image.LANCZOS
except AttributeError:
    LANCZOS = Image.Resampling.LANCZOS

# Configuration
PYTHON_VERSION = "3.8.10"
PYTHON_CMD = os.environ.get("PYTHON_CMD")
INNO_SETUP_COMPILER = os.environ.get("INNO_SETUP_COMPILER", "iscc")
def get_python_cmd():
    """Resolve the Python 3.8 command to use for pip/pyinstaller."""
    if PYTHON_CMD:
        return PYTHON_CMD
    import sys
    if sys.version_info[:2] == (3, 8):
        return sys.executable
    import shutil
    for candidate in [f"py -{PYTHON_VERSION[:3]}", "python3.8", "python38"]:
        if shutil.which(candidate.split()[0]):
            return candidate
    raise RuntimeError(
        f"Python {PYTHON_VERSION} is required. "
        "Run with: py -3.8 setup.py  or  set PYTHON_CMD=python3.8"
    )

def check_python_version():
    """Verify the build is running under Python 3.8.x."""
    import sys
    if sys.version_info[:2] != (3, 8):
        print(f"WARNING: setup.py is running under Python {sys.version_info[:2]}, "
              f"but the project requires Python {PYTHON_VERSION}.")
        print("Attempting to re-launch with py -3.8...")
        import subprocess
        cmd = ["py", f"-{PYTHON_VERSION[:3]}"] + sys.argv
        sys.exit(subprocess.run(cmd).returncode)
PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
PACKAGES_DIR = PROJECT_ROOT / "packages"
VCREDIST_DIR = PROJECT_ROOT / "vcredist"
ICON_PNG = PROJECT_ROOT / "icons" / "login.png"
ICON_ICO = PROJECT_ROOT / "icons" / "login.ico"
ISS_FILE = PROJECT_ROOT / "setup.iss"
POST_INSTALL_BAT = PROJECT_ROOT / "post_install.bat"
LICENSE_FILE = PROJECT_ROOT / "license.txt"
README_FILE = PROJECT_ROOT / "readme.txt"
BANNER_IMAGE = PROJECT_ROOT / "installer_banner.bmp"
SMALL_IMAGE = PROJECT_ROOT / "installer_icon.bmp"
DB_PATH = PROJECT_ROOT / "database" / "ream_management.db"

def convert_png_to_ico():
    """Convert login.png to login.ico if it doesn't exist."""
    if not ICON_ICO.exists():
        if not ICON_PNG.exists():
            logger.error(f"{ICON_PNG} not found")
            raise FileNotFoundError(f"{ICON_PNG} not found")
        logger.info(f"Converting {ICON_PNG} to {ICON_ICO}")
        try:
            img = Image.open(ICON_PNG)
            img.save(ICON_ICO, format="ICO")
            logger.info("Icon conversion successful")
        except Exception as e:
            logger.error(f"Failed to convert icon: {e}")
            raise

def generate_installer_images():
    """Generate installer banner and small icon from login.png."""
    if not ICON_PNG.exists():
        logger.error(f"{ICON_PNG} not found")
        raise FileNotFoundError(f"{ICON_PNG} not found")
    
    if not BANNER_IMAGE.exists():
        logger.info(f"Generating {BANNER_IMAGE}")
        try:
            img = Image.open(ICON_PNG)
            img = img.resize((164, 314), LANCZOS)
            img.save(BANNER_IMAGE, format="BMP")
            logger.info("Installer banner generated")
        except Exception as e:
            logger.error(f"Failed to generate installer banner: {e}")
            raise
    
    if not SMALL_IMAGE.exists():
        logger.info(f"Generating {SMALL_IMAGE}")
        try:
            img = Image.open(ICON_PNG)
            img = img.resize((55, 55), LANCZOS)
            img.save(SMALL_IMAGE, format="BMP")
            logger.info("Installer small icon generated")
        except Exception as e:
            logger.error(f"Failed to generate installer small icon: {e}")
            raise

def generate_license_file():
    """Generate license.txt if it doesn't exist."""
    if not LICENSE_FILE.exists():
        content = """Ream Management System License Agreement

                This software is provided "as is" without warranty of any kind, express or implied.
                By installing this software, you agree to use it in accordance with applicable laws.
                For full terms, contact Your Organization at harryoginga@gmail.com.
                """
        try:
            with open(LICENSE_FILE, "w") as f:
                f.write(content)
            logger.info(f"Generated {LICENSE_FILE}")
        except Exception as e:
            logger.error(f"Failed to generate license.txt: {e}")
            raise

def generate_readme_file():
    """Generate readme.txt if it doesn't exist."""
    if not README_FILE.exists():
        content = """Ream Management System v1.0

                Thank you for choosing Ream Management System!
                This application helps manage ream allocations for educational institutions.
                Ensure you have administrative privileges to install this software.
                For support, visit https://example.com or contact support@example.com.
                """
        try:
            with open(README_FILE, "w") as f:
                f.write(content)
            logger.info(f"Generated {README_FILE}")
        except Exception as e:
            logger.error(f"Failed to generate readme.txt: {e}")
            raise

def prepare_offline_packages():
    """Install dependencies in the current environment and prepare VC++ redistributable."""
    VCREDIST_DIR.mkdir(exist_ok=True)
    logger.info(f"Ensured VC++ redistributable directory exists: {VCREDIST_DIR}")

    # Install requirements in the current environment (needed for PyInstaller bundling)
    requirements = PROJECT_ROOT / "requirements.txt"
    if not requirements.exists():
        logger.error(f"{requirements} not found")
        raise FileNotFoundError(f"{requirements} not found")

    python_cmd = get_python_cmd()
    pip_install = [python_cmd, "-m", "pip", "install", "-r", str(requirements)]
    try:
        subprocess.run(pip_install, check=True)
        logger.info("Installed dependencies from requirements.txt")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install dependencies: {e}")
        raise

    # Download VC++ Redistributable if not already present
    vcredist_path = VCREDIST_DIR / "vcredist_x64.exe"
    if not vcredist_path.exists():
        logger.info("Downloading Visual C++ Redistributable...")
        try:
            subprocess.run(
                ["powershell", "-Command",
                 f"Invoke-WebRequest -Uri 'https://aka.ms/vs/16/release/vc_redist.x64.exe' "
                 f"-OutFile '{vcredist_path}' -UseBasicParsing"],
                check=True
            )
            logger.info(f"Downloaded VC++ Redistributable to {vcredist_path}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to download VC++ Redistributable: {e}. "
                           "post_install.bat will attempt download at install time.")

def generate_post_install_bat():
    """Generate post_install.bat for setting up runtime environment."""
    content = f"""@echo off
setlocal enabledelayedexpansion

echo Setting up runtime environment...

cd "%~dp0"

:: ============================================================
:: Check and install Visual C++ Redistributable (required for Python native modules)
:: ============================================================
echo Checking for Visual C++ Redistributable...

reg query "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Version >nul 2>&1
if %errorlevel% neq 0 (
    reg query "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Visual C++ Redistributable not found.

        if exist "vcredist\\vcredist_x64.exe" (
            echo Installing VC++ Redistributable from local package...
            vcredist\\vcredist_x64.exe /install /quiet /norestart
            timeout /t 10 /nobreak >nul
        ) else (
            echo Downloading Visual C++ Redistributable...
            powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/16/release/vc_redist.x64.exe' -OutFile 'vcredist\\vcredist_x64.exe' -UseBasicParsing"
            if exist "vcredist\\vcredist_x64.exe" (
                echo Installing VC++ Redistributable...
                vcredist\\vcredist_x64.exe /install /quiet /norestart
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
:: Detect Python {PYTHON_VERSION}
:: ============================================================
echo Checking for Python {PYTHON_VERSION}...

python --version 2>nul | findstr /C:"{PYTHON_VERSION}" >nul
if %errorlevel% equ 0 (
    echo Python {PYTHON_VERSION} detected.
    echo Installing dependencies from requirements.txt...
    python -m pip install -r requirements.txt
    if %errorlevel% equ 0 (
        echo Dependencies installed successfully.
    ) else (
        echo WARNING: Failed to install some dependencies.
    )
) else (
    py -3.8 --version 2>nul | findstr /C:"{PYTHON_VERSION}" >nul
    if %errorlevel% equ 0 (
        echo Python {PYTHON_VERSION} detected via py launcher.
        echo Installing dependencies from requirements.txt...
        py -3.8 -m pip install -r requirements.txt
        if %errorlevel% equ 0 (
            echo Dependencies installed successfully.
        ) else (
            echo WARNING: Failed to install some dependencies.
        )
    ) else (
        echo Python {PYTHON_VERSION} not found on this system.
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
"""
    try:
        with open(POST_INSTALL_BAT, "w") as f:
            f.write(content)
        logger.info(f"Generated {POST_INSTALL_BAT}")
    except Exception as e:
        logger.error(f"Failed to generate post_install.bat: {e}")
        raise


def run_pyinstaller():
    """Run PyInstaller to create ReamManagement.exe."""
    python_cmd = get_python_cmd()
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        logger.info(f"Cleared existing {DIST_DIR}")
    DIST_DIR.mkdir(exist_ok=True)

    # Ensure PyInstaller is available in the target Python environment
    logger.info("Ensuring PyInstaller is installed...")
    subprocess.run([python_cmd, "-m", "pip", "install", "pyinstaller==5.13.2"], check=True)

    cmd = [
        python_cmd, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        f"--add-data=config;config",
        f"--add-data=database;database",
        f"--add-data=gui;gui",
        f"--add-data=icons;icons",
        f"--add-data=logs;logs",
        f"--add-data=modules;modules",
        f"--add-data=reports;reports",
        f"--add-data=requirements.txt;.",
        f"--icon={ICON_ICO}",
        "--name", "ReamManagement",
        "main.py"
    ]
    if os.name != 'nt':
        cmd = [arg.replace(';', ':') for arg in cmd]
    logger.info("Running PyInstaller")
    try:
        subprocess.run(cmd, check=True)
        logger.info("PyInstaller build successful")
    except subprocess.CalledProcessError as e:
        logger.error(f"PyInstaller failed: {e}")
        raise

def run_inno_setup():
    """Compile the Inno Setup script."""
    if not ISS_FILE.exists():
        logger.error(f"{ISS_FILE} not found")
        raise FileNotFoundError(f"{ISS_FILE} not found")
    logger.info(f"Compiling {ISS_FILE} with Inno Setup")
    try:
        subprocess.run([INNO_SETUP_COMPILER, str(ISS_FILE)], check=True)
        logger.info("Inno Setup compilation successful")
    except FileNotFoundError:
        logger.error(
            f"Inno Setup compiler '{INNO_SETUP_COMPILER}' not found. "
            "Install Inno Setup from https://jrsoftware.org/isinfo.php and add it to PATH, "
            "or set INNO_SETUP_COMPILER environment variable."
        )
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Inno Setup compilation failed: {e}")
        raise

def main():
    """Main function to orchestrate the build process."""
    try:
        check_python_version()
        # Step 1: Generate license and readme files
        generate_license_file()
        generate_readme_file()

        # Step 2: Convert icon and generate installer images
        convert_png_to_ico()
        generate_installer_images()

        # Step 3: Prepare offline packages
        prepare_offline_packages()

        # Step 4: Initialize database
        if not DB_PATH.parent.exists():
            DB_PATH.parent.mkdir(exist_ok=True)

        # Step 5: Generate post_install.bat
        generate_post_install_bat()

        # Step 6: Run PyInstaller
        run_pyinstaller()

        # Step 7: Run Inno Setup
        _shutdown_logging()
        run_inno_setup()

        logger.info("Build process completed successfully")
        print(f"Installer created at: {DIST_DIR / 'ReamManagementSetup.exe'}")
    except Exception as e:
        logger.error(f"Build process failed: {e}")
        raise

if __name__ == "__main__":
    main()
