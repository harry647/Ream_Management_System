# modules/user_manager.py
import sqlite3
import bcrypt
import logging
import re
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from tkinter import messagebox

# ----------------------------------------------------------------------
# Global helpers from db_setup (the only place we touch the DB)
# ----------------------------------------------------------------------
from modules.db_setup import get_db_connection, release_db_connection

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/user_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# UI-thread helper
# ----------------------------------------------------------------------
def _ui(callback: Callable[..., Any]):
    def inner(*args, **kwargs):
        try:
            callback(*args, **kwargs)
        except Exception as exc:
            logger.exception("UI callback error")
            messagebox.showerror("Error", f"Unexpected error: {exc}")
    return inner


# ----------------------------------------------------------------------
# UserManager
# ----------------------------------------------------------------------
class UserManager:
    """All user CRUD + authentication – fully thread-safe."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(self, db_name: str = "database/ream_management.db"):
        self.db_name = db_name
        self.valid_roles = {"admin", "staff", "viewer"}
        self.valid_statuses = {"active", "inactive"}
        self.lock = threading.Lock()
        logger.info(f"UserManager initialized for {db_name}")

    # ------------------------------------------------------------------
    # Validation helpers (static)
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_username(username: str) -> None:
        if not username or not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            raise ValueError("Username: 3-20 alphanum + '_'")

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or not re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d!@#$%^&*]{6,50}", password):
            raise ValueError("Password: 6-50 chars, >=1 letter, >=1 digit")

    def _validate_role(self, role: str) -> None:
        if role not in self.valid_roles:
            raise ValueError(f"Role must be one of {self.valid_roles}")

    def _validate_status(self, status: str) -> None:
        if status not in self.valid_statuses:
            raise ValueError(f"Status must be one of {self.valid_statuses}")

    @staticmethod
    def _validate_remarks(remarks: Optional[str]) -> None:
        if remarks and not re.fullmatch(r"[A-Za-z0-9\s\-]{0,100}", remarks):
            raise ValueError("Remarks: max 100 alphanum + space + '-'")

    # ------------------------------------------------------------------
    # PRIVATE – does the actual DB lookup (used by public methods)
    # ------------------------------------------------------------------
    def _user_exists(self, username: str) -> bool:
        """Return True if a user with *username* exists."""
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            return cur.fetchone() is not None
        finally:
            release_db_connection(conn)

    # ------------------------------------------------------------------
    # PUBLIC – exact name the GUI expects
    # ------------------------------------------------------------------
    def user_exists(self, username: str) -> bool:
        """Public wrapper – keeps old GUI code happy."""
        with self.lock:
            self._validate_username(username)
            return self._user_exists(username)


    def get_password_hash(self, username: str) -> str:
        """Return password_hash for a user (used by ReportManager)."""
        with self.lock:
            self._validate_username(username)
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"User {username} not found")
                return row["password_hash"]
            finally:
                release_db_connection(conn)


    # ------------------------------------------------------------------
    # CREATE USER – background thread
    # ------------------------------------------------------------------
    def create_user(
        self,
        username: str,
        password: str,
        role: str = "staff",
        status: str = "active",
        creator: str = "system",
        *,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ) -> None:
        def _work():
            conn = None
            try:
                # ---- validation -------------------------------------------------
                self._validate_username(username)
                self._validate_password(password)
                self._validate_role(role)
                self._validate_status(status)
                self._validate_username(creator)

                if self._user_exists(username):
                    raise ValueError(f"Username '{username}' already taken")

                # ---- hash -------------------------------------------------------
                pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

                # ---- DB ---------------------------------------------------------
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, role, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, pw_hash, role, status),
                )
                user_id = cur.lastrowid
                conn.commit()

                # ---- success ----------------------------------------------------
                msg = f"User '{username}' created"
                logger.info(msg)
                if log_feedback:
                    log_feedback(msg)
                if callback:
                    callback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                err = f"Create user failed: {exc}"
                logger.error(err)
                if log_feedback:
                    log_feedback(err)
                if callback:
                    callback(exc)               
            finally:
                if conn:
                    release_db_connection(conn)

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # AUTHENTICATE
    # ------------------------------------------------------------------
    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            try:
                self._validate_username(username)
                if not password:
                    raise ValueError("Password cannot be empty")

                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT user_id, username, password_hash, role, status FROM users WHERE username = ?",
                        (username,),
                    )
                    row = cur.fetchone()
                    if not row:
                        self._audit(cur, "LOGIN", None, username, "Failed - not found")
                        conn.commit()
                        return None

                    user = dict(row)
                    if user["status"] != "active":
                        self._audit(cur, "LOGIN", user["user_id"], username, "Failed - inactive")
                        conn.commit()
                        return None

                    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
                        self._audit(cur, "LOGIN", user["user_id"], username, "Success")
                        conn.commit()
                        logger.info(f"Login OK: {username}")
                        return {
                            "user_id": user["user_id"],
                            "username": user["username"],
                            "role": user["role"],
                            "status": user["status"],
                            "password_hash": user["password_hash"],
                        }
                    else:
                        self._audit(cur, "LOGIN", user["user_id"], username, "Failed - wrong password")
                        conn.commit()
                        return None
                finally:
                    release_db_connection(conn)
            except Exception as exc:
                logger.error(f"authenticate_user error: {exc}")
                raise

    # ------------------------------------------------------------------
    # ROLE CHECK
    # ------------------------------------------------------------------
    def check_user_role(self, username: str, required_role: str) -> bool:
        with self.lock:
            try:
                self._validate_username(username)
                self._validate_role(required_role)

                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute("SELECT role, status FROM users WHERE username = ?", (username,))
                    row = cur.fetchone()
                    if not row or row["status"] != "active":
                        return False
                    role = row["role"]
                    if role == "admin":
                        return True
                    if required_role == "viewer" and role in {"staff", "viewer"}:
                        return True
                    return role == required_role
                finally:
                    release_db_connection(conn)
            except Exception as exc:
                logger.error(f"check_user_role error: {exc}")
                raise

    # ------------------------------------------------------------------
    # AUDIT helper (writes to audit_log table)
    # ------------------------------------------------------------------
    def _audit(self, cur: sqlite3.Cursor, operation: str, record_id: Optional[int],
               user: str, details: str) -> None:
        cur.execute(
            """
            INSERT INTO audit_log (table_name, operation, record_id, user, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("users", operation, record_id, user, details),
        )

    # ------------------------------------------------------------------
    # RESET PASSWORD – background thread
    # ------------------------------------------------------------------
    def reset_password(
        self,
        username: str,
        new_password: str,
        admin_user: str,
        remarks: Optional[str] = None,
        *,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ) -> None:
        def _work():
            conn = None
            try:
                self._validate_username(username)
                self._validate_password(new_password)
                self._validate_username(admin_user)
                self._validate_remarks(remarks)

                if not self.check_user_role(admin_user, "admin"):
                    raise PermissionError(f"{admin_user} is not an admin")

                pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT user_id FROM users WHERE username = ?", (username,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"User '{username}' not found")

                cur.execute(
                    """
                    UPDATE users SET password_hash = ?, updated_at = ?
                    WHERE username = ?
                    """,
                    (pw_hash, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username),
                )
                self._audit(cur, "UPDATE", row["user_id"], admin_user,
                            f"Password reset for {username}" + (f": {remarks}" if remarks else ""))
                conn.commit()

                msg = f"Password reset for {username}"
                logger.info(msg)
                if log_feedback:
                    log_feedback(msg)
                if callback:
                    callback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                err = f"Reset password failed: {exc}"
                logger.error(err)
                if log_feedback:
                    log_feedback(err)
                if callback:
                    callback(exc)
            finally:
                if conn:
                    release_db_connection(conn)

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # UPDATE STATUS – background thread
    # ------------------------------------------------------------------
    def update_user_status(
        self,
        username: str,
        new_status: str,
        admin_user: str,
        remarks: Optional[str] = None,
        *,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ) -> None:
        def _work():
            conn = None
            try:
                self._validate_username(username)
                self._validate_status(new_status)
                self._validate_username(admin_user)
                self._validate_remarks(remarks)

                if username == admin_user:
                    raise PermissionError("Cannot change own status")
                if not self.check_user_role(admin_user, "admin"):
                    raise PermissionError(f"{admin_user} is not an admin")

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT user_id, role FROM users WHERE username = ?", (username,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"User '{username}' not found")

                # Prevent de-activating the last admin
                if row["role"] == "admin" and new_status == "inactive":
                    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'")
                    if cur.fetchone()[0] <= 1:
                        raise PermissionError("Cannot deactivate the last active admin")

                cur.execute(
                    """
                    UPDATE users SET status = ?, updated_at = ?
                    WHERE username = ?
                    """,
                    (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username),
                )
                self._audit(cur, "UPDATE", row["user_id"], admin_user,
                            f"Status -> {new_status} for {username}" + (f": {remarks}" if remarks else ""))
                conn.commit()

                msg = f"Status of {username} -> {new_status}"
                logger.info(msg)
                if log_feedback:
                    log_feedback(msg)
                if callback:
                    callback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                err = f"Update status failed: {exc}"
                logger.error(err)
                if log_feedback:
                    log_feedback(err)
                if callback:
                    callback(exc)
            finally:
                if conn:
                    release_db_connection(conn)

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # DELETE USER – background thread
    # ------------------------------------------------------------------
    def delete_user(
        self,
        username: str,
        admin_user: str,
        remarks: Optional[str] = None,
        *,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ) -> None:
        def _work():
            conn = None
            try:
                self._validate_username(username)
                self._validate_username(admin_user)
                self._validate_remarks(remarks)

                if username == admin_user:
                    raise PermissionError("Cannot delete own account")
                if not self.check_user_role(admin_user, "admin"):
                    raise PermissionError(f"{admin_user} is not an admin")

                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT user_id, role FROM users WHERE username = ?", (username,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"User '{username}' not found")

                # Prevent deleting the last admin
                if row["role"] == "admin":
                    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'")
                    if cur.fetchone()[0] <= 1:
                        raise PermissionError("Cannot delete the last active admin")

                cur.execute("DELETE FROM users WHERE username = ?", (username,))
                self._audit(cur, "DELETE", row["user_id"], admin_user,
                            f"Deleted user {username}" + (f": {remarks}" if remarks else ""))
                conn.commit()

                msg = f"User '{username}' deleted"
                logger.info(msg)
                if log_feedback:
                    log_feedback(msg)
                if callback:
                    callback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                err = f"Delete user failed: {exc}"
                logger.error(err)
                if log_feedback:
                    log_feedback(err)
                if callback:
                    callback(exc)
            finally:
                if conn:
                    release_db_connection(conn)

        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------------
    # LIST / FETCH ALL USERS (admin only)
    # ------------------------------------------------------------------
    def fetch_all_users(self, requesting_user: str, requesting_role: str) -> List[Dict[str, Any]]:
        with self.lock:
            if requesting_role != "admin":
                raise PermissionError("Only admins may fetch all users")

            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT user_id, username, role, status, created_at, updated_at
                    FROM users ORDER BY username
                    """
                )
                rows = cur.fetchall()
                users = [dict(r) for r in rows]

                self._audit(cur, "DISPLAY", None, requesting_user, "Fetched all users")
                conn.commit()
                logger.info(f"All users fetched by {requesting_user}")
                return users
            finally:
                release_db_connection(conn)

    # ------------------------------------------------------------------
    # FETCH ALL STUDENTS (admin / staff / viewer)
    # ------------------------------------------------------------------
    def fetch_all_students(self, requesting_user: str, requesting_role: str) -> List[Dict[str, Any]]:
        with self.lock:
            if requesting_role not in {"admin", "staff", "viewer"}:
                raise PermissionError("Insufficient privileges to view students")

            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT student_id, admission_no, name, form, stream,
                           total_required, total_brought, remaining_to_bring,
                           status, created_at, updated_at
                    FROM students ORDER BY admission_no
                    """
                )
                rows = cur.fetchall()
                students = [dict(r) for r in rows]

                self._audit(cur, "DISPLAY", None, requesting_user, "Fetched all students")
                conn.commit()
                logger.info(f"All students fetched by {requesting_user}")
                return students
            finally:
                release_db_connection(conn)


# ----------------------------------------------------------------------
# END OF FILE
# ----------------------------------------------------------------------