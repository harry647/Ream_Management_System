import sqlite3
import logging
import re
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from modules.db_setup import get_db_connection, release_db_connection, get_cumulative_ream_requirements, get_db_pool, get_logs_dir, get_database_path  
from modules.user_manager import UserManager
import csv
import json
from pylatex import Document, Section, Subsection, Tabular, Package, NoEscape
import threading
import pandas as pd


# ----------------------------------------------------------------------
# Logging configuration
# ----------------------------------------------------------------------
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'report_manager.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_NAME = get_database_path()


# ----------------------------------------------------------------------
# ReportManager
# ----------------------------------------------------------------------
class ReportManager:
    def __init__(self, db_name: str = DB_NAME):
        self.db_name = db_name
        # Uses global db_pool from db_setup.py
        self.user_manager = UserManager(db_name)
        self.edit_lock = threading.Lock()
        self.valid_terms = {'Term 1', 'Term 2', 'Term 3'}
        self.valid_forms = {'Form 1', 'Form 2', 'Form 3', 'Form 4', 'Grade 10', 'Grade 11', 'Grade 12'}
        self.valid_departments = {'Mathematics', 'Sciences', 'Languages', 'Humanities',
                                 'Technical', 'Library', 'Administration', 'Exams', 'Store'}

        # Cache cumulative ream requirements once per instance
        self.cum_req = get_cumulative_ream_requirements()

        # ------------------------------------------------------------------
        # Session state (current logged-in user)
        # ------------------------------------------------------------------
        self._current_user: Optional[Dict[str, Any]] = None
        self._current_user_lock = threading.Lock()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------
    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool."""
        pool = get_db_pool()
        return pool.get_connection(timeout=30)

    def _release_connection(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool."""
        if conn:
            pool = get_db_pool()
            pool.release_connection(conn)

    # ------------------------------------------------------------------
    # Validation helpers 
    # ------------------------------------------------------------------
    def _validate_admission_no(self, admission_no: str) -> bool:
        """Validate admission number format (1-12 alphanumeric characters)."""
        if not admission_no or not re.match(r'^[A-Za-z0-9]{1,12}$', admission_no):
            raise ValueError("Admission number must be 1-12 alphanumeric characters")
        return True

    def _validate_quantity(self, quantity: int) -> bool:
        """Validate ream quantity (positive integer, 1-10)."""
        if not isinstance(quantity, int) or quantity < 1 or quantity > 10:
            raise ValueError("Quantity must be an integer between 1 and 10")
        return True

    def _validate_term(self, term: str) -> bool:
        """Validate term against allowed values."""
        if term and term not in self.valid_terms:
            raise ValueError(f"Term must be one of {self.valid_terms} if provided")
        return True

    def _validate_form(self, form: Optional[str]) -> bool:
        """Validate form against allowed values if provided."""
        if form and form not in self.valid_forms:
            raise ValueError(f"Form must be one of {self.valid_forms} if provided")
        return True

    def _validate_stream(self, stream: Optional[str]) -> bool:
        """Validate stream against database values if provided."""
        if not stream or stream == "None":
            return True
        streams = self.get_streams()
        if stream not in streams:
            raise ValueError(f"Stream must be one of {streams} if provided")
        return True

    def _validate_department(self, department: Optional[str]) -> bool:
        """Validate department against allowed values if provided."""
        if department and department not in self.valid_departments:
            raise ValueError(f"Department must be one of {self.valid_departments} if provided")
        return True

    def _validate_recorded_by(self, recorded_by: Optional[str]) -> bool:
        """Validate recorded_by (alphanumeric with underscores, 3-20 characters if provided)."""
        if recorded_by and not re.match(r'^[A-Za-z0-9_]{3,20}$', recorded_by):
            raise ValueError("Recorded_by must be 3-20 alphanumeric characters with underscores if provided")
        return True

    def _validate_user(self, user: str) -> bool:
        """Validate user (alphanumeric with underscores, 3-20 characters)."""
        if not user or not re.match(r'^[A-Za-z0-9_]{3,20}$', user):
            raise ValueError("User must be 3-20 alphanumeric characters with underscores")
        return True

    def _validate_date_range(self, start_date: Optional[str], end_date: Optional[str]) -> bool:
        """Validate date range format (YYYY-MM-DD)."""
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        if start_date and not re.match(date_pattern, start_date):
            raise ValueError("Start date must be in YYYY-MM-DD format")
        if end_date and not re.match(date_pattern, end_date):
            raise ValueError("End date must be in YYYY-MM-DD format")
        if start_date and end_date and start_date > end_date:
            raise ValueError("Start date must be before or equal to end date")
        return True

    def _validate_supplier(self, supplier: str) -> bool:
        """Validate supplier (alphanumeric with spaces and hyphens, 2-50 characters)."""
        if not supplier or not re.match(r'^[A-Za-z0-9\s\-]{2,50}$', supplier):
            raise ValueError("Supplier must be 2-50 alphanumeric characters with spaces and hyphens")
        return True

    def _validate_invoice_no(self, invoice_no: str) -> bool:
        """Validate invoice number (alphanumeric with hyphens, 3-20 characters)."""
        if not invoice_no or not re.match(r'^[A-Za-z0-9\-]{3,20}$', invoice_no):
            raise ValueError("Invoice number must be 3-20 alphanumeric characters with hyphens")
        return True

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------
    def _log_audit(self, action: str, user: str, table_name: str, record_id: Optional[int],
                   details: str, success: bool = True) -> None:
        """Log an audit entry."""
        with self.edit_lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                valid_operations = {'INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'DISPLAY', 'REPORT', 'EXPORT'}

                report_actions = {
                    'student_summary', 'class_summary', 'defaulters_report', 'surplus_report',
                    'term_summary', 'issued_summary', 'overview', 'custom_report', 'stock_summary',
                    'stream_ream_report'
                }
                export_actions = {'export_to_pdf', 'export_to_csv', 'export_ream_report_to_pdf'}
                fetch_actions = {'fetch_all_students', 'search_students', 'get_student_by_admission',
                                 'get_streams', 'get_min_stock_alert'}

                if action in fetch_actions:
                    operation = 'DISPLAY'
                elif action in report_actions:
                    operation = 'REPORT'
                elif action in export_actions:
                    operation = 'EXPORT'
                else:
                    operation = action.upper()
                    if operation not in valid_operations:
                        raise ValueError(f"Invalid audit operation: {operation}")

                cursor.execute(
                    "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (action, '1' if success else '0', table_name, operation, record_id, user, details)
                )
                conn.commit()
                logger.info(f"Audit logged: {operation} ({action}) by {user}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to log audit: {e}")
                raise
            finally:
                self._release_connection(conn)

    # ------------------------------------------------------------------
    # Stock alert helper
    # ------------------------------------------------------------------
    def _check_stock_alert(self, conn: sqlite3.Connection) -> tuple[int, int]:
        """Check if stock is below the minimum alert threshold."""
        cursor = conn.cursor()
        cursor.execute("SELECT min_stock_alert FROM settings LIMIT 1")
        result = cursor.fetchone()
        min_stock = result['min_stock_alert'] if result else 10
        cursor.execute("SELECT current_balance FROM ream_stock_summary")
        result = cursor.fetchone()
        total_reams = result['current_balance'] if result else 0
        if total_reams < min_stock:
            logger.warning(f"Low Stock Alert! Only {total_reams} reams remaining (threshold: {min_stock})")
        return total_reams, min_stock

    # ------------------------------------------------------------------
    # Streams helper
    # ------------------------------------------------------------------
    def get_streams(self) -> List[str]:
        """Fetch unique streams from the students table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT stream FROM students WHERE stream IS NOT NULL ORDER BY stream")
            streams = [row['stream'] for row in cursor.fetchall()]
            logger.debug(f"Fetched {len(streams)} unique streams")
            return streams
        except Exception as e:
            logger.error(f"Error fetching streams: {e}")
            return []
        finally:
            self._release_connection(conn)

    # ------------------------------------------------------------------
    # AUTH HELPER – now with defaults & session fallback
    # ------------------------------------------------------------------
    def _check_user_auth(self, user: Optional[str] = None, role: Optional[str] = None,
                         required_role: str = 'admin') -> bool:
        """
        Check authorisation.
        If `user`/`role` are None, fall back to the current session.
        """
        if user and role:
            pass
        else:
            sess = self.get_current_user()
            if sess:
                user = sess.get('username')
                role = sess.get('role')
            else:
                user = role = None

        if not user or not role:
            logger.warning(f"Access denied: No user or role provided for {required_role} action")
            return False

        hierarchy = ('viewer', 'staff', 'admin')
        if required_role not in hierarchy:
            return False
        if hierarchy.index(role) >= hierarchy.index(required_role):
            return True

        logger.warning(f"Access denied: {user} lacks role {required_role}")
        return False


    # ------------------------------------------------------------------
    # SESSION / CURRENT USER MANAGEMENT
    # ------------------------------------------------------------------
    def set_current_user(self, username: str, password: str) -> bool:
        """Authenticate the user and store the session."""
        with self._current_user_lock:
            user_data = self.user_manager.authenticate_user(username, password)
            if user_data:
                self._current_user = user_data
                logger.info(f"ReportManager: User '{username}' logged in")
                return True
            else:
                self._current_user = None
                logger.warning(f"ReportManager: Failed login for '{username}'")
                return False

    def get_current_user(self) -> Optional[Dict[str, Any]]:
        with self._current_user_lock:
            return self._current_user.copy() if self._current_user else None

    def get_current_username(self) -> Optional[str]:
        user = self.get_current_user()
        return user["username"] if user else None

    def get_current_role(self) -> Optional[str]:
        user = self.get_current_user()
        return user["role"] if user else None

    def require_auth(self, required_role: str = "viewer") -> None:
        """Raise PermissionError if not logged in or insufficient role."""
        user = self.get_current_user()
        if not user:
            raise PermissionError("Authentication required – no user logged in")
        if not self.user_manager.check_user_role(user["username"], required_role):
            raise PermissionError(
                f"Role '{required_role}' required – user has '{user['role']}'"
            )

    def logout(self) -> None:
        with self._current_user_lock:
            if self._current_user:
                logger.info(f"ReportManager: User '{self._current_user['username']}' logged out")
            self._current_user = None

    # ------------------------------------------------------------------
    # Cumulative helper
    # ------------------------------------------------------------------
    def _get_required(self, form: str) -> int:
        """Return cumulative ream requirement for the given form."""
        return self.cum_req.get(form, 0)


    def student_summary(self, user: str = None, role: str = None, start_date: Optional[str] = None,
                        end_date: Optional[str] = None, form: Optional[str] = None,
                        stream: Optional[str] = None) -> List[Dict]:

        self.require_auth(required_role='viewer')  
        """Generate a student summary report using CUMULATIVE totals."""
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"student_summary: No records returned for unauthorized user {user or 'None'}")
                return []
            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        s.admission_no, s.name, s.form, s.stream,
                        COALESCE(SUM(r.quantity), 0) AS brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                """
                params = []
                conditions = []
                if start_date:
                    conditions.append("date(r.date_brought) >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("date(r.date_brought) <= ?")
                    params.append(end_date)
                if form:
                    conditions.append("s.form = ?")
                    params.append(form)
                if stream and stream != "None":
                    conditions.append("s.stream = ?")
                    params.append(stream)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " GROUP BY s.student_id, s.admission_no, s.name, s.form, s.stream"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = []
                for row in rows:
                    required = self._get_required(row['form'])  
                    brought = row['brought']
                    remaining = required - brought  
                    excess = max(0, -remaining)
                    status = 'Complete' if remaining == 0 else 'On Track' if brought > 0 else 'Behind'
                    records.append({
                        'admission_no': row['admission_no'],
                        'name': row['name'],
                        'form': row['form'],
                        'stream': row['stream'],
                        'required': required,
                        'brought': brought,
                        'remaining': remaining,
                        'status': status
                    })
                self._log_audit('student_summary', user or self.get_current_username() or 'unknown',
                                'reams_brought', 0,
                                f"Generated student summary with {len(records)} records")
                logger.info(f"Generated student summary with {len(records)} records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error generating student summary: {e}")
            self._log_audit('student_summary', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error generating student summary: {e}", False)
            raise

    def stock_summary(self, user: str = None, role: str = None, 
                  start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
        self.require_auth(required_role='admin')
        """Generate stock summary from ream_stock_summary table."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                return {}

            self._validate_date_range(start_date, end_date)
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                query = """
                    SELECT 
                        total_student_brought AS total_brought,
                        total_purchased,
                        total_issued,
                        current_balance
                    FROM ream_stock_summary
                    WHERE summary_id = 1
                """
                cursor.execute(query)
                row = cursor.fetchone()

                min_alert = self.get_min_stock_alert(user, role)
                data = {
                    'total_brought': row['total_brought'] if row else 0,
                    'total_purchased': row['total_purchased'] if row else 0,
                    'total_issued': row['total_issued'] if row else 0,
                    'current_balance': row['current_balance'] if row else 0,
                    'min_stock_alert': min_alert,
                    'low_stock': (row['current_balance'] if row else 0) < min_alert
                }

                self._log_audit('stock_summary', user or self.get_current_username() or 'unknown',
                                'ream_stock_summary', 0, "Generated stock summary")
                logger.info(f"Stock summary generated by {user or self.get_current_username()}")
                return data

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error generating stock summary: {e}")
            self._log_audit('stock_summary', user or self.get_current_username() or 'unknown',
                            'ream_stock_summary', 0, f"Error: {e}", success=False)
            raise

    def class_summary(self, user: str = None, role: str = None) -> List[Dict]:
        self.require_auth(required_role='admin') 
        """Generate a class summary report using CUMULATIVE ream_required_per_form."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"class_summary: No records returned for unauthorized user {user or 'None'}")
                return []
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT 
                        s.form,
                        COUNT(DISTINCT s.student_id) AS total_students,
                        COALESCE(SUM(r.quantity), 0) AS total_brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                    GROUP BY s.form
                    ORDER BY s.form
                """)
                rows = cursor.fetchall()
                records = []
                for row in rows:
                    form = row['form']
                    total_students = row['total_students']
                    total_brought = row['total_brought']
                    reams_per_student = self._get_required(form)  
                    total_required = total_students * reams_per_student
                    remaining = max(0, total_required - total_brought)
                    percentage = (total_brought / total_required * 100) if total_required > 0 else 0
                    records.append({
                        'form': form,
                        'total_students': total_students,
                        'total_brought': total_brought,
                        'total_required': total_required,
                        'remaining': remaining,
                        'percentage': round(percentage, 2)
                    })
                self._log_audit('class_summary', user or self.get_current_username() or 'unknown',
                                'reams_brought', 0,
                                f"Generated class summary with {len(records)} records")
                logger.info(f"Generated class summary with {len(records)} records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error generating class summary: {e}")
            self._log_audit('class_summary', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error generating class summary: {e}", False)
            raise

    def defaulters_report(
        self,
        user: str = None,
        role: str = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        form: Optional[str] = None,
        stream: Optional[str] = None
    ) -> List[Dict]:
        """
        Return students who have brought **less than required** reams.
        Uses **CUMULATIVE** totals (ignores date range if None).
        """
        self.require_auth(required_role='viewer')  # changed to viewer – staff can see too
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"defaulters_report: unauthorized user {user or 'None'}")
                return []

            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                # --------------------------------------------------------------
                # 1. Build base query – get each student + total brought
                # --------------------------------------------------------------
                query = """
                    SELECT
                        s.student_id,
                        s.admission_no,
                        s.name,
                        s.form,
                        s.stream,
                        COALESCE(SUM(r.quantity), 0) AS total_brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                """
                params = []
                conditions = []

                if start_date:
                    conditions.append("date(r.date_brought) >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("date(r.date_brought) <= ?")
                    params.append(end_date)
                if form:
                    conditions.append("s.form = ?")
                    params.append(form)
                if stream and stream != "None":
                    conditions.append("s.stream = ?")
                    params.append(stream)

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                query += " GROUP BY s.student_id"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                # --------------------------------------------------------------
                # 2. Compare with required reams per form
                # --------------------------------------------------------------
                records = []
                for row in rows:
                    required = self._get_required(row['form'])  # e.g. 5 for Form 1
                    brought = row['total_brought']

                    if brought < required:
                        records.append({
                            'admission_no': row['admission_no'],
                            'name': row['name'],
                            'form': row['form'],
                            'stream': row['stream'] or '',
                            'required': required,
                            'brought': brought,
                            'remaining': required - brought
                        })

                # --------------------------------------------------------------
                # 3. Audit & log
                # --------------------------------------------------------------
                username = user or self.get_current_username() or 'unknown'
                self._log_audit(
                    'defaulters_report', username, 'reams_brought', 0,
                    f"Generated defaulters report ({len(records)} students)"
                )
                logger.info(f"Defaulters report: {len(records)} students by {username}")

                return records

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"defaulters_report error: {e}")
            self._log_audit(
                'defaulters_report',
                user or self.get_current_username() or 'unknown',
                'reams_brought', 0,
                f"Error: {e}", success=False
            )
            return []  # never crash UI

    def surplus_report(self, user: str = None, role: str = None, start_date: Optional[str] = None,
                       end_date: Optional[str] = None, form: Optional[str] = None,
                       stream: Optional[str] = None) -> List[Dict]:
        self.require_auth(required_role='admin')
        """Generate a surplus report using CUMULATIVE totals."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"surplus_report: No records returned for unauthorized user {user or 'None'}")
                return []
            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        s.admission_no, s.name, s.form, s.stream,
                        COALESCE(SUM(r.quantity), 0) AS brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                """
                params = []
                conditions = []
                if start_date:
                    conditions.append("date(r.date_brought) >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("date(r.date_brought) <= ?")
                    params.append(end_date)
                if form:
                    conditions.append("s.form = ?")
                    params.append(form)
                if stream and stream != "None":
                    conditions.append("s.stream = ?")
                    params.append(stream)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " GROUP BY s.student_id, s.admission_no, s.name, s.form, s.stream"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = []
                for row in rows:
                    required = self._get_required(row['form']) 
                    brought = row['brought']
                    if brought > required:
                        records.append({
                            'admission_no': row['admission_no'],
                            'name': row['name'],
                            'form': row['form'],
                            'stream': row['stream'],
                            'required': required,
                            'brought': brought,
                            'surplus': brought - required
                        })
                self._log_audit('surplus_report', user or self.get_current_username() or 'unknown',
                                'reams_brought', 0,
                                f"Generated surplus report with {len(records)} records")
                logger.info(f"Generated surplus report with {len(records)} records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error generating surplus report: {e}")
            self._log_audit('surplus_report', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error generating surplus report: {e}", False)
            raise

    def term_summary(self, user: str = None, role: str = None, term: Optional[str] = None,
                     start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        self.require_auth(required_role='admin') 
        """Generate a term summary report."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"term_summary: No records returned for unauthorized user {user or 'None'}")
                return []
            self._validate_term(term)
            self._validate_date_range(start_date, end_date)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        r.term,
                        COUNT(r.record_id) AS total_entries,
                        COALESCE(SUM(r.quantity), 0) AS total_reams
                    FROM reams_brought r
                    WHERE 1=1
                """
                params = []
                if term:
                    query += " AND r.term = ?"
                    params.append(term)
                if start_date:
                    query += " AND date(r.date_brought) >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date(r.date_brought) <= ?"
                    params.append(end_date)
                query += " GROUP BY r.term"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = [
                    {
                        'term': row['term'],
                        'total_entries': row['total_entries'],
                        'total_reams': row['total_reams']
                    } for row in rows
                ]
                self._log_audit('term_summary', user or self.get_current_username() or 'unknown',
                                'reams_brought', 0,
                                f"Generated term summary with {len(records)} records")
                logger.info(f"Generated term summary with {len(records)} records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error generating term summary: {e}")
            self._log_audit('term_summary', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error generating term summary: {e}", False)
            raise

    def issued_summary(self, user: str = None, role: str = None, start_date: Optional[str] = None,
                       end_date: Optional[str] = None, department: Optional[str] = None) -> List[Dict]:
        self.require_auth(required_role='viewer')
        """Generate an issued summary report."""
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"issued_summary: No records returned for unauthorized user {user or 'None'}")
                return []
            self._validate_date_range(start_date, end_date)
            self._validate_department(department)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        ri.department,
                        COALESCE(SUM(ri.quantity), 0) AS total_issued
                    FROM reams_issued ri
                    WHERE 1=1
                """
                params = []
                if start_date:
                    query += " AND date(ri.date_issued) >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date(ri.date_issued) <= ?"
                    params.append(end_date)
                if department:
                    query += " AND ri.department = ?"
                    params.append(department)
                query += " GROUP BY ri.department"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = [
                    {
                        'department': row['department'],
                        'total_issued': row['total_issued']
                    } for row in rows
                ]
                self._log_audit('issued_summary', user or self.get_current_username() or 'unknown',
                                'reams_issued', 0,
                                f"Generated issued summary with {len(records)} records")
                logger.info(f"Generated issued summary with {len(records)} records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error generating issued summary: {e}")
            self._log_audit('issued_summary', user or self.get_current_username() or 'unknown',
                            'reams_issued', 0,
                            f"Error generating issued summary: {e}", False)
            raise

    def overview(self, user: str = None, role: str = None, start_date: Optional[str] = None,
             end_date: Optional[str] = None) -> Dict:
        """Generate overview report. Always returns a dict."""
        self.require_auth(required_role='viewer')
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"overview: No data for unauthorized user {user or 'None'}")
                return {
                    'total_required': 0, 'total_brought': 0, 'remaining': 0,
                    'collection_percentage': 0.0, 'total_issued': 0, 'total_stock': 0
                }

            self._validate_date_range(start_date, end_date)
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                # === 1. Student reams (brought) ===
                query = """
                    SELECT
                        s.form,
                        COUNT(DISTINCT s.student_id) AS total_students,
                        COALESCE(SUM(r.quantity), 0) AS total_brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                """
                params = []
                conditions = []
                if start_date:
                    conditions.append("date(r.date_brought) >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("date(r.date_brought) <= ?")
                    params.append(end_date)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " GROUP BY s.form"
                cursor.execute(query, params)
                rows = cursor.fetchall()

                total_required = 0
                total_brought = 0
                for row in rows:
                    form = row['form']
                    total_students = row['total_students']
                    reams_per_student = self._get_required(form)
                    total_required += total_students * reams_per_student
                    total_brought += row['total_brought']

                # === 2. Issued reams ===
                issued_query = """
                    SELECT COALESCE(SUM(quantity), 0) AS total_issued
                    FROM reams_issued
                """
                issued_params = []
                issued_conditions = []
                if start_date:
                    issued_conditions.append("date(date_issued) >= ?")
                    issued_params.append(start_date)
                if end_date:
                    issued_conditions.append("date(date_issued) <= ?")
                    issued_params.append(end_date)
                if issued_conditions:
                    issued_query += " WHERE " + " AND ".join(issued_conditions)
                cursor.execute(issued_query, issued_params)
                total_issued = cursor.fetchone()['total_issued']

                # === 3. Stock balance ===
                cursor.execute("SELECT current_balance FROM ream_stock_summary")
                row = cursor.fetchone()
                total_stock = row['current_balance'] if row else 0

                # === 4. Final calculations ===
                remaining = max(0, total_required - total_brought)
                collection_percentage = (total_brought / total_required * 100) if total_required > 0 else 0.0

                # === 5. ALWAYS RETURN A DICT ===
                result = {
                    'total_required': int(total_required),
                    'total_brought': int(total_brought),
                    'remaining': int(remaining),
                    'collection_percentage': round(collection_percentage, 2),
                    'total_issued': int(total_issued),
                    'total_stock': int(total_stock)
                }

                self._log_audit(
                    'overview', user or self.get_current_username() or 'unknown',
                    'reams_brought', 0,
                    f"Generated overview report"
                )
                logger.info(f"Generated overview report by {user or self.get_current_username()}")
                return result

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error generating overview: {e}")
            self._log_audit(
                'overview', user or self.get_current_username() or 'unknown',
                'reams_brought', 0,
                f"Error: {e}", False
            )
            # Even on error, return a safe dict
            return {
                'total_required': 0, 'total_brought': 0, 'remaining': 0,
                'collection_percentage': 0.0, 'total_issued': 0, 'total_stock': 0
            }

    def custom_report(self, report_types: List[str],  user: str = None, role: str = None, 
                      start_date: Optional[str] = None, end_date: Optional[str] = None,
                      form: Optional[str] = None, stream: Optional[str] = None,
                      department: Optional[str] = None) -> Dict[str, List[Dict]]:
        self.require_auth(required_role='viewer') 
        """Generate custom reports based on selected report types."""
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"custom_report: No records returned for unauthorized user {user or 'None'}")
                return {}
            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)
            self._validate_department(department)

            valid_reports = {
                'student_summary': self.student_summary,
                'class_summary': self.class_summary,
                'defaulters': self.defaulters_report,
                'surplus': self.surplus_report,
                'term_summary': self.term_summary,
                'issued_summary': self.issued_summary,
                'stream_ream': self.stream_ream_report,
            }
            results = {}
            for report_type in report_types:
                if report_type not in valid_reports:
                    logger.warning(f"Invalid report type: {report_type}")
                    continue
                if report_type == 'class_summary':
                    results[report_type] = valid_reports[report_type](user, role)
                elif report_type == 'term_summary':
                    results[report_type] = valid_reports[report_type](user, role, None, start_date, end_date)
                elif report_type == 'issued_summary':
                    results[report_type] = valid_reports[report_type](user, role, start_date, end_date, department)
                elif report_type == 'stream_ream':
                    results[report_type] = valid_reports[report_type](user, role, form, stream, start_date, end_date)
                else:
                    results[report_type] = valid_reports[report_type](user, role, start_date, end_date, form, stream)
            self._log_audit('custom_report', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Generated custom report for types {report_types}")
            logger.info(f"Generated custom report for types {report_types} by {user or self.get_current_username()}")
            return results
        except Exception as e:
            logger.error(f"Error generating custom report: {e}")
            self._log_audit('custom_report', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error generating custom report: {e}", False)
            raise

    def fetch_all_records(self, user: str = None, role: str = None) -> List[Dict]:
        self.require_auth(required_role='admin') 
        """Fetch all ream records for export."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"fetch_all_records: No records returned for unauthorized user {user or 'None'}")
                return []
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        r.record_id, s.admission_no, s.name, s.form, s.stream, 
                        r.quantity, r.term, r.date_brought, r.recorded_by
                    FROM reams_brought r
                    JOIN students s ON r.student_id = s.student_id
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                records = [
                    {
                        'record_id': row['record_id'],
                        'admission_no': row['admission_no'],
                        'name': row['name'],
                        'form': row['form'],
                        'stream': row['stream'],
                        'quantity': row['quantity'],
                        'term': row['term'],
                        'date_brought': row['date_brought'],
                        'recorded_by': row['recorded_by']
                    } for row in rows
                ]
                self._log_audit('fetch_all_records', user or self.get_current_username() or 'unknown',
                                'reams_brought', 0,
                                f"Fetched {len(records)} ream records")
                logger.info(f"Fetched {len(records)} ream records by {user or self.get_current_username()}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching all records: {e}")
            self._log_audit('fetch_all_records', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error fetching all records: {e}", False)
            raise

    def export_ream_report_to_pdf(self, file_path: str, user: str = None, role: str = None) -> None:
        self.require_auth(required_role='admin')
        """Export ream records to a PDF file using LaTeX."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                raise ValueError("Permission denied: admin or higher role required")
            records = self.fetch_all_records(user, role)

            doc = Document(documentclass='article')
            doc.packages.append(Package('geometry', options=['a4paper', 'margin=1in']))
            doc.packages.append(Package('booktabs'))
            doc.packages.append(Package('array'))
            doc.packages.append(Package('times'))
            doc.preamble.append(NoEscape(r'\usepackage{parskip}'))
            doc.preamble.append(NoEscape(r'\usepackage[scaled=.90]{helvet}'))
            doc.preamble.append(NoEscape(r'\usepackage[scaled=.95]{courier}'))

            with doc.create(Section('Ream Records Report')):
                doc.append(f"Generated by {user or self.get_current_username() or 'unknown'} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                with doc.create(Subsection('Records')):
                    with doc.create(Tabular('|l|l|l|l|l|r|l|l|')) as table:
                        table.add_hline()
                        table.add_row(('Record ID', 'Admission No', 'Name', 'Form', 'Stream',
                                       'Quantity', 'Term', 'Date Brought', 'Recorded By'))
                        table.add_hline()
                        for record in records:
                            table.add_row((
                                str(record['record_id']),
                                record['admission_no'],
                                record['name'],
                                record['form'],
                                record['stream'] or '',
                                str(record['quantity']),
                                record['term'],
                                record['date_brought'],
                                record['recorded_by'] or ''
                            ))
                            table.add_hline()

            doc.generate_pdf(file_path.replace('.pdf', ''), clean_tex=True, compiler='pdflatex')
            self._log_audit('export_ream_report_to_pdf', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Exported ream report to {file_path}")
            logger.info(f"Exported ream report to {file_path} by {user or self.get_current_username()}")
        except Exception as e:
            logger.error(f"Error exporting ream report to {file_path}: {e}")
            self._log_audit('export_ream_report_to_pdf', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error exporting ream report to {file_path}: {e}", False)
            raise

    def export_to_pdf(self, report_type: str, file_path: str, user: str = None, role: str = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None,
                      form: Optional[str] = None, stream: Optional[str] = None,
                      department: Optional[str] = None) -> None:
        self.require_auth(required_role='viewer')
        """Export specified report to PDF."""
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")
            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)
            self._validate_department(department)

            report_configs = {
                'student_summary': {
                    'title': 'Student Summary Report',
                    'columns': ['Admission No', 'Name', 'Form', 'Stream', 'Required', 'Brought',
                                'Remaining', 'Status'],
                    'data': lambda: self.student_summary(user, role, start_date, end_date, form, stream)
                },
                'class_summary': {
                    'title': 'Class Summary Report',
                    'columns': ['Form', 'Total Students', 'Total Brought', 'Total Required',
                                'Remaining', 'Percentage'],
                    'data': lambda: self.class_summary(user, role)
                },
                'defaulters': {
                    'title': 'Defaulters Report',
                    'columns': ['Admission No', 'Name', 'Form', 'Stream', 'Required', 'Brought',
                                'Remaining'],
                    'data': lambda: self.defaulters_report(user, role, start_date, end_date, form, stream)
                },
                'surplus': {
                    'title': 'Surplus Report',
                    'columns': ['Admission No', 'Name', 'Form', 'Stream', 'Required', 'Brought',
                                'Surplus'],
                    'data': lambda: self.surplus_report(user, role, start_date, end_date, form, stream)
                },
                'term_summary': {
                    'title': 'Term Summary Report',
                    'columns': ['Term', 'Total Entries', 'Total Reams'],
                    'data': lambda: self.term_summary(user, role, None, start_date, end_date)
                },
                'issued_summary': {
                    'title': 'Issued Summary Report',
                    'columns': ['Department', 'Total Issued'],
                    'data': lambda: self.issued_summary(user, role, start_date, end_date, department)
                },
                'stream_ream': {
                    'title': 'Stream Ream Report',
                    'columns': ['Admission No', 'Name', 'Required', 'Brought', 'Remaining', 'Status'],
                    'data': lambda: self.stream_ream_report(user, role, form, stream,
                                                            start_date, end_date)['students']
                }
            }

            if report_type not in report_configs:
                raise ValueError(f"Invalid report type: {report_type}")

            config = report_configs[report_type]
            records = config['data']()

            doc = Document(documentclass='article')
            doc.packages.append(Package('geometry', options=['a4paper', 'margin=1in']))
            doc.packages.append(Package('booktabs'))
            doc.packages.append(Package('array'))
            doc.packages.append(Package('times'))
            doc.preamble.append(NoEscape(r'\usepackage{parskip}'))
            doc.preamble.append(NoEscape(r'\usepackage[scaled=.90]{helvet}'))
            doc.preamble.append(NoEscape(r'\usepackage[scaled=.95]{courier}'))

            with doc.create(Section(config['title'])):
                doc.append(f"Generated by {user or self.get_current_username() or 'unknown'} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                with doc.create(Subsection('Records')):
                    table_spec = '|' + 'l|' * len(config['columns'])
                    with doc.create(Tabular(table_spec)) as table:
                        table.add_hline()
                        table.add_row(config['columns'])
                        table.add_hline()
                        for record in records:
                            row = [str(record.get(col.lower().replace(' ', '_'), '')) for col in config['columns']]
                            table.add_row(row)
                            table.add_hline()

            doc.generate_pdf(file_path.replace('.pdf', ''), clean_tex=True, compiler='pdflatex')
            self._log_audit('export_to_pdf', user or self.get_current_username() or 'unknown',
                            'reports', 0,
                            f"Exported {report_type} report to {file_path}")
            logger.info(f"Exported {report_type} report to {file_path} by {user or self.get_current_username()}")
        except Exception as e:
            logger.error(f"Error exporting {report_type} report to {file_path}: {e}")
            self._log_audit('export_to_pdf', user or self.get_current_username() or 'unknown',
                            'reports', 0,
                            f"Error exporting {report_type} report to {file_path}: {e}", False)
            raise

    def export_to_csv(self, report_type: str, file_path: str, user: str = None, role: str = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None,
                      form: Optional[str] = None, stream: Optional[str] = None,
                      department: Optional[str] = None) -> None:
        self.require_auth(required_role='viewer') 
        """Export specified report to CSV."""
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")
            self._validate_date_range(start_date, end_date)
            self._validate_form(form)
            self._validate_stream(stream)
            self._validate_department(department)

            report_configs = {
                'student_summary': {
                    'columns': ['admission_no', 'name', 'form', 'stream', 'required', 'brought',
                                'remaining', 'status'],
                    'data': lambda: self.student_summary(user, role, start_date, end_date, form, stream)
                },
                'class_summary': {
                    'columns': ['form', 'total_students', 'total_brought', 'total_required',
                                'remaining', 'percentage'],
                    'data': lambda: self.class_summary(user, role)
                },
                'defaulters': {
                    'columns': ['admission_no', 'name', 'form', 'stream', 'required', 'brought',
                                'remaining'],
                    'data': lambda: self.defaulters_report(user, role, start_date, end_date, form, stream)
                },
                'surplus': {
                    'columns': ['admission_no', 'name', 'form', 'stream', 'required', 'brought',
                                'surplus'],
                    'data': lambda: self.surplus_report(user, role, start_date, end_date, form, stream)
                },
                'term_summary': {
                    'columns': ['term', 'total_entries', 'total_reams'],
                    'data': lambda: self.term_summary(user, role, None, start_date, end_date)
                },
                'issued_summary': {
                    'columns': ['department', 'total_issued'],
                    'data': lambda: self.issued_summary(user, role, start_date, end_date, department)
                },
                'stream_ream': {
                    'columns': ['admission_no', 'name', 'required', 'brought', 'remaining', 'status'],
                    'data': lambda: self.stream_ream_report(user, role, form, stream,
                                                            start_date, end_date)['students']
                }
            }

            if report_type not in report_configs:
                raise ValueError(f"Invalid report type: {report_type}")

            config = report_configs[report_type]
            records = config['data']()
            df = pd.DataFrame(records, columns=config['columns'])
            df.to_csv(file_path, index=False)
            self._log_audit('export_to_csv', user or self.get_current_username() or 'unknown',
                            'reports', 0,
                            f"Exported {report_type} report to {file_path}")
            logger.info(f"Exported {report_type} report to {file_path} by {user or self.get_current_username()}")
        except Exception as e:
            logger.error(f"Error exporting {report_type} report to {file_path}: {e}")
            self._log_audit('export_to_csv', user or self.get_current_username() or 'unknown',
                            'reports', 0,
                            f"Error exporting {report_type} report to {file_path}: {e}", False)
            raise

    def get_min_stock_alert(self, user: str = None, role: str = None) -> int:
        self.require_auth(required_role='admin') 
        """Get the minimum stock alert threshold."""
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"get_min_stock_alert: No value returned for unauthorized user {user or 'None'}")
                return 10
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT min_stock_alert FROM settings LIMIT 1")
                result = cursor.fetchone()
                min_stock = result['min_stock_alert'] if result else 10
                self._log_audit('get_min_stock_alert', user or self.get_current_username() or 'unknown',
                                'settings', 0,
                                f"Fetched min stock alert ({min_stock})")
                logger.info(f"Fetched min stock alert ({min_stock}) by {user or self.get_current_username()}")
                return min_stock
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching min stock alert: {e}")
            self._log_audit('get_min_stock_alert', user or self.get_current_username() or 'unknown',
                            'settings', 0,
                            f"Error fetching min stock alert: {e}", False)
            raise

    def stream_ream_report(self, user: str = None, role: str = None, form: Optional[str] = None,
                           stream: Optional[str] = None, start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> Dict[str, any]:
        self.require_auth(required_role='admin') 
        """
        Generate a detailed ream report for a specific Form + Stream.
        """
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                logger.info(f"stream_ream_report: Access denied for user {user or 'None'}")
                return {'students': [], 'summary': {}}

            self._validate_form(form)
            self._validate_stream(stream)
            self._validate_date_range(start_date, end_date)

            if not form and not stream:
                raise ValueError("At least Form or Stream must be supplied for a stream ream report")

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        s.admission_no,
                        s.name,
                        s.form,
                        s.stream,
                        COALESCE(SUM(r.quantity), 0) AS brought
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                    WHERE 1=1
                """
                params = []
                if form:
                    query += " AND s.form = ?"
                    params.append(form)
                if stream and stream != "None":
                    query += " AND s.stream = ?"
                    params.append(stream)

                if start_date:
                    query += " AND date(r.date_brought) >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date(r.date_brought) <= ?"
                    params.append(end_date)

                query += " GROUP BY s.student_id, s.admission_no, s.name, s.form, s.stream"
                query += " ORDER BY s.form, s.stream, s.admission_no"

                cursor.execute(query, params)
                rows = cursor.fetchall()

                students = []
                total_required = total_brought = 0
                for row in rows:
                    f = row['form']
                    required = self._get_required(f)
                    brought = row['brought']
                    remaining = required - brought  
                    excess = max(0, -remaining)
                    status = ('Complete' if remaining == 0 else
                              'On Track' if brought > 0 else 'Behind')

                    students.append({
                        'admission_no': row['admission_no'],
                        'name': row['name'],
                        'form': f,
                        'stream': row['stream'],
                        'required': required,
                        'brought': brought,
                        'remaining': remaining,
                        'status': status
                    })
                    total_required += required
                    total_brought += brought

                total_remaining = max(0, total_required - total_brought)
                collection_percentage = (total_brought / total_required * 100) if total_required else 0.0

                summary = {
                    'form': form,
                    'stream': stream,
                    'total_students': len(students),
                    'total_required': total_required,
                    'total_brought': total_brought,
                    'total_remaining': total_remaining,
                    'collection_percentage': round(collection_percentage, 2)
                }

                self._log_audit(
                    'stream_ream_report', user or self.get_current_username() or 'unknown',
                    'reams_brought', 0,
                    f"Stream report for {form or 'All'} {stream or 'All'}: {len(students)} students"
                )
                logger.info(f"Generated stream ream report for {form or 'All'} {stream or 'All'} by {user or self.get_current_username()}")
                return {'students': students, 'summary': summary}

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error in stream_ream_report: {e}")
            self._log_audit('stream_ream_report', user or self.get_current_username() or 'unknown',
                            'reams_brought', 0,
                            f"Error: {e}", success=False)
            raise


if __name__ == "__main__":
    report_mgr = ReportManager()