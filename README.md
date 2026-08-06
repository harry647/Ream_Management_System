# Ream Management System

A desktop application for managing ream (paper) allocations in educational institutions. It tracks student ream contributions, stock purchases, departmental issues, and generates detailed reports — all through an intuitive, modern GUI.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)

---

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running from Source](#running-from-source)
- [Usage Guide](#usage-guide)
  - [Step 1: Update Ream Requirements](#step-1-update-ream-requirements-admin-only)
  - [Step 2: Upload Students](#step-2-upload-students-adminstaff)
  - [Step 3: Upload Reams Brought](#step-3-upload-reams-brought-adminstaff)
  - [Step 4: View Reports](#step-4-view-reports)
- [Roles & Permissions](#roles--permissions)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Building the Installer](#building-the-installer)
- [Docker](#docker)
- [Database & Backups](#database--backups)
- [Logging](#logging)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- **Student Management** — Add, edit, delete, search, and bulk-import students from Excel.
- **Ream Tracking** — Record reams brought by students, purchases from suppliers, and issues to departments.
- **Cumulative Logic** — Automatically computes cumulative ream targets per form (e.g., Form 1 → 2, Form 2 → 4, Form 3 → 6, Form 4 → 8).
- **Reports** — Defaulters, class summaries, stock summaries, term summaries, surplus reports, and more. Export to **PDF** and **CSV**.
- **Role-Based Access** — `admin`, `staff`, and `viewer` roles with granular permissions.
- **Auto-Promotion** — Scheduled year-end student promotion (configurable via `config.json`).
- **Audit Logging** — Every action is recorded for accountability.
- **Stock Alerts** — Low-stock warnings when ream inventory falls below a threshold.
- **Theming** — Dark/light appearance modes with customizable color themes.
- **Backup & Restore** — One-click database backup and restore.

---

## Getting Started

### Prerequisites

- **Python 3.8+** (3.8 recommended for building the installer)
- **pip** (Python package manager)
- **Microsoft Visual C++ Redistributable** (Windows, for native modules)

### Installation

#### Option A: Standalone Installer (Windows)

1. Download the latest `ReamManagementSetup.exe` from the [Releases](../../releases) page.
2. Run the installer and follow the on-screen instructions.
3. The installer automatically checks for and installs the Visual C++ Redistributable if needed.
4. Launch **Ream Management System** from the Start Menu or desktop shortcut.

#### Option B: Run from Source

1. Clone the repository:

   ```bash
   git clone https://github.com/harry647/Ream_Management_System.git
   cd Ream_Management_System
   ```

2. Create and activate a virtual environment (recommended):

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/macOS
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set the admin password (required on first run):

   ```bash
   # Windows (PowerShell)
   $env:ADMIN_PASSWORD="YourSecurePassword"
   # Linux/macOS
   export ADMIN_PASSWORD="YourSecurePassword"
   ```

5. Run the application:

   ```bash
   python main.py
   ```

> **Note:** On first launch, the application creates the SQLite database, config files, and an `admin` user with the password provided via the `ADMIN_PASSWORD` environment variable.

---

## Usage Guide

Follow these steps **in order** to ensure accurate data and avoid errors.

### Step 1: Update Ream Requirements (Admin Only)

Before importing students or reams, set how many reams each form must bring.

1. Go to **Settings** tab.
2. Find the section **"Reams Required Per Form"**.
3. Enter values for each form (e.g., Form 1: 2, Form 2: 2, ... Grade 12: 2).
4. Click **Save Settings**.

This sets **cumulative targets**:

| Form     | Cumulative Target |
|----------|-------------------|
| Form 1   | 2                 |
| Form 2   | 4 (2+2)           |
| Form 3   | 6 (2+2+2)         |
| Form 4   | 8 (2+2+2+2)       |

### Step 2: Upload Students (Admin/Staff)

Use an Excel template with **exact** column names:

| Admission No | Name       | Form   | Stream | Total Required |
|--------------|------------|--------|--------|----------------|
| 4523         | John Doe   | Form 1 | A      |                |
| 4338         | Jane Smith | Form 2 | B      |                |

Rules:
- `Total Required` is **optional** — the app uses the cumulative value from Settings.
- Only the first 4 columns are required.
- `Admission No` must be unique.
- `Form` must match: `Form 1`, `Form 2`, ..., `Grade 12`.

1. Go to **Students** tab.
2. Click **Import Students from Excel**.
3. Select your file and wait for the success message.

### Step 3: Upload Reams Brought (Admin/Staff)

Use an Excel template:

| Admission No | Quantity | Date Brought |
|--------------|----------|--------------|
| 4523         | 1        | 2025-03-25   |
| 4338         | 2        | 2025-03-26   |

Rules:
- Date format: `YYYY-MM-DD`.
- Quantity must be greater than 0.
- Admission No must exist in Students.
- Term is auto-detected (Jan–Apr = Term 1, etc.).

1. Go to **Reams** tab.
2. Click **Import Reams from Excel**.
3. Select your file — a progress bar shows live status.

If any Admission No is missing:
- Import continues.
- A PDF report of missing students is generated.
- You choose where to save it, and it auto-opens.

### Step 4: View Reports

Go to the **Reports** tab:

- **Defaulters** — Students who brought fewer reams than required.
- **Class Summary** — Percentage achieved per form.
- **Stock Summary** — Purchased vs. Issued vs. Brought.
- **Term Summary** — Contributions per term.
- **Surplus Report** — Students who brought more than required.

All reports use **cumulative logic** and can be exported to PDF or CSV.

---

## Roles & Permissions

| Role    | Permissions                                                                 |
|---------|-----------------------------------------------------------------------------|
| **Admin**  | Full access — manage users, settings, students, reams, issues, reports, backups. |
| **Staff**  | Manage students, reams, issues, and view reports. Cannot manage users or settings. |
| **Viewer** | Read-only access to records and reports.                                     |

---

## Project Structure

```
Ream_Management_System/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── setup.py                   # Build script (PyInstaller + Inno Setup)
├── setup.iss                  # Inno Setup installer script
├── ReamManagement.spec        # PyInstaller spec file
├── Dockerfile                 # Container definition
├── docker-compose.yml         # Docker Compose configuration
├── config/
│   ├── config.json            # Main application configuration
│   ├── theme.json             # UI theme settings
│   ├── report_config.json     # Report configuration
│   └── report_config_schema.json
├── database/
│   └── ream_management.db     # SQLite database (auto-created)
├── gui/
│   ├── main_window.py         # Main window / navigation
│   ├── students_tab.py        # Student management UI
│   ├── reams_tab.py           # Ream tracking UI
│   ├── issues_tab.py          # Department issue UI
│   ├── reports_tab.py         # Reports UI
│   ├── settings.py            # Settings UI
│   ├── user_tab.py            # User management UI
│   └── utils.py               # Shared GUI utilities
├── modules/
│   ├── db_setup.py            # Database init, connection pool, migrations
│   ├── student_manager.py     # Student business logic
│   ├── ream_manager.py        # Ream tracking business logic
│   ├── issue_manager.py       # Department issue business logic
│   ├── report_manager.py      # Report generation logic
│   ├── user_manager.py        # Authentication & user management
│   └── ream_insert.py         # Sample data import
├── reports/
│   └── report_export.py       # PDF/CSV export helpers
├── icons/                     # Application icons
├── logs/                      # Log files (auto-created)
└── vcredist/                  # VC++ Redistributable for installer
```

---

## Configuration

The main configuration file is `config/config.json`:

```json
{
    "database_path": "database/ream_management.db",
    "ui_theme": {
        "appearance_mode": "dark",
        "color_theme": "blue"
    },
    "logging": {
        "level": "INFO",
        "file": "logs/main.log",
        "console": true
    },
    "features": {
        "undo_enabled": false,
        "sample_data_enabled": true,
        "auto_promotion_enabled": true,
        "auto_promotion_schedule": {
            "month": 12,
            "day": 31,
            "hour": 23,
            "minute": 55
        }
    }
}
```

### Environment Variables

| Variable          | Description                                                       |
|-------------------|-------------------------------------------------------------------|
| `ADMIN_PASSWORD`  | Password for the default `admin` user (required on first run).    |
| `DATABASE_PATH`   | Override the database file location.                              |
| `LOGS_PATH`       | Override the logs directory.                                      |
| `CONFIG_PATH`     | Override the config directory.                                    |
| `PYTHON_CMD`      | Python command used by `setup.py` (e.g., `py -3.8`).              |
| `INNO_SETUP_COMPILER` | Path to the Inno Setup compiler (`iscc`).                     |

---

## Building the Installer

To build a standalone Windows installer:

1. Install **Python 3.8** and **Inno Setup 6** (add `iscc` to PATH).
2. Run the build script:

   ```bash
   py -3.8 setup.py
   ```

   Or set the Python command explicitly:

   ```bash
   set PYTHON_CMD=python3.8
   python setup.py
   ```

The build process:
1. Generates license/readme files and installer images.
2. Installs dependencies and downloads the VC++ Redistributable.
3. Runs **PyInstaller** to create `ReamManagement.exe`.
4. Compiles the **Inno Setup** installer to `dist/ReamManagementSetup.exe`.

---

## Docker

A `Dockerfile` and `docker-compose.yml` are provided for containerized environments.

> **Note:** This is a GUI application. Running it in Docker requires X11 forwarding or a virtual framebuffer (Xvfb). For headless/server use, consider adding a web API layer.

```bash
docker build -t ream-management .
docker run --rm -e ADMIN_PASSWORD="YourSecurePassword" ream-management
```

---

## Database & Backups

- The application uses **SQLite** (`database/ream_management.db`).
- The database is auto-created and migrated on first launch.
- Use **Settings → Backup** to create a backup, and **Settings → Restore** to restore one.
- **Never edit the database directly** while the application is running.

---

## Logging

Logs are written to the `logs/` directory:

- `main.log` — Application startup, config, and scheduler events.
- `reams_tab.log` — Ream import and tracking operations.

Log level and console output can be configured in `config/config.json`.

---

## Troubleshooting

| Issue                                        | Solution                                                                 |
|----------------------------------------------|--------------------------------------------------------------------------|
| Application fails to start                   | Install the Microsoft Visual C++ Redistributable.                        |
| `ADMIN_PASSWORD` not set                     | Set the environment variable before first launch.                        |
| Excel import skips rows                      | Check the generated "Missing Students" PDF for details.                  |
| Wrong cumulative targets                     | Update **Settings → Reams Required Per Form** first.                     |
| Database corrupted                           | Restore from a backup (Settings → Restore).                              |
| Need more help                               | Check `logs/` for detailed error messages.                               |

---

## License

This project is licensed under the [MIT License](LICENSE).

---

*Thank you for keeping ream records accurate!*