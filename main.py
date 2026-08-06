# main.py
import os
import json
import logging
import sys
import customtkinter as ctk
from gui.main_window import MainWindow
from modules.db_setup import init_database, get_database_path, get_logs_dir, get_config_dir, get_app_dir
from modules.student_manager import StudentManager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import atexit
import threading

# ----------------------------------------------------------------------
# Logging (first thing!) - Use UTF-8 encoding to handle Unicode characters
# ----------------------------------------------------------------------
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)

# Create handlers with UTF-8 encoding
file_handler = logging.FileHandler(os.path.join(logs_dir, "main.log"), encoding='utf-8')
stream_handler = logging.StreamHandler(sys.stdout)
try:
    stream_handler.stream.reconfigure(encoding='utf-8')
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        file_handler,
        stream_handler
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Using logs directory: {logs_dir}")

# ----------------------------------------------------------------------
# Config handling
# ----------------------------------------------------------------------
def load_config():
    # Use platform-appropriate config directory
    config_dir = get_config_dir()
    config_path = os.path.join(config_dir, "config.json")
    
    # Get database path using platform-appropriate directory
    db_path = get_database_path()
    
    default_config = {
        "database_path": db_path,
        "ui_theme": {
            "appearance_mode": "dark",
            "color_theme": "blue"
        },
        "logging": {
            "level": "INFO",
            "file": os.path.join(get_logs_dir(), "main.log"),
            "console": True
        },
        "features": {
            "undo_enabled": False,
            "sample_data_enabled": True,
            "auto_promotion_enabled": True,
            "auto_promotion_schedule": {
                "month": 12,
                "day": 31,
                "hour": 23,
                "minute": 55
            }
        }
    }

    try:
        os.makedirs(config_dir, exist_ok=True)

        if not os.path.exists(config_path) or os.path.getsize(config_path) == 0:
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Created default config at {config_path}")
            return default_config

        with open(config_path, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning("Config file empty -> using defaults")
                with open(config_path, "w") as fw:
                    json.dump(default_config, fw, indent=4)
                return default_config

            config = json.loads(content)

            # Fill missing keys with defaults
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
                    logger.warning(f"Added missing config key: {key}")

            # Ensure nested logging defaults (backward compatibility)
            if "console" not in config.get("logging", {}):
                config["logging"]["console"] = True

            # Persist the merged config
            with open(config_path, "w") as fw:
                json.dump(config, fw, indent=4)

            return config

    except json.JSONDecodeError as e:
        logger.error(f"Bad JSON in config -> restoring defaults: {e}")
        with open(config_path, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config
    except Exception as e:
        logger.error(f"Config load error -> defaults: {e}")
        return default_config

# ----------------------------------------------------------------------
# System initialisation
# ----------------------------------------------------------------------
def initialize_system(config):
    """Create required folders **and** initialise the DB pool + schema."""
    try:
        os.makedirs("logs", exist_ok=True)
        os.makedirs("database", exist_ok=True)
        os.makedirs("config", exist_ok=True)

        # ------------------------------------------------------------------
        # 1. Initialise the **global** connection pool + tables + migrations
        # ------------------------------------------------------------------
        db_path = config["database_path"]
        init_database(db_path)                     
        logger.info(f"Database initialised at {db_path}")

        # ------------------------------------------------------------------
        # 2. (Optional) Insert sample data – keep it *after* DB init
        # ------------------------------------------------------------------
        '''if config["features"]["sample_data_enabled"]:
            try:
                from modules.ream_insert import import_reams_brought_data, imported_data
                import_reams_brought_data(imported_data)
                logger.info("Sample ream data imported")
            except Exception as e:
                logger.warning(f"Sample data import failed (non-critical): {e}")'''

    except Exception as e:
        logger.critical(f"System initialisation failed: {e}")
        raise

# ----------------------------------------------------------------------
# AUTO-PROMOTION SCHEDULER
# ----------------------------------------------------------------------
scheduler = None
student_manager = None

def run_auto_promotion():
    """Run auto-promotion — safe to call from background thread."""
    global student_manager
    if student_manager is None:
        student_manager = StudentManager()

    try:
        logger.info("Running scheduled auto-promotion...")
        result = student_manager.auto_promote_all(user="system_scheduler")
        if result.get("skipped"):
            logger.info(f"Auto-promotion skipped: {result['reason']}")
        else:
            logger.info(f"Auto-promotion completed: {result['success_count']} students promoted")
            if result["errors"]:
                logger.warning(f"Errors during promotion: {result['errors'][:3]}...")
    except Exception as e:
        logger.error(f"Auto-promotion failed: {e}", exc_info=True)

def start_scheduler(config):
    """Start background scheduler for auto-promotion."""
    global scheduler

    if not config["features"]["auto_promotion_enabled"]:
        logger.info("Auto-promotion is disabled in config")
        return

    scheduler = BackgroundScheduler()
    sched = config["features"]["auto_promotion_schedule"]

    trigger = CronTrigger(
        year="*",
        month=sched["month"],
        day=sched["day"],
        hour=sched["hour"],
        minute=sched["minute"],
        second=0
    )

    scheduler.add_job(
        func=run_auto_promotion,
        trigger=trigger,
        id='auto_promotion_job',
        name='Year-end Student Auto-Promotion',
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"Auto-promotion scheduled for {sched['month']}/{sched['day']} at {sched['hour']}:{sched['minute']:02d}")

    # Graceful shutdown
    atexit.register(lambda: scheduler.shutdown() if scheduler and scheduler.running else None)

# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def main():
    try:
        config = load_config()

        # Re-apply logging level from config
        logging.getLogger().setLevel(getattr(logging, config["logging"]["level"]))

        # Disable console logging in production if configured
        if not config.get("logging", {}).get("console", True):
            root = logging.getLogger()
            for handler in list(root.handlers):
                if isinstance(handler, logging.StreamHandler):
                    root.removeHandler(handler)

        # ------------------------------------------------------------------
        # 1. Initialise system (DB, folders)
        # ------------------------------------------------------------------
        initialize_system(config)

        # ------------------------------------------------------------------
        # 2. Start auto-promotion scheduler (background)
        # ------------------------------------------------------------------
        global student_manager
        student_manager = StudentManager()
        start_scheduler(config)

        # ------------------------------------------------------------------
        # 3. GUI start
        # ------------------------------------------------------------------
        logger.info("Launching GUI")
        ctk.set_appearance_mode(config["ui_theme"]["appearance_mode"])
        ctk.set_default_color_theme(config["ui_theme"]["color_theme"])

        app = MainWindow()
        app.mainloop()

    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        raise  

if __name__ == "__main__":
    main()