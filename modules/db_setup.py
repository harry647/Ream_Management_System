import sqlite3
import os
import getpass
import atexit
import logging
import threading
import queue
import shutil
import time
import json
import re
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import bcrypt

# Load environment variables from .env file
load_dotenv()

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/database.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global connection pool
db_pool = None


# ===================================================================
# 1. Secure Admin Password (Critical Fix #1)
# ===================================================================
def get_admin_password() -> str:
    """
    Securely get admin password from environment or prompt.
    Never hardcode. Works in Docker, CI/CD, and local.
    """
    env_pass = os.getenv("ADMIN_PASSWORD")
    if env_pass:
        logger.info("Using ADMIN_PASSWORD from environment")
        return env_pass.strip()

    if os.isatty(0):  # Interactive terminal
        print("No ADMIN_PASSWORD environment variable found.")
        print("Enter a secure admin password (will be hashed and stored):")
        return getpass.getpass()
    else:
        raise ValueError(
            "ADMIN_PASSWORD environment variable is required in non-interactive mode "
            "(e.g. Docker, systemd, CI/CD)"
        )


# ===================================================================
# 2. JSON Validation & Cumulative Logic
# ===================================================================
def validate_json(json_str: str) -> bool:
    try:
        data = json.loads(json_str)
        expected_keys = {'Form 1', 'Form 2', 'Form 3', 'Form 4', 'Grade 10', 'Grade 11', 'Grade 12'}
        if not isinstance(data, dict):
            raise ValueError("JSON must be a dictionary")
        if not expected_keys.issubset(data.keys()):
            raise ValueError(f"JSON must contain all required keys: {expected_keys}")
        if not all(isinstance(v, int) and v >= 0 for v in data.values()):
            raise ValueError("All values in JSON must be non-negative integers")
        return True
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"JSON validation failed: {e}")
        raise


def get_cumulative_ream_requirements() -> dict[str, int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT ream_required_per_form FROM settings WHERE setting_id = 1")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("No settings row found.")
        raw_json = row["ream_required_per_form"]
        validate_json(raw_json)
        per_form: dict[str, int] = json.loads(raw_json)

        junior_order = ["Form 1", "Form 2", "Form 3", "Form 4"]
        senior_order = ["Grade 10", "Grade 11", "Grade 12"]

        junior_cum = {}
        acc = 0
        for f in junior_order:
            acc += per_form[f]
            junior_cum[f] = acc

        senior_cum = {}
        acc = 0
        for g in senior_order:
            acc += per_form[g]
            senior_cum[g] = acc

        return {**junior_cum, **senior_cum}
    except Exception as exc:
        logger.error(f"Failed to compute cumulative ream requirements: {exc}")
        raise RuntimeError("Could not compute cumulative ream requirements") from exc
    finally:
        if conn:
            release_db_connection(conn)


# ===================================================================
# 3. Connection Pool (Thread-safe)
# ===================================================================
class ConnectionPool:
    def __init__(self, db_path: str, max_connections: int = 15):
        self.db_path = db_path
        self.max_connections = max_connections
        self.connections = queue.Queue(maxsize=max_connections)
        self.lock = threading.Lock()
        logger.info(f"Initializing ConnectionPool for {db_path} with max_connections={max_connections}")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def get_connection(self, retries=3, delay=1):
        with self.lock:
            for attempt in range(retries):
                try:
                    return self.connections.get_nowait()
                except queue.Empty:
                    if self.connections.qsize() < self.max_connections:
                        try:
                            conn = sqlite3.connect(
                                self.db_path,
                                check_same_thread=False,
                                detect_types=sqlite3.PARSE_DECLTYPES,
                                timeout=30
                            )
                            conn.row_factory = sqlite3.Row
                            conn.execute("PRAGMA foreign_keys = ON")
                            conn.execute("PRAGMA journal_mode=WAL")
                            logger.info(f"Created new connection for {self.db_path}")
                            return conn
                        except sqlite3.Error as e:
                            logger.error(f"Connection attempt {attempt + 1}/{retries} failed: {e}")
                            if attempt < retries - 1:
                                time.sleep(delay)
                    else:
                        try:
                            conn = self.connections.get(timeout=30)
                            logger.info(f"Retrieved connection from pool")
                            return conn
                        except queue.Empty:
                            logger.error("Connection pool exhausted")
                            raise sqlite3.OperationalError("No available connections")
            raise sqlite3.OperationalError("Failed to get connection after retries")

    def release_connection(self, conn):
        if not conn:
            logger.warning("Attempted to release None connection")
            return
        with self.lock:
            if self.connections.qsize() < self.max_connections:
                self.connections.put(conn)
                logger.info("Released connection to pool")
            else:
                conn.close()
                logger.info("Closed excess connection")

    def close_all(self):
        with self.lock:
            while not self.connections.empty():
                conn = self.connections.get()
                conn.close()
                logger.info("Closed pooled connection")


def get_db_connection():
    global db_pool
    if db_pool is None:
        raise ValueError("Connection pool not initialized. Call init_database() first.")
    local = threading.local()
    if not hasattr(local, 'conn'):
        local.conn = db_pool.get_connection()
    return local.conn


def release_db_connection(conn):
    global db_pool
    if db_pool is None:
        return
    db_pool.release_connection(conn)


# ===================================================================
# 4. Utility Functions
# ===================================================================
def get_term_from_date(date_str: Optional[str], datetime_format: str = '%Y-%m-%d'):
    if not date_str:
        date_obj = datetime.now()
    else:
        if not re.match(r'^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$', date_str):
            raise ValueError("Date must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
        try:
            date_obj = datetime.strptime(date_str, datetime_format)
        except ValueError:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    month = date_obj.month
    if 1 <= month <= 4:
        return 'Term 1'
    elif 5 <= month <= 8:
        return 'Term 2'
    elif 9 <= month <= 12:
        return 'Term 3'
    raise ValueError(f"Invalid month {month}")


def backup_database(db_path="database/ream_management.db", backup_path="database/ream_management_backup.db"):
    try:
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_path)
        with src, dst:
            src.backup(dst)
        logger.info(f"Backup created at {backup_path}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        raise


def restore_database(db_path="database/ream_management.db", backup_path="database/ream_management_backup.db"):
    global db_pool
    try:
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup not found: {backup_path}")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        if db_pool:
            db_pool.close_all()
        shutil.copy2(backup_path, db_path)
        logger.info(f"Restored from {backup_path}")
        db_pool = ConnectionPool(db_path, max_connections=15)
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise


# ===================================================================
# 5. Health Check
# ===================================================================
def is_db_healthy() -> bool:
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        return False
    finally:
        if 'conn' in locals():
            release_db_connection(conn)


# ===================================================================
# 6. create_base_schema() – ALL FIXES APPLIED
# ===================================================================
def create_base_schema():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Tables
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            success TEXT,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('INSERT','UPDATE','DELETE','LOGIN','DISPLAY','REPORT','EXPORT','PROMOTE','SETTINGS')),
            record_id INTEGER,
            user TEXT NOT NULL,
            change_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_name TEXT NOT NULL DEFAULT 'Bar Union Secondary Mixed' CHECK(school_name != ''),
            current_term TEXT NOT NULL DEFAULT 'Term 1' CHECK(current_term IN ('Term 1','Term 2','Term 3')),
            term_year INTEGER NOT NULL DEFAULT (strftime('%Y','now')),
            min_stock_alert INTEGER NOT NULL DEFAULT 10 CHECK(min_stock_alert >= 0),
            ream_required_per_form TEXT NOT NULL DEFAULT '{"Form 1":2,"Form 2":2,"Form 3":2,"Form 4":2,"Grade 10":2,"Grade 11":2,"Grade 12":2}',
            total_required INTEGER NOT NULL DEFAULT 8 CHECK(total_required >= 0),
            datetime_format TEXT NOT NULL DEFAULT '%Y-%m-%d' CHECK(datetime_format != ''),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reams_stock (
            stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_reams INTEGER NOT NULL DEFAULT 0 CHECK(total_reams >= 0),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS  students (
            student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admission_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL CHECK(name != ''),
            form TEXT NOT NULL,
            stream TEXT,
            total_required INTEGER NOT NULL DEFAULT 8,
            total_brought INTEGER NOT NULL DEFAULT 0,
            remaining_to_bring INTEGER NOT NULL DEFAULT 8,
            status TEXT NOT NULL DEFAULT 'On Track' 
                CHECK(status IN ('Ahead', 'On Track', 'Behind', 'Complete')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reams_purchased (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            supplier TEXT NOT NULL,
            invoice_no TEXT NOT NULL,
            purchase_date TEXT NOT NULL,
            recorded_by TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT unique_invoice UNIQUE (invoice_no)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reams_brought (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            term TEXT NOT NULL CHECK(term IN ('Term 1','Term 2','Term 3')),
            form TEXT NOT NULL CHECK(form IN ('Form 1','Form 2','Form 3','Form 4','Grade 10','Grade 11','Grade 12')),
            date_brought TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now')),
            recorded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS reams_issued (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT,
            department TEXT NOT NULL CHECK(department IN ('Mathematics','Sciences','Languages','Humanities','Technical','Library','Administration','Exams','Store')),
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            date_issued TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now')),
            issued_by TEXT NOT NULL CHECK(issued_by != ''),
            purpose TEXT NOT NULL CHECK(purpose != ''),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE CHECK(username != ''),
            password_hash TEXT NOT NULL CHECK(password_hash != ''),
            role TEXT NOT NULL CHECK(role IN ('admin','staff','viewer')),
            status TEXT NOT NULL CHECK(status IN ('active','inactive')) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS department_limits (
            department_id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_name TEXT NOT NULL CHECK(department_name IN ('Mathematics','Sciences','Languages','Humanities','Technical','Library','Administration','Exams','Store')),
            term TEXT NOT NULL CHECK(term IN ('Term 1','Term 2','Term 3')),
            term_year INTEGER NOT NULL,
            ream_limit INTEGER NOT NULL CHECK(ream_limit >= 0),
            reams_issued INTEGER NOT NULL DEFAULT 0 CHECK(reams_issued >= 0),
            CONSTRAINT unique_dept_term_year UNIQUE (department_name, term, term_year)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS ream_stock_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_student_brought INTEGER NOT NULL DEFAULT 0,
            total_purchased INTEGER NOT NULL DEFAULT 0,
            total_issued INTEGER NOT NULL DEFAULT 0,
            current_balance INTEGER NOT NULL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Indexes
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_admission_no ON students(admission_no);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_students_form ON students(form);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reams_purchased_invoice_no ON reams_purchased(invoice_no);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_brought_student_id ON reams_brought(student_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_brought_date ON reams_brought(date_brought);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_brought_term ON reams_brought(term);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_issued_date ON reams_issued(date_issued);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_issued_department ON reams_issued(department);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_issued_term ON reams_issued(term);")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_department_limits_dept_term_year ON department_limits(department_name,term,term_year);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reams_brought_form ON reams_brought(form);")  # Fix #5

        # Views
        cur.execute("CREATE VIEW IF NOT EXISTS student_ream_summary AS SELECT * FROM students;")
        cur.execute("""
        CREATE VIEW IF NOT EXISTS class_ream_summary AS
        SELECT
            s.form,
            COUNT(DISTINCT s.student_id) AS total_students,
            COALESCE(SUM(r.quantity),0) AS brought_total,
            COUNT(DISTINCT s.student_id) * (
                SELECT json_extract(ream_required_per_form, '$.' || s.form) FROM settings WHERE setting_id = 1
            ) AS required_total,
            COUNT(DISTINCT s.student_id) * (
                SELECT json_extract(ream_required_per_form, '$.' || s.form) FROM settings WHERE setting_id = 1
            ) - COALESCE(SUM(r.quantity),0) AS remaining_total,
            ROUND(
                (COALESCE(SUM(r.quantity),0) * 100.0) /
                NULLIF(
                    COUNT(DISTINCT s.student_id) * (
                        SELECT json_extract(ream_required_per_form, '$.' || s.form) FROM settings WHERE setting_id = 1
                    ),0
                ),2
            ) AS percent_achieved
        FROM students s
        LEFT JOIN reams_brought r ON s.student_id = r.student_id
        GROUP BY s.form;
        """)

        # Triggers
        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS validate_settings_json
        BEFORE INSERT ON settings FOR EACH ROW
        WHEN NEW.ream_required_per_form IS NOT NULL
        BEGIN
            SELECT CASE
                WHEN json_valid(NEW.ream_required_per_form) = 0 THEN RAISE(ABORT, 'Invalid JSON')
                WHEN (SELECT COUNT(*) FROM json_each(NEW.ream_required_per_form)
                      WHERE json_each.key NOT IN ('Form 1','Form 2','Form 3','Form 4','Grade 10','Grade 11','Grade 12')) > 0
                    THEN RAISE(ABORT, 'Invalid key')
                WHEN (SELECT COUNT(*) FROM json_each(NEW.ream_required_per_form)
                      WHERE json_each.value NOT GLOB '[0-9]*' OR json_each.value < 0) > 0
                    THEN RAISE(ABORT, 'Invalid value')
            END;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS sync_student_total_required
        AFTER INSERT ON students FOR EACH ROW
        BEGIN
            UPDATE students SET total_required = (
                SELECT SUM(value) FROM (
                    SELECT json_each.value
                    FROM json_each((SELECT ream_required_per_form FROM settings WHERE setting_id = 1)) AS json_each
                    WHERE (NEW.form LIKE 'Form%' AND json_each.key <= NEW.form AND json_each.key LIKE 'Form%')
                       OR (NEW.form LIKE 'Grade%' AND json_each.key <= NEW.form AND json_each.key LIKE 'Grade%')
                )
            ) WHERE student_id = NEW.student_id;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS sync_student_total_required_update
        AFTER UPDATE OF form ON students FOR EACH ROW
        BEGIN
            UPDATE students SET total_required = (
                SELECT SUM(value) FROM (
                    SELECT json_each.value
                    FROM json_each((SELECT ream_required_per_form FROM settings WHERE setting_id = 1)) AS json_each
                    WHERE (NEW.form LIKE 'Form%' AND json_each.key <= NEW.form AND json_each.key LIKE 'Form%')
                       OR (NEW.form LIKE 'Grade%' AND json_each.key <= NEW.form AND json_each.key LIKE 'Grade%')
                )
            ) WHERE student_id = NEW.student_id;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS after_reams_brought_insert_stock
        AFTER INSERT ON reams_brought FOR EACH ROW
        BEGIN
            UPDATE reams_stock SET total_reams = total_reams + NEW.quantity,
                                 last_updated = CURRENT_TIMESTAMP
            WHERE status = 'active';
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS after_reams_purchased_insert_stock
        AFTER INSERT ON reams_purchased FOR EACH ROW
        BEGIN
            UPDATE reams_stock SET total_reams = total_reams + NEW.quantity,
                                 last_updated = CURRENT_TIMESTAMP
            WHERE status = 'active';
        END;
        """)

        # Fix #4: Use summary_id = 1
        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_summary_brought
        AFTER INSERT ON reams_brought FOR EACH ROW
        BEGIN
            UPDATE ream_stock_summary
            SET total_student_brought = total_student_brought + NEW.quantity,
                current_balance = current_balance + NEW.quantity,
                last_updated = CURRENT_TIMESTAMP
            WHERE summary_id = 1;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_summary_purchased
        AFTER INSERT ON reams_purchased FOR EACH ROW
        BEGIN
            UPDATE ream_stock_summary
            SET total_purchased = total_purchased + NEW.quantity,
                current_balance = current_balance + NEW.quantity,
                last_updated = CURRENT_TIMESTAMP
            WHERE summary_id = 1;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS update_summary_issued
        AFTER INSERT ON reams_issued FOR EACH ROW
        BEGIN
            UPDATE ream_stock_summary
            SET total_issued = total_issued + NEW.quantity,
                current_balance = current_balance - NEW.quantity,
                last_updated = CURRENT_TIMESTAMP
            WHERE summary_id = 1;
        END;
        """)

        # Default Data
        default_ream = {"Form 1":2,"Form 2":2,"Form 3":2,"Form 4":2,"Grade 10":2,"Grade 11":2,"Grade 12":2}
        json_str = json.dumps(default_ream)
        validate_json(json_str)

        cur.execute("""
        INSERT OR REPLACE INTO settings 
            (setting_id, school_name, current_term, term_year, min_stock_alert, 
             ream_required_per_form, total_required, datetime_format)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, ('Bar Union Secondary', 'Term 1', datetime.now().year, 10, json_str, 8, '%Y-%m-%d'))

        cur.execute("INSERT OR IGNORE INTO reams_stock (stock_id, total_reams, status) VALUES (1, 0, 'active')")
        cur.execute("INSERT OR IGNORE INTO ream_stock_summary (summary_id) VALUES (1)")

        current_year = datetime.now().year
        departments = [
            'Mathematics', 'Sciences', 'Languages', 'Humanities',
            'Technical', 'Library', 'Administration', 'Exams', 'Store'
        ]
        for dept in departments:
            limit = 100 if dept == 'Store' else 50
            for term in ['Term 1', 'Term 2', 'Term 3']:
                cur.execute("""
                INSERT OR IGNORE INTO department_limits 
                    (department_name, term, term_year, ream_limit, reams_issued)
                VALUES (?, ?, ?, ?, 0)
                """, (dept, term, current_year, limit))

        admin_password = get_admin_password()
        admin_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
        INSERT OR REPLACE INTO users 
            (user_id, username, password_hash, role, status, created_at, updated_at)
        VALUES (1, 'admin', ?, 'admin', 'active', ?, ?)
        """, (admin_hash, now_str, now_str))

        cur.execute("""
        INSERT OR REPLACE INTO schema_version 
            (version_id, version_number, description, applied_at)
        VALUES (1, '1.0.0', 'Production-ready v1.0.0', ?)
        """, (now_str,))

        # Production Polish
        cur.execute("PRAGMA optimize;")
        cur.execute("PRAGMA auto_vacuum = FULL;")
        try:
            cur.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size();")
            size = cur.fetchone()[0]
            if size < 100 * 1024 * 1024:
                cur.execute("VACUUM;")
                logger.info("VACUUM executed.")
        except:
            pass

        conn.commit()
        logger.info("Production database schema v1.0.0 initialized securely.")

    except Exception as e:
        logger.error(f"Schema setup failed: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_db_connection(conn)


# ===================================================================
# 7. Stock Reconciliation
# ===================================================================
def reconcile_stock():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE reams_stock SET
                total_reams = (SELECT current_balance FROM ream_stock_summary WHERE summary_id = 1),
                last_updated = CURRENT_TIMESTAMP
            WHERE status = 'active'
        """)
        conn.commit()
        logger.info("Stock reconciled.")
    except Exception as e:
        logger.error(f"Reconcile failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)


# ===================================================================
# 8. init_database()
# ===================================================================
def init_database(db_path="database/ream_management.db"):
    global db_pool
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        if db_pool is None:
            db_pool = ConnectionPool(db_path, max_connections=15)
            logger.info(f"Initialized connection pool for {db_path}")
        create_base_schema()
        reconcile_stock()
        atexit.register(lambda: db_pool.close_all() if db_pool else None)
        logger.info(f"Database fully initialized at {db_path}")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        if db_pool:
            db_pool.close_all()
        db_pool = None
        raise