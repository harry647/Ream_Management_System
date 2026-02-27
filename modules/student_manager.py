import sqlite3
import pandas as pd
import logging
from datetime import datetime
import os
import re
from typing import List, Optional, Dict 
from modules.db_setup import get_db_connection, release_db_connection, validate_json, get_term_from_date, get_cumulative_ream_requirements, get_db_pool
from modules.user_manager import UserManager
import threading
import json
import time

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/student_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_NAME = "database/ream_management.db"

# Uses global db_pool from db_setup.py

class StudentManager:
    def __init__(self, db_name: str = DB_NAME):
        self.db_name = db_name
        self.user_mgr = UserManager(db_name)
        self.edit_lock = threading.Lock()
        self.valid_forms = {'Form 1', 'Form 2', 'Form 3', 'Form 4', 'Grade 10', 'Grade 11', 'Grade 12'}
        self.form_progression = {
            'Form 1': 'Form 2',
            'Form 2': 'Form 3',
            'Form 3': 'Form 4',
            'Grade 10': 'Grade 11',
            'Grade 11': 'Grade 12'
        }

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool."""
        pool = get_db_pool()
        return pool.get_connection(timeout=30)

    def _release_connection(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool."""
        if conn:
            pool = get_db_pool()
            pool.release_connection(conn)

    def _validate_admission_no(self, admission_no: str) -> bool:
        """Validate admission number format (1-12 alphanumeric characters)."""
        if not admission_no or not re.match(r'^[A-Za-z0-9]{1,12}$', admission_no):
            raise ValueError("Admission number must be 1-12 alphanumeric characters")
        return True

    def _validate_name(self, name: str) -> bool:
        """Validate name (2+ characters, letters, spaces, hyphens, apostrophes only)."""
        if not name or not re.match(r'^[A-Za-z\s\-\']{2,}$', name):
            raise ValueError("Name must be at least 2 characters and contain only letters, spaces, hyphens, or apostrophes")
        return True

    def _validate_form(self, form: str) -> bool:
        """Validate form against allowed values."""
        if form not in self.valid_forms:
            raise ValueError(f"Form must be one of {self.valid_forms}")
        return True

    def _validate_stream(self, stream: Optional[str]) -> bool:
        """Validate stream (allow any non-empty string or None)."""
        if stream is None or stream == "None":
            return True
        if not isinstance(stream, str) or not stream.strip():
            raise ValueError("Stream must be a non-empty string or None")
        return True

    def _validate_reams(self, reams: int) -> bool:
        """Validate ream quantities (non-negative integer)."""
        if not isinstance(reams, int) or reams < 0:
            raise ValueError("Ream quantities must be a non-negative integer")
        return True

    def _validate_user(self, user: str) -> bool:
        """Validate user (alphanumeric with underscores, 3-20 characters)."""
        if not user or not re.match(r'^[A-Za-z0-9_]{3,20}$', user):
            raise ValueError("User must be 3-20 alphanumeric characters with underscores")
        return True

    def _validate_keyword(self, keyword: str) -> bool:
        """Validate search keyword (2+ characters, no special characters except spaces)."""
        if not keyword or len(keyword) < 2 or not re.match(r'^[A-Za-z0-9\s]+$', keyword):
            raise ValueError("Search keyword must be at least 2 characters and contain only letters, numbers, or spaces")
        return True

    def _get_datetime_format(self) -> str:
        """Fetch datetime_format from settings table."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT datetime_format FROM settings LIMIT 1")
            row = cursor.fetchone()
            if not row:
                raise ValueError("Settings table is empty")
            return row['datetime_format']
        except Exception as e:
            logger.error(f"Error fetching datetime_format: {e}")
            return '%Y-%m-%d %H:%M:%S'  # Fallback to default
        finally:
            self._release_connection(conn)

    def _check_user_auth(self, user: Optional[str], role: Optional[str], action: str) -> bool:
        """Check user authorization based on action."""
        if action in ('fetch_all_students', 'search_students', 'get_student_by_admission', 'get_streams', 'get_ream_required_per_form', 'get_next_form', 'get_total_required'):
            if not user or not role:
                logger.warning(f"{action} called with no user or role, returning empty result")
                return False
            for required_role in {'viewer', 'staff', 'admin'}:
                if self.user_mgr.check_user_role(user, required_role):
                    return True
            logger.warning(f"Access denied: {user} does not have required role for {action}")
            return False
        elif action == 'update_ream_required_per_form':
            if not user or not self.user_mgr.check_user_role(user, 'admin'):
                logger.warning(f"Access denied: {user} does not have admin role for {action}")
                return False
            return True
        self._validate_user(user)
        for required_role in {'staff', 'admin'}:
            if self.user_mgr.check_user_role(user, required_role):
                return True
        logger.warning(f"Access denied: {user} does not have required role for {action}")
        return False

    def _log_audit(self, action: str, user: str, table_name: str, record_id: Optional[int],
               details: str, success: bool = True) -> None:
        with self.edit_lock:
            retries = 3
            for attempt in range(retries):
                conn = None
                try:
                    conn = self._get_connection()  
                    cursor = conn.cursor()
                    operation = {
                        'delete_student': 'DELETE',
                        'bulk_delete_students': 'DELETE',
                        'add_student': 'INSERT',
                        'import_students': 'INSERT',
                        'update_student_info': 'UPDATE',
                        'update_ream_status': 'UPDATE',
                        'update_all_students_status': 'UPDATE',
                        'promote_student': 'PROMOTE',
                        'promote_students': 'PROMOTE',
                        'auto_promote_all': 'PROMOTE',
                        'delete_student': 'DELETE',
                        'bulk_delete_students': 'DELETE',
                        'export_students_to_csv': 'EXPORT',
                        'update_ream_required_per_form': 'SETTINGS'
                    }.get(action, 'DISPLAY')

                    cursor.execute(
                        "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (action, 1 if success else 0, table_name, operation, record_id, user, details)
                    )
                    conn.commit()
                    return
                except sqlite3.Error as e:
                    if conn:
                        conn.rollback()
                    if "locked" in str(e).lower():
                        time.sleep(0.5 * (2 ** attempt))  
                    if attempt == retries - 1:
                        logger.error(f"Failed to log audit after {retries} attempts: {e}")
                finally:
                    if conn:
                        self._release_connection(conn)

    

    def get_streams(self) -> List[str]:
        """Fetch unique streams from the students table."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT stream FROM students WHERE stream IS NOT NULL ORDER BY stream")
            streams = [row['stream'] for row in cursor.fetchall()]
            logger.debug(f"Fetched {len(streams)} unique streams")
            return streams
        except Exception as e:
            logger.error(f"Error fetching streams: {e}")
            return []
        finally:
            self._release_connection(conn)

    def get_ream_required_per_form(self) -> dict:
        """
        Safely fetch ream requirements from settings table.
        Returns default values if DB is empty or corrupted.
        """
        default = {
            "Form 1": 2, "Form 2": 2, "Form 3": 2, "Form 4": 2,
            "Grade 10": 2, "Grade 11": 2, "Grade 12": 2
        }

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT ream_required_per_form FROM settings LIMIT 1")
            row = cursor.fetchone()

            if not row or not row[0]:
                logger.warning("No ream_required_per_form in settings, using defaults")
                return default

            json_str = row[0]
            try:
                data = json.loads(json_str)
                if not isinstance(data, dict):
                    raise ValueError("Not a dict")
                # Validate keys
                valid_keys = {"Form 1", "Form 2", "Form 3", "Form 4", "Grade 10", "Grade 11", "Grade 12"}
                filtered = {k: v for k, v in data.items() if k in valid_keys and isinstance(v, int) and v >= 0}
                if not filtered:
                    raise ValueError("No valid entries")
                logger.info(f"Loaded ream requirements: {filtered}")
                return filtered
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.error(f"Invalid JSON in settings.ream_required_per_form: {e}")
                return default

        except Exception as e:
            logger.error(f"Error reading settings: {e}")
            return default
        finally:
            if conn:
                self._release_connection(conn)

    

    def update_ream_required_per_form(self, ream_required: Dict[str, int], user: str = "system") -> None:
        """Update ream_required_per_form in the settings table."""
        conn = None
        try:
            if not self._check_user_auth(user, 'admin', 'update_ream_required_per_form'):
                raise ValueError("Permission denied: Admin role required")
            for form in self.valid_forms:
                if form not in ream_required:
                    raise ValueError(f"Missing ream requirement for {form}")
                self._validate_reams(ream_required[form])

            ream_required_json = json.dumps(ream_required)
            validate_json(ream_required_json)  

            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE settings SET ream_required_per_form = ?, updated_at = CURRENT_TIMESTAMP WHERE setting_id = (SELECT MAX(setting_id) FROM settings)",
                (ream_required_json,)
            )
            if cursor.rowcount == 0:
                raise ValueError("Settings table is empty or update failed")
            conn.commit()
            logger.info(f"Updated ream_required_per_form by {user}")
            self._log_audit('update_ream_required_per_form', user, 'settings', None, f"Updated ream requirements: {ream_required_json}")
        except Exception as e:
            logger.error(f"Error updating ream_required_per_form: {e}")
            self._log_audit('update_ream_required_per_form', user, 'settings', None, f"Error updating ream requirements: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def get_next_form(self, current_form: str, user: str = "system") -> Optional[str]:
        """Get the next form for promotion."""
        try:
            if not self._check_user_auth(user, 'viewer', 'get_next_form'):
                return None
            self._validate_form(current_form)
            next_form = self.form_progression.get(current_form)
            logger.info(f"Fetched next form for {current_form}: {next_form or 'None'} by {user}")
            self._log_audit('get_next_form', user, 'students', None, f"Fetched next form for {current_form}: {next_form or 'None'}")
            return next_form
        except Exception as e:
            logger.error(f"Error fetching next form for {current_form}: {e}")
            self._log_audit('get_next_form', user, 'students', None, f"Error fetching next form for {current_form}: {e}", False)
            raise

    def fetch_all_students(self, user: Optional[str], role: Optional[str]) -> List[Dict]:
        """Fetch all students as a list of dictionaries, safe for None user/role."""
        conn = None
        try:
            if not self._check_user_auth(user, role, 'fetch_all_students'):
                return []
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students ORDER BY form, name")
            rows = cursor.fetchall()
            students = [
                {
                    'student_id': row['student_id'],
                    'admission_no': row['admission_no'],
                    'name': row['name'],
                    'form': row['form'],
                    'stream': row['stream'],
                    'total_required': row['total_required'],
                    'total_brought': row['total_brought'],
                    'remaining_to_bring': row['remaining_to_bring'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                } for row in rows
            ]
            logger.info(f"Fetched {len(students)} students by {user}")
            self._log_audit('fetch_all_students', user, 'students', None, f"Fetched {len(students)} students")
            return students
        except Exception as e:
            logger.error(f"Error fetching all students: {e}")
            self._log_audit('fetch_all_students', user, 'students', None, f"Error: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def add_student(self, admission_no: str, name: str, form: str, stream: Optional[str] = None,
                total_required: Optional[int] = None, user: str = "system") -> None:
        conn = None
        try:
            if not self._check_user_auth(user, 'staff', 'add_student'):
                raise ValueError("Permission denied: Staff or Admin role required")
            self._validate_admission_no(admission_no)
            self._validate_name(name)
            self._validate_form(form)
            self._validate_stream(stream)

            # === CUMULATIVE REQUIRED ===
            cum_req = get_cumulative_ream_requirements()
            total_required = total_required if total_required is not None else cum_req.get(form, 8)
            self._validate_reams(total_required)

            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO students (admission_no, name, form, stream, total_required, remaining_to_bring)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (admission_no, name, form, stream, total_required, total_required))
            student_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Student '{name}' added with total_required={total_required} (Form: {form})")
            self._log_audit('add_student', user, 'students', student_id, f"Added {admission_no} with cumulative req {total_required}")
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error adding student {admission_no}: {e}")
            self._log_audit('add_student', user, 'students', None, f"Error: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def import_students_from_excel(
        self,
        file_path: str,
        user: str,
        progress_callback=None,
        cancel_event=None
    ) -> dict:
        """
        Import students from Excel with exact column matching.
        Columns: Admission No, Name, Form, Stream, Total Required (optional)
        Uses CUMULATIVE ream requirements from DB if Total Required is missing/invalid.
        """
        result = {"success_count": 0, "errors": []}
        start_time = datetime.now()
        BATCH_SIZE = 100

        try:
            # === 1. Read Excel ===
            if progress_callback:
                progress_callback("Reading Excel file...")
            df = pd.read_excel(file_path)
            total_rows = len(df)
            logger.info(f"Read {total_rows} rows from Excel")
            if total_rows == 0:
                result["errors"].append("Excel file is empty")
                return result

            # === 2. Normalize column names ===
            df.columns = [col.strip() for col in df.columns]
            required_cols = ["Admission No", "Name", "Form"]
            optional_cols = ["Stream", "Total Required"]
            missing = [col for col in required_cols if col not in df.columns]
            if missing:
                result["errors"].append(f"Missing required columns: {', '.join(missing)}")
                return result

            # === 3. Load CUMULATIVE ream requirements from DB ===
            try:
                cumulative_req = get_cumulative_ream_requirements()  # Form 1 → 2, Form 2 → 4, etc.
            except Exception as e:
                result["errors"].append(f"Failed to load ream requirements: {e}")
                logger.error(f"get_cumulative_ream_requirements failed: {e}")
                return result

            valid_forms = set(cumulative_req.keys())

            # === 4. Process in batches ===
            batch = []
            processed = 0
            conn = None

            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                for idx, row in df.iterrows():
                    if cancel_event and cancel_event.is_set():
                        result["errors"].append("Import cancelled by user")
                        break

                    row_num = idx + 2  # Excel row number (1-based + header)

                    # --- Extract & clean ---
                    adm_no = str(row["Admission No"]).strip() if pd.notna(row["Admission No"]) else ""
                    name = str(row["Name"]).strip() if pd.notna(row["Name"]) else ""
                    form = str(row["Form"]).strip() if pd.notna(row["Form"]) else ""
                    stream = str(row.get("Stream", "")).strip() if pd.notna(row.get("Stream")) else None
                    total_req_raw = row.get("Total Required")

                    # --- Validation ---
                    if not adm_no:
                        result["errors"].append(f"Row {row_num}: Admission No missing")
                        continue
                    if not name:
                        result["errors"].append(f"Row {row_num}: Name missing")
                        continue
                    if not form:
                        result["errors"].append(f"Row {row_num}: Form missing")
                        continue
                    if form not in valid_forms:
                        result["errors"].append(f"Row {row_num}: Invalid Form '{form}'. Valid: {', '.join(sorted(valid_forms))}")
                        continue

                    # --- Determine total_required ---
                    # Use Excel value if valid integer ≥0, else use DB cumulative
                    try:
                        excel_val = total_req_raw
                        if pd.notna(excel_val) and str(excel_val).strip().isdigit():
                            total_required = max(0, int(excel_val))  # enforce ≥0
                        else:
                            total_required = cumulative_req[form]
                    except:
                        total_required = cumulative_req[form]  # safe fallback

                    # --- Add to batch ---
                    batch.append((
                        adm_no,
                        name,
                        form,
                        stream,
                        total_required,           # total_required
                        total_required            # remaining_to_bring
                    ))

                    # === Batch Insert ===
                    if len(batch) >= BATCH_SIZE:
                        success = self._insert_student_batch(cursor, batch, result, row_offset=processed + 1)
                        result["success_count"] += success
                        processed += len(batch)
                        if progress_callback:
                            progress_callback(f"Imported {processed}/{total_rows} students...")
                        batch.clear()

                # === Final Batch ===
                if batch:
                    success = self._insert_student_batch(cursor, batch, result, row_offset=processed + 1)
                    result["success_count"] += success
                    processed += len(batch)
                    if progress_callback:
                        progress_callback(f"Imported {processed}/{total_rows} students...")

                conn.commit()
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.info(f"Import completed: {result['success_count']} students in {elapsed:.2f}s")

            except Exception as e:
                if conn:
                    conn.rollback()
                result["errors"].append(f"Database error: {str(e)}")
                logger.error(f"Import DB error: {e}", exc_info=True)

            finally:
                if conn:
                    self._release_connection(conn)

        except Exception as e:
            result["errors"].append(f"File error: {str(e)}")
            logger.error(f"Excel read error: {e}", exc_info=True)

        return result


    def _insert_student_batch(self, cursor, batch: list, result: dict, row_offset: int = 1) -> int:
        """
        Insert batch with UPSERT. On failure, fall back to row-by-row with Excel row numbers.
        """
        success_count = 0
        try:
            cursor.executemany("""
                INSERT INTO students
                (admission_no, name, form, stream, total_required, total_brought, remaining_to_bring, status)
                VALUES (?, ?, ?, ?, ?, 0, ?, 'Behind')
                ON CONFLICT(admission_no) DO UPDATE SET
                    name = excluded.name,
                    form = excluded.form,
                    stream = excluded.stream,
                    total_required = excluded.total_required,
                    remaining_to_bring = excluded.total_required - total_brought
            """, batch)
            success_count = len(batch)
        except sqlite3.Error as e:
            logger.warning(f"Batch insert failed, retrying row-by-row: {e}")
            for i, row in enumerate(batch):
                adm_no = row[0]
                excel_row = row_offset + i
                try:
                    cursor.execute("""
                        INSERT INTO students
                        (admission_no, name, form, stream, total_required, total_brought, remaining_to_bring, status)
                        VALUES (?, ?, ?, ?, ?, 0, ?, 'Behind')
                        ON CONFLICT(admission_no) DO UPDATE SET
                            name = excluded.name,
                            form = excluded.form,
                            stream = excluded.stream,
                            total_required = excluded.total_required,
                            remaining_to_bring = excluded.total_required - total_brought
                    """, row)
                    success_count += 1
                except sqlite3.Error as row_e:
                    result["errors"].append(f"Excel Row {excel_row} (Adm: {adm_no}): {str(row_e)}")
        return success_count

    def export_students_to_csv(self, file_path: str = "students_export.csv", user: str = "system") -> None:
        """Export all students to a CSV file."""
        conn = None
        try:
            if not self._check_user_auth(user, 'viewer', 'export_students'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")
            students = self.fetch_all_students(user, 'viewer')
            df = pd.DataFrame(students, columns=['student_id', 'admission_no', 'name', 'form', 'stream',
                                                'total_required', 'total_brought', 'remaining_to_bring',
                                                'status', 'created_at', 'updated_at'])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)  # NEW: Ensure directory exists
            df.to_csv(file_path, index=False)
            logger.info(f"Exported {len(students)} students to {file_path} by {user}")
            self._log_audit('export_students', user, 'students', None, f"Exported {len(students)} students to {file_path}")
        except Exception as e:
            logger.error(f"Error exporting students to {file_path}: {e}")
            self._log_audit('export_students', user, 'students', None, f"Error exporting students to {file_path}: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def get_student_by_admission(self, admission_no: str, user: str = "system") -> Optional[Dict]:
        """Fetch a single student by admission number."""
        conn = None
        try:
            if not self._check_user_auth(user, 'viewer', 'get_student_by_admission'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")
            self._validate_admission_no(admission_no)
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM students WHERE admission_no = ?", (admission_no,))
            row = cursor.fetchone()
            if row:
                student = {
                    'student_id': row['student_id'],
                    'admission_no': row['admission_no'],
                    'name': row['name'],
                    'form': row['form'],
                    'stream': row['stream'],
                    'total_required': row['total_required'],
                    'total_brought': row['total_brought'],
                    'remaining_to_bring': row['remaining_to_bring'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
                logger.info(f"Fetched student {admission_no} by {user}")
                self._log_audit('get_student_by_admission', user, 'students', row['student_id'], f"Fetched student {admission_no}")
                return student
            return None
        except Exception as e:
            logger.error(f"Error fetching student {admission_no}: {e}")
            self._log_audit('get_student_by_admission', user, 'students', None, f"Error fetching student {admission_no}: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def update_student_info(self, admission_no: str, name: Optional[str] = None, form: Optional[str] = None,
                       stream: Optional[str] = None, total_required: Optional[int] = None,
                       user: str = "system") -> None:
        conn = None
        try:
            if not self._check_user_auth(user, 'staff', 'update_student_info'):
                raise ValueError("Permission denied")
            self._validate_admission_no(admission_no)

            updates = []
            values = []

            if name is not None:
                self._validate_name(name)
                updates.append("name = ?")
                values.append(name)

            if form is not None:
                self._validate_form(form)
                cum_req = get_cumulative_ream_requirements()
                new_total = cum_req.get(form, 8)
                updates.append("form = ?")
                values.append(form)
                updates.append("total_required = ?")
                values.append(new_total)
                updates.append("remaining_to_bring = ? - total_brought")
                values.append(new_total)

            if stream is not None:
                self._validate_stream(stream)
                updates.append("stream = ?")
                values.append(stream)

            if total_required is not None and form is None:
                self._validate_reams(total_required)
                updates.append("total_required = ?")
                values.append(total_required)
                updates.append("remaining_to_bring = ? - total_brought")
                values.append(total_required)

            if not updates:
                raise ValueError("No updates provided")

            values.append(admission_no)
            query = f"UPDATE students SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE admission_no = ?"

            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, tuple(values))
            if cursor.rowcount == 0:
                raise ValueError(f"Student {admission_no} not found")
            conn.commit()
            logger.info(f"Updated {admission_no} -> Form: {form}, Total: {total_required}")
            self._log_audit('update_student_info', user, 'students', None, f"Updated {admission_no}")
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error updating student {admission_no}: {e}")
            self._log_audit('update_student_info', user, 'students', None, f"Error: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def delete_student(self, admission_no: str, user: str = "system") -> None:
        """Delete a single student."""
        conn = None
        try:
            if not self._check_user_auth(user, 'staff', 'delete_student'):
                raise ValueError("Permission denied: Staff or Admin role required")
            self._validate_admission_no(admission_no)
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT student_id FROM students WHERE admission_no = ?", (admission_no,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Student with admission number {admission_no} not found")
            student_id = row['student_id']
            cursor.execute("DELETE FROM students WHERE admission_no = ?", (admission_no,))
            conn.commit()
            logger.info(f"Deleted student {admission_no} by {user}")
            self._log_audit('delete_student', user, 'students', student_id, f"Deleted student {admission_no}")
        except Exception as e:
            logger.error(f"Error deleting student {admission_no}: {e}")
            self._log_audit('delete_student', user, 'students', None, f"Error deleting student {admission_no}: {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def bulk_delete_students(self, admission_numbers: List[str], user: str = "system") -> Dict:
        conn = None
        audit_actions = []
        try:
            if not self._check_user_auth(user, 'staff', 'bulk_delete_students'):
                raise ValueError("Permission denied: Staff or Admin role required")
            if not admission_numbers:
                raise ValueError("Admission numbers list cannot be empty")

            for admission_no in admission_numbers:
                self._validate_admission_no(admission_no.strip())  # strip!

            conn = self._get_connection()
            cursor = conn.cursor()
            success_count = 0
            errors = []

            placeholders = ','.join('?' for _ in admission_numbers)
            cursor.execute(
                f"SELECT admission_no, student_id FROM students WHERE admission_no IN ({placeholders})",
                admission_numbers
            )
            rows = cursor.fetchall()
            existing = {row['admission_no']: row['student_id'] for row in rows}  

            not_found = set(admission_numbers) - set(existing.keys())
            for admission_no in not_found:
                errors.append(f"Student {admission_no} not found")

            for admission_no, student_id in existing.items():
                try:
                    # DELETE FROM reams_brought USING student_id
                    cursor.execute("DELETE FROM reams_brought WHERE student_id = ?", (student_id,))
                    deleted_reams = cursor.rowcount
                    logger.info(f"Deleted {deleted_reams} ream records for student_id {student_id}")

                    # THEN DELETE STUDENT
                    cursor.execute("DELETE FROM students WHERE admission_no = ?", (admission_no,))
                    if cursor.rowcount == 0:
                        raise ValueError("Student delete failed")

                    success_count += 1
                    logger.info(f"Deleted student {admission_no} (ID: {student_id}) by {user}")

                    audit_actions.append({
                        'action': 'delete_student',
                        'user': user,
                        'table_name': 'students',
                        'record_id': student_id,
                        'details': f"Deleted student {admission_no} and {deleted_reams} reams",
                        'success': True
                    })

                except Exception as e:
                    errors.append(f"Student {admission_no}: {str(e)}")
                    audit_actions.append({
                        'action': 'delete_student',
                        'user': user,
                        'table_name': 'students',
                        'record_id': student_id,
                        'details': f"Failed: {e}",
                        'success': False
                    })

            conn.commit()

            # Log audit AFTER commit
            for act in audit_actions:
                self._log_audit(**act)

            self._log_audit(
                'bulk_delete_students', user, 'students', None,
                f"Deleted {success_count} students", True
            )

            return {"success_count": success_count, "errors": errors}

        except Exception as e:
            if conn:
                conn.rollback()
            self._log_audit('bulk_delete_students', user, 'students', None, f"Error: {e}", False)
            logger.error(f"Bulk delete error: {e}")
            raise
        finally:
            if conn:
                self._release_connection(conn)

    def update_ream_status(self, student_id: int, user: str = "system", role: str = "staff") -> None:
        """
        Recalculate ream status for ONE student.
        - Allows NEGATIVE remaining_to_bring
        - Status: Ahead, On Track, Behind, Complete
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'update_ream_status'):
                raise ValueError("Permission denied")
            if not isinstance(student_id, int) or student_id <= 0:
                raise ValueError("Invalid student ID")

            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. Get total_brought ===
            cursor.execute("SELECT COALESCE(SUM(quantity), 0) FROM reams_brought WHERE student_id = ?", (student_id,))
            total_brought = cursor.fetchone()[0]

            # === 2. Get student + current total_required ===
            cursor.execute("""
                SELECT form, total_required 
                FROM students 
                WHERE student_id = ?
            """, (student_id,))
            result = cursor.fetchone()
            if not result:
                raise ValueError("Student not found")
            form, total_required = result

            # === 3. CUMULATIVE REQUIRED (fallback if not set) ===
            cum_req = get_cumulative_ream_requirements()
            expected_required = cum_req.get(form, 8)
            total_required = total_required or expected_required  # Use DB value if set

            # === 4. Calculate remaining (CAN BE NEGATIVE) ===
            remaining_to_bring = total_required - total_brought  # e.g., -3

            # === 5. Smart status ===
            if remaining_to_bring > 0:
                status = "Behind"
            elif remaining_to_bring == 0:
                status = "On Track"
            else:
                status = "Ahead"  # Brought extra!

            # === 6. Update student ===
            cursor.execute("""
                UPDATE students
                SET total_brought = ?,
                    total_required = ?,
                    remaining_to_bring = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE student_id = ?
            """, (total_brought, total_required, remaining_to_bring, status, student_id))

            conn.commit()
            logger.info(f"Updated status for student {student_id}: {status} (remaining: {remaining_to_bring})")
            self._log_audit('update_ream_status', user, 'students', student_id, f"Status: {status}, remaining: {remaining_to_bring}")

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error updating status for {student_id}: {e}")
            self._log_audit('update_ream_status', user, 'students', student_id, f"Error: {e}", False)
            raise
        finally:
            if conn:
                self._release_connection(conn)


    def update_all_students_status(self, user: str = "system", role: str = "staff") -> None:
        """
        Recalculate ream status for ALL students in ONE transaction.
        - Supports NEGATIVE remaining
        - Fixes incorrect total_required
        - Smart status: Ahead, On Track, Behind
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'update_all_students_status'):
                raise ValueError("Permission denied")

            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. CUMULATIVE REQUIREMENTS ===
            cum_req = get_cumulative_ream_requirements()

            # === 2. Fetch all students + total_brought ===
            cursor.execute("""
                SELECT
                    s.student_id,
                    s.form,
                    s.total_required,
                    COALESCE(SUM(r.quantity), 0) AS total_brought
                FROM students s
                LEFT JOIN reams_brought r ON s.student_id = r.student_id
                GROUP BY s.student_id
            """)
            rows = cursor.fetchall()
            update_count = 0

            for row in rows:
                student_id = row['student_id']
                form = row['form']
                current_required = row['total_required'] or 0
                total_brought = row['total_brought']

                # === 3. Use cumulative required (unless manually overridden) ===
                expected_required = cum_req.get(form, 8)
                total_required = current_required if current_required > 0 else expected_required

                # Log correction
                if current_required != total_required:
                    logger.info(f"Corrected total_required for student ID {student_id} from {current_required} to {total_required}")

                # === 4. Allow NEGATIVE remaining ===
                remaining_to_bring = total_required - total_brought

                # === 5. Smart status ===
                if remaining_to_bring > 0:
                    status = "Behind"
                elif remaining_to_bring == 0:
                    status = "On Track"
                else:
                    status = "Ahead"

                # === 6. Update ===
                cursor.execute("""
                    UPDATE students
                    SET total_brought = ?,
                        total_required = ?,
                        remaining_to_bring = ?,
                        status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE student_id = ?
                """, (total_brought, total_required, remaining_to_bring, status, student_id))
                update_count += 1

            conn.commit()
            logger.info(f"Updated ream status for {update_count} students by {user}")
            self._log_audit('update_all_students_status', user, 'students', None, f"Updated {update_count} students")

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error in update_all_students_status: {e}")
            self._log_audit('update_all_students_status', user, 'students', None, f"Error: {e}", False)
            raise
        finally:
            if conn:
                self._release_connection(conn)

    def search_students(self, keyword: str, user: str = "system", field: Optional[str] = None) -> List[Dict]:
        """Search students by keyword, optionally by specific field."""
        conn = None
        try:
            if not self._check_user_auth(user, 'viewer', 'search_students'):
                return []
            self._validate_keyword(keyword)
            conn = self._get_connection()
            cursor = conn.cursor()
            query = """
                SELECT * FROM students
                WHERE name LIKE ? OR admission_no LIKE ? OR form LIKE ? OR stream LIKE ?
            """
            params = (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
            if field:
                valid_fields = {'adm no': 'admission_no', 'name': 'name', 'form': 'form', 'stream': 'stream'}
                if field.lower() not in valid_fields:
                    raise ValueError(f"Invalid search field: {field}")
                query = f"SELECT * FROM students WHERE {valid_fields[field.lower()]} LIKE ?"
                params = (f"%{keyword}%",)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            students = [
                {
                    'student_id': row['student_id'],
                    'admission_no': row['admission_no'],
                    'name': row['name'],
                    'form': row['form'],
                    'stream': row['stream'],
                    'total_required': row['total_required'],
                    'total_brought': row['total_brought'],
                    'remaining_to_bring': row['remaining_to_bring'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                } for row in rows
            ]
            logger.info(f"Searched students with keyword '{keyword}' by {user}")
            self._log_audit('search_students', user, 'students', None, f"Searched students with keyword '{keyword}'")
            return students
        except Exception as e:
            logger.error(f"Error searching students with keyword '{keyword}': {e}")
            self._log_audit('search_students', user, 'students', None, f"Error searching students with keyword '{keyword}': {e}", False)
            raise
        finally:
            self._release_connection(conn)

    def promote_student(self, admission_no: str, user: str = "system", role: str = "staff") -> None:
        """
        Promote ONE student to next form.
        - Carries excess reams forward (negative remaining)
        - Sets new total_required based on cumulative
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'promote_student'):
                raise ValueError("Permission denied: Staff or Admin required")

            self._validate_admission_no(admission_no)
            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. Fetch current student data ===
            cursor.execute("""
                SELECT student_id, form, stream, total_brought, total_required, remaining_to_bring
                FROM students WHERE admission_no = ?
            """, (admission_no,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Student {admission_no} not found")

            student_id, current_form, stream, total_brought, total_required_db, current_remaining = row

            # === 2. Validate promotion path ===
            if current_form in {'Form 4', 'Grade 12'}:
                raise ValueError(f"Cannot promote {current_form}: This is the final year")
            next_form = self.form_progression.get(current_form)
            if not next_form:
                raise ValueError(f"No promotion path from {current_form}")

            # === 3. CUMULATIVE REQUIRED FOR NEXT FORM ===
            cum_req = get_cumulative_ream_requirements()
            new_total_required = cum_req.get(next_form, 8)

            # === 4. CARRY EXCESS FORWARD ===
            excess = max(0, -current_remaining)  # e.g., -3 → 3 excess
            effective_required = max(0, new_total_required - excess)  # e.g., 8 - 3 = 5

            # === 5. Update student ===
            cursor.execute("""
                UPDATE students
                SET form = ?,
                    stream = ?,
                    total_required = ?,
                    total_brought = 0,  -- Reset brought (excess already applied)
                    remaining_to_bring = ?,
                    status = CASE
                        WHEN ? > 0 THEN 'Behind'
                        WHEN ? = 0 THEN 'On Track'
                        ELSE 'Ahead'
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE admission_no = ?
            """, (
                next_form, stream,
                new_total_required, effective_required,
                effective_required, effective_required,
                admission_no
            ))

            conn.commit()
            logger.info(
                f"Promoted {admission_no}: {current_form} → {next_form} | "
                f"Excess: {excess}, New required: {new_total_required}, Remaining: {effective_required}"
            )
            self._log_audit(
                'promote_student', user, 'students', student_id,
                f"Promoted {admission_no}: {current_form}→{next_form}, "
                f"excess={excess}, req={new_total_required}, remaining={effective_required}"
            )

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error promoting student {admission_no}: {e}")
            self._log_audit('promote_student', user, 'students', None, f"Error: {e}", False)
            raise
        finally:
            if conn:
                self._release_connection(conn)


    def promote_students(
        self,
        admission_numbers: Optional[List[str]] = None,
        form: Optional[str] = None,
        user: str = "system",
        role: str = "staff"
    ) -> Dict:
        """
        Promote multiple students.
        - Carries excess reams forward
        - Bulk audit logging
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'promote_students'):
                raise ValueError("Permission denied")

            if not admission_numbers and not form:
                raise ValueError("Provide admission_numbers or form")

            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. CUMULATIVE REQUIREMENTS ===
            cum_req = get_cumulative_ream_requirements()

            # === 2. Fetch students ===
            if admission_numbers:
                for adm in admission_numbers:
                    self._validate_admission_no(adm)
                placeholders = ','.join('?' for _ in admission_numbers)
                cursor.execute(
                    f"SELECT student_id, admission_no, form, stream, remaining_to_bring FROM students WHERE admission_no IN ({placeholders})",
                    admission_numbers
                )
            else:
                self._validate_form(form)
                cursor.execute(
                    "SELECT student_id, admission_no, form, stream, remaining_to_bring FROM students WHERE form = ?",
                    (form,)
                )
            students = cursor.fetchall()
            if not students:
                return {"success_count": 0, "errors": ["No students found"]}

            success = 0
            errors = []

            for sid, adm, current_form, stream, current_remaining in students:
                try:
                    if current_form in {'Form 4', 'Grade 12'}:
                        raise ValueError("Final year — cannot promote")

                    next_form = self.form_progression.get(current_form)
                    if not next_form:
                        raise ValueError(f"No promotion path from {current_form}")

                    new_total_required = cum_req.get(next_form, 8)
                    excess = max(0, -current_remaining)
                    effective_required = max(0, new_total_required - excess)

                    cursor.execute("""
                        UPDATE students
                        SET form = ?, stream = ?, total_required = ?, total_brought = 0,
                            remaining_to_bring = ?,
                            status = CASE WHEN ? > 0 THEN 'Behind' WHEN ? = 0 THEN 'On Track' ELSE 'Ahead' END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE admission_no = ?
                    """, (next_form, stream, new_total_required, effective_required, effective_required, effective_required, adm))

                    success += 1

                    # Per-student audit
                    cursor.execute(
                        "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ('promote_student', 1, 'students', 'PROMOTE', sid, user,
                         f"{adm}: {current_form}→{next_form}, excess={excess}, req={new_total_required}, remaining={effective_required}")
                    )

                except Exception as e:
                    error_msg = f"{adm}: {e}"
                    errors.append(error_msg)
                    cursor.execute(
                        "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ('promote_student', 0, 'students', 'PROMOTE', sid, user, f"Failed: {e}")
                    )

            # === 3. Final bulk log ===
            cursor.execute(
                "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('promote_students', 1, 'students', 'PROMOTE', None, user, f"Promoted {success} students")
            )
            conn.commit()

            return {"success_count": success, "errors": errors}

        except Exception as e:
            if conn:
                conn.rollback()
            # Log failure
            try:
                fail_conn = self._get_connection()
                fail_cur = fail_conn.cursor()
                fail_cur.execute(
                    "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ('promote_students', 0, 'students', 'PROMOTE', None, user, f"Error: {e}")
                )
                fail_conn.commit()
                self._release_connection(fail_conn)
            except:
                pass
            raise
        finally:
            if conn:
                self._release_connection(conn)

    def auto_promote_all(self, user: str = "system", role: str = "admin") -> Dict:
        """
        Auto-promote ALL students at end of Term 3.
        - Carries excess reams forward (negative remaining)
        - Skips Form 4 & Grade 12
        - Resets total_brought
        - Updates status: Ahead, On Track, Behind
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'auto_promote_all'):
                raise ValueError("Admin access only")

            current_term = get_term_from_date(None)
            if current_term != 'Term 3':
                reason = f"Skipped: Current term is {current_term}, not Term 3"
                logger.info(reason)
                return {
                    "success_count": 0,
                    "skipped": True,
                    "reason": reason,
                    "term": current_term
                }

            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. CUMULATIVE REQUIREMENTS ===
            cum_req = get_cumulative_ream_requirements()
            if not cum_req:
                raise ValueError("Cumulative ream requirements not configured")

            # === 2. Fetch promotable students (exclude final years) ===
            cursor.execute("""
                SELECT student_id, admission_no, form, stream, remaining_to_bring, total_required
                FROM students
                WHERE form NOT IN ('Form 4', 'Grade 12')
            """)
            students = cursor.fetchall()
            if not students:
                return {
                    "success_count": 0,
                    "skipped": True,
                    "reason": "No promotable students (all in final year)"
                }

            success = 0
            errors = []
            excess_carried = 0

            for sid, adm, current_form, stream, current_remaining, current_total_req in students:
                try:
                    next_form = self.form_progression.get(current_form)
                    if not next_form:
                        errors.append(f"{adm}: No promotion path from {current_form}")
                        continue

                    new_total_required = cum_req.get(next_form, 8)
                    excess = max(0, -current_remaining)  # e.g., -3 → 3
                    effective_remaining = max(0, new_total_required - excess)

                    # === Smart status ===
                    if effective_remaining > 0:
                        status = "Behind"
                    elif effective_remaining == 0:
                        status = "On Track"
                    else:
                        status = "Ahead"

                    cursor.execute("""
                        UPDATE students
                        SET form = ?,
                            stream = ?,
                            total_required = ?,
                            total_brought = 0,
                            remaining_to_bring = ?,
                            status = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE student_id = ?
                    """, (
                        next_form, stream,
                        new_total_required,
                        effective_remaining,
                        status,
                        sid
                    ))

                    success += 1
                    excess_carried += excess

                    # Per-student audit
                    cursor.execute(
                        "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ('auto_promote_all', 1, 'students', 'PROMOTE', sid, user,
                         f"{adm}: {current_form}→{next_form}, excess={excess}, req={new_total_required}, remaining={effective_remaining}")
                    )

                except Exception as e:
                    error_msg = f"{adm}: {e}"
                    errors.append(error_msg)
                    cursor.execute(
                        "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ('auto_promote_all', 0, 'students', 'PROMOTE', sid, user, f"Failed: {e}")
                    )

            # === 3. Final bulk audit ===
            cursor.execute(
                "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('auto_promote_all', 1, 'students', 'PROMOTE', None, user,
                 f"Auto-promoted {success} students (Term 3), excess carried: {excess_carried} reams")
            )

            conn.commit()
            logger.info(f"AUTO-PROMOTION: Promoted {success} students, carried {excess_carried} excess reams")

            return {
                "success_count": success,
                "errors": errors,
                "excess_carried_reams": excess_carried,
                "term": current_term,
                "final_years_skipped": "Form 4, Grade 12"
            }

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error in auto_promote_all: {e}")
            # Log failure
            try:
                fail_conn = self._get_connection()
                fail_cur = fail_conn.cursor()
                fail_cur.execute(
                    "INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ('auto_promote_all', 0, 'students', 'PROMOTE', None, user, f"Error: {e}")
                )
                fail_conn.commit()
                self._release_connection(fail_conn)
            except:
                pass
            raise
        finally:
            if conn:
                self._release_connection(conn)