# setup.py
import os
import subprocess
import shutil
from pathlib import Path
from PIL import Image
import logging
import venv
import site
import sqlite3
from datetime import datetime
import bcrypt

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

# Configuration
PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_ZIP = "python-embed.zip"
INNO_SETUP_COMPILER = os.environ.get("INNO_SETUP_COMPILER", "iscc")  # Use 'iscc' on PATH or set INNO_SETUP_COMPILER environment variable
PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
PACKAGES_DIR = PROJECT_ROOT / "packages"
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
            img = img.resize((164, 314), Image.LANCZOS)
            img.save(BANNER_IMAGE, format="BMP")
            logger.info("Installer banner generated")
        except Exception as e:
            logger.error(f"Failed to generate installer banner: {e}")
            raise
    
    if not SMALL_IMAGE.exists():
        logger.info(f"Generating {SMALL_IMAGE}")
        try:
            img = Image.open(ICON_PNG)
            img = img.resize((55, 55), Image.LANCZOS)
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
    """Create a virtual environment, install dependencies, and copy to packages directory."""
    if PACKAGES_DIR.exists():
        shutil.rmtree(PACKAGES_DIR)
        logger.info(f"Cleared existing {PACKAGES_DIR}")
    PACKAGES_DIR.mkdir(exist_ok=True)

    # Create a temporary virtual environment
    temp_venv = PROJECT_ROOT / "temp_venv"
    logger.info(f"Creating temporary virtual environment at {temp_venv}")
    try:
        venv.create(temp_venv, with_pip=True)
        logger.info("Temporary virtual environment created")
    except Exception as e:
        logger.error(f"Failed to create virtual environment: {e}")
        raise

    # Install dependencies in the virtual environment
    venv_python = temp_venv / "Scripts" / "python.exe" if os.name == 'nt' else temp_venv / "bin" / "python"
    venv_pip = [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"]
    try:
        subprocess.run(venv_pip, check=True)
        logger.info("Upgraded pip in virtual environment")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to upgrade pip: {e}")
        raise

    # Install requirements
    requirements = PROJECT_ROOT / "requirements.txt"
    if not requirements.exists():
        logger.error(f"{requirements} not found")
        raise FileNotFoundError(f"{requirements} not found")
    
    venv_install = [str(venv_python), "-m", "pip", "install", "-r", str(requirements)]
    try:
        subprocess.run(venv_install, check=True)
        logger.info("Installed dependencies in virtual environment")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install dependencies: {e}")
        raise

    # Copy site-packages to packages directory
    venv_site_packages = temp_venv / "Lib" / "site-packages" if os.name == 'nt' else Path(site.getsitepackages()[0])
    try:
        shutil.copytree(venv_site_packages, PACKAGES_DIR, dirs_exist_ok=True)
        logger.info(f"Copied site-packages to {PACKAGES_DIR}")
    except Exception as e:
        logger.error(f"Failed to copy site-packages: {e}")
        raise
    finally:
        shutil.rmtree(temp_venv, ignore_errors=True)
        logger.info(f"Removed temporary virtual environment {temp_venv}")

def generate_post_install_bat():
    """Generate post_install.bat for setting up Python environment."""
    content = f"""@echo off
setlocal enabledelayedexpansion

echo Setting up Python environment...

cd "%~dp0"

:: ============================================================
:: Check and install Visual C++ Redistributable (required for Python native modules)
:: ============================================================
echo Checking for Visual C++ Redistributable...

:: Check if VC++ Redistributable is already installed (check registry)
reg query "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Version >nul 2>&1
if %errorlevel% neq 0 (
    reg query "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Visual C++ Redistributable not found. Installing...
        
        :: Try to download and install VC++ Redistributable
        :: Note: For offline installation, include VC++ Redistributable installer in packages folder
        if exist "packages\\vcredist_x64.exe" (
            echo Installing VC++ Redistributable from local package...
            packages\\vcredist_x64.exe /install /quiet /norestart
            timeout /t 10 /nobreak >nul
        ) else (
            echo WARNING: VC++ Redistributable not found in packages folder.
            echo The application may require Microsoft Visual C++ Redistributable.
            echo Download from: https://aka.ms/vs/17/release/vc_redist.x64.exe
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
echo [Defaults] > python\\python{PYTHON_VERSION.replace('.', '')}._pth
echo python{PYTHON_VERSION.replace('.', '')}.zip >> python\\python{PYTHON_VERSION.replace('.', '')}._pth
echo . >> python\\python{PYTHON_VERSION.replace('.', '')}._pth
echo import site >> python\\python{PYTHON_VERSION.replace('.', '')}._pth

echo.
echo ============================================================
echo Setup complete!
echo.
echo IMPORTANT: If the application fails to start, please install:
echo   Microsoft Visual C++ Redistributable from:
echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
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
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
        logger.info(f"Cleared existing {DIST_DIR}")
    DIST_DIR.mkdir(exist_ok=True)

    cmd = [
        "pyinstaller",
        "--noconfirm",
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
    except subprocess.CalledProcessError as e:
        logger.error(f"Inno Setup compilation failed: {e}")
        raise

def main():
    """Main function to orchestrate the build process."""
    try:
        # Step 1: Generate license and readme files
        generate_license_file()
        generate_readme_file()

        # Step 2: Convert icon and generate installer images
        convert_png_to_ico()
        generate_installer_images()

        # Step 3: Prepare offline packages
        prepare_offline_packages()

        # Step 4: Verify Python embeddable exists
        if not (PROJECT_ROOT / PYTHON_EMBED_ZIP).exists():
            logger.error(f"{PYTHON_EMBED_ZIP} not found in project root. Please download python-{PYTHON_VERSION}-embed-amd64.zip and place it in the project root.")
            raise FileNotFoundError(f"{PYTHON_EMBED_ZIP} not found")

        # Step 5: Initialize database
        if not DB_PATH.parent.exists():
            DB_PATH.parent.mkdir(exist_ok=True)

        # Step 6: Generate post_install.bat
        generate_post_install_bat()

        # Step 7: Run PyInstaller
        run_pyinstaller()

        # Step 8: Run Inno Setup
        run_inno_setup()

        logger.info("Build process completed successfully")
        print(f"Installer created at: {DIST_DIR / 'ReamManagementSetup.exe'}")
    except Exception as e:
        logger.error(f"Build process failed: {e}")
        raise

if __name__ == "__main__":
    main()
