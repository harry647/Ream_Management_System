import sqlite3
import pandas as pd
import logging
from datetime import datetime
import re
import os
import sys
import subprocess
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from tkinter import filedialog, Tk
from typing import List, Optional, Dict, Union
from modules.db_setup import (
    backup_database,
    get_cumulative_ream_requirements,
    get_term_from_date,
    get_db_pool
)
from modules.student_manager import StudentManager
from modules.user_manager import UserManager
from pylatex import Document, Section, Subsection, Tabular, Package, Command
from pylatex.utils import NoEscape
import threading
import json

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ream_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_NAME = "database/ream_management.db"

# Uses global db_pool from db_setup.py

class ReamManager:
    def __init__(self, db_name: str = DB_NAME):
        self.db_name = db_name
        self.student_manager = StudentManager(db_name)
        self.user_manager = UserManager(db_name)
        self.edit_lock = threading.Lock()
        self.valid_terms = {'Term 1', 'Term 2', 'Term 3'}
        self.valid_forms = {'Form 1', 'Form 2', 'Form 3', 'Form 4', 'Grade 10', 'Grade 11', 'Grade 12'}
        self.valid_departments = {'Mathematics', 'Sciences', 'Languages', 'Humanities', 'Technical', 'Library', 'Administration', 'Exams', 'Store'}
        logger.debug("ReamManager initialized")

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

    def _validate_quantity(self, quantity: int) -> bool:
        """Validate ream quantity (non-negative integer)."""
        if not isinstance(quantity, int) or quantity < 0:
            raise ValueError("Quantity must be a non-negative integer")
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
        streams = self.student_manager.get_streams()
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

    def _check_user_auth(self, user: Optional[str], role: Optional[str], action: str) -> bool:
        """Check user authorization based on action."""
        if action in ('fetch_all_records', 'search_records', 'get_record_by_id', 'fetch_purchase_records', 'get_streams', 'get_min_stock_alert', 'get_total_reams', 'get_ream_required_per_form', 'get_total_required', 'get_ream_contribution_report', 'export_ream_report_to_pdf'):
            if not user or not role:
                logger.warning(f"{action} called with no user or role, returning empty result")
                return False
            for required_role in {'viewer', 'staff', 'admin'}:
                if self.user_manager.check_user_role(user, required_role):
                    return True
            logger.warning(f"Access denied: {user} does not have required role for {action}")
            return False
        self._validate_user(user)
        for required_role in {'staff', 'admin'}:
            if self.user_manager.check_user_role(user, required_role):
                return True
        logger.warning(f"Access denied: {user} does not have required role for {action}")
        return False

    def _log_audit(
        self,
        action: str,
        user: str,
        table_name: str,
        record_id: Optional[int],
        details: str,
        success: bool = True,
        conn=None  # ← ADD THIS LINE
    ) -> None:
        """Log an action to the audit_log table."""
        close_conn = False
        if conn is None:
            conn = self._get_connection()
            close_conn = True

        cursor = conn.cursor()
        try:
            valid_operations = {'INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'DISPLAY', 'REPORT', 'EXPORT'}
            fetch_actions = {
                'fetch_all_records', 'get_record_by_id', 'fetch_purchase_records',
                'search_records', 'get_streams', 'get_min_stock_alert', 'get_total_reams',
                'get_ream_required_per_form', 'get_total_required', 'get_ream_contribution_report',
                'get_purchase_by_id'
            }
            insert_actions = {'record_ream', 'add_purchase'}
            delete_actions = {'delete_record', 'delete_purchase'}
            report_actions = {'get_ream_contribution_report'}
            export_actions = {'export_ream_report_to_pdf', 'backup_ream_database'}

            if action in fetch_actions:
                operation = 'DISPLAY'
            elif action in insert_actions:
                operation = 'INSERT'
            elif action in delete_actions:
                operation = 'DELETE'
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
            if close_conn:
                self._release_connection(conn)

    def _log_audit_with_conn(self, conn, action: str, user: str, table_name: str,
                             record_id: Optional[int], details: str, success: bool = True):
        try:
            cursor = conn.cursor()
            operation = {'add_purchase': 'INSERT', 'record_ream': 'INSERT'}.get(action, 'OTHER')
            cursor.execute("""
                INSERT INTO audit_log (action, success, table_name, operation, record_id, user, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (action, 1 if success else 0, table_name, operation, record_id, user, details))
        except Exception as e:
            logger.warning(f"Failed to log audit in same connection: {e}")
            

    def _check_stock_alert(self, conn: sqlite3.Connection) -> tuple[int, int]:
        """Check if stock is below the minimum alert threshold."""
        cursor = conn.cursor()
        cursor.execute("SELECT min_stock_alert FROM settings LIMIT 1")
        result = cursor.fetchone()
        min_stock = result[0] if result else 10
        cursor.execute("SELECT current_balance FROM ream_stock_summary ORDER BY summary_id DESC LIMIT 1")
        result = cursor.fetchone()
        total_reams = result[0] if result else 0
        if total_reams < min_stock:
            logger.warning(f"Low Stock Alert! Only {total_reams} reams remaining (threshold: {min_stock})")
        return total_reams, min_stock

    def get_ream_required_per_form(self, user: str, role: str) -> Dict[str, int]:
        """Fetch **CUMULATIVE** ream requirements per form."""
        try:
            if not self._check_user_auth(user, role, 'get_ream_required_per_form'):
                return {}
            
            # Use cumulative logic from db_setup
            cum_req = get_cumulative_ream_requirements()
            logger.info(f"Fetched cumulative ream requirements by {user}: {cum_req}")
            self._log_audit('get_ream_required_per_form', user, 'settings', None, "Fetched cumulative ream requirements")
            return cum_req
        except Exception as e:
            logger.error(f"Error fetching cumulative ream requirements: {e}")
            self._log_audit('get_ream_required_per_form', user, 'settings', None, f"Error: {e}", False)
            raise

    def get_total_required(self, user: str, role: str) -> int:
        """Return total required for **final year** (Form 4 / Grade 12) — cumulative."""
        try:
            if not self._check_user_auth(user, role, 'get_total_required'):
                return 8  # fallback

            cum_req = get_cumulative_ream_requirements()
            # Final years: Form 4 and Grade 12
            final_forms = {'Form 4', 'Grade 12'}
            total = max(cum_req.get(form, 8) for form in final_forms)
            
            self._log_audit('get_total_required', user, 'settings', None, f"Fetched final-year total: {total}")
            logger.info(f"Fetched final-year total_required ({total}) by {user}")
            return total
        except Exception as e:
            logger.error(f"Error fetching final-year total_required: {e}")
            self._log_audit('get_total_required', user, 'settings', None, f"Error: {e}", False)
            raise


    def get_streams(self) -> List[str]:
        """Fetch unique streams from the students table via StudentManager."""
        try:
            streams = self.student_manager.get_streams()
            logger.debug(f"Fetched {len(streams)} unique streams")
            return streams
        except Exception as e:
            logger.error(f"Error fetching streams: {e}")
            return []

    def add_purchase(self, quantity: int, supplier: str, invoice_no: str, user: str, role: str,
                 recorded_by: Optional[str] = None, remarks: Optional[str] = None) -> None:
        conn = None
        try:
            if not self._check_user_auth(user, role, 'add_purchase'):
                raise ValueError("Permission denied: Staff or Admin role required")
            self._validate_quantity(quantity)
            self._validate_supplier(supplier)
            self._validate_invoice_no(invoice_no)
            self._validate_recorded_by(recorded_by)

            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                purchase_date = datetime.now().strftime("%Y-%m-%d")

                # 1. Insert purchase
                cursor.execute("""
                    INSERT INTO reams_purchased (quantity, supplier, invoice_no, purchase_date, recorded_by, remarks)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (quantity, supplier, invoice_no, purchase_date, recorded_by, remarks))
                purchase_id = cursor.lastrowid

                # 2. Log audit IN SAME CONNECTION
                self._log_audit_with_conn(
                    conn, 'add_purchase', user, 'reams_purchased', purchase_id,
                    f"Recorded purchase of {quantity} reams from {supplier} (invoice {invoice_no}) on {purchase_date}"
                )

                # 3. Check stock
                self._check_stock_alert(conn)

                # 4. Commit
                conn.commit()
                logger.info(f"Recorded purchase of {quantity} reams from {supplier} (invoice {invoice_no}) by {user}")

            except sqlite3.IntegrityError as e:
                conn.rollback()
                error_msg = f"Invoice number {invoice_no} already exists"
                self._log_audit_with_conn(conn, 'add_purchase', user, 'reams_purchased', None, error_msg, False)
                raise ValueError(error_msg)
            except Exception as e:
                conn.rollback()
                self._log_audit_with_conn(conn, 'add_purchase', user, 'reams_purchased', None, f"Error: {e}", False)
                raise
            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error in add_purchase for invoice {invoice_no}: {e}")
            raise


    def import_reams_from_excel(
        self,
        file_path: str,
        user: str,
        role: str,
        progress_callback=None,
        cancel_event=None
    ) -> Dict[str, any]:
        """
        Import reams brought from Excel.
        - Allows NEGATIVE remaining_to_bring → excess carried to next form
        - No limit on quantity per row
        - Generates PDF for missing students
        """
        result = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
            "skipped": [],
            "missing_students": [],
            "missing_pdf_path": None
        }
        BATCH_SIZE = 100
        missing_students = []  # (adm_no, quantity, date_brought)
        try:
            if not self._check_user_auth(user, role, 'record_ream'):
                raise PermissionError("Permission denied: Staff or Admin required")

            # === 1. READ EXCEL ===
            if progress_callback:
                progress_callback("Reading Excel file...")
            df = pd.read_excel(file_path, dtype=str)
            df = df.dropna(how='all')
            total_rows = len(df)
            if total_rows == 0:
                result["errors"].append("Excel file is empty or contains no data")
                return result

            # === 2. NORMALIZE COLUMNS ===
            if progress_callback:
                progress_callback("Validating columns...")
            df.columns = [col.strip() for col in df.columns]
            column_map = {
                "Admission No": "Admission No", "Adm No": "Admission No", "Student ID": "Admission No",
                "Admission": "Admission No", "Adm. No": "Admission No", "ID": "Admission No",
                "Reams Brought": "Quantity", "Quantity": "Quantity", "Reams": "Quantity", "Qty": "Quantity",
                "Reams_Brought": "Quantity",
                "Date": "Date Brought", "Date Brought": "Date Brought", "Brought Date": "Date Brought",
                "Date of Bringing": "Date Brought", "Brought_Date": "Date Brought",
                "Term": "Term", "Form": "Form", "Recorded By": "Recorded By", "Recorded_By": "Recorded By"
            }
            df.rename(columns=column_map, inplace=True)
            required = ["Admission No", "Quantity", "Date Brought"]
            missing = [c for c in required if c not in df.columns]
            if missing:
                found = list(df.columns)
                result["errors"].append(
                    f"Missing required columns: {', '.join(missing)}\n"
                    f"Found: {', '.join(found)}\n"
                    "Supported:\n"
                    "• Admission No: 'Admission No', 'Adm No', 'ID'\n"
                    "• Quantity: 'Reams Brought', 'Quantity', 'Qty'\n"
                    "• Date: 'Date', 'Date Brought'"
                )
                return result

            # === 3. LOAD CUMULATIVE REQUIREMENTS ===
            try:
                cum_req = get_cumulative_ream_requirements()
            except Exception as e:
                result["errors"].append(f"Failed to load ream requirements: {e}")
                return result

            # === 4. DATABASE CONNECTION ===
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # === 5. CLEAR EXISTING DATA ===
                #cursor.execute("DELETE FROM reams_brought")
                #logger.info("Cleared existing reams_brought data for import.")

                # === 6. PROCESS EACH ROW (ALLOW NEGATIVE REMAINING) ===
                batch = []
                processed = 0
                for idx, row in df.iterrows():
                    if cancel_event and cancel_event.is_set():
                        result["errors"].append("Import cancelled by user")
                        break

                    row_num = idx + 2
                    raw_adm = row["Admission No"]
                    raw_qty = row["Quantity"]
                    raw_date = row["Date Brought"]

                    # --- SKIP EMPTY ADMISSION NO ---
                    if pd.isna(raw_adm) or str(raw_adm).strip() in ['', 'nan']:
                        result["skipped"].append(f"Row {row_num}: Empty Admission No")
                        result["error_count"] += 1
                        continue
                    adm_no = str(raw_adm).strip()
                    if not re.match(r'^[A-Za-z0-9]{1,20}$', adm_no):
                        result["errors"].append(f"Row {row_num}: Invalid Admission No '{adm_no}'")
                        result["error_count"] += 1
                        continue

                    # --- QUANTITY ---
                    try:
                        quantity = int(float(raw_qty))
                        if quantity <= 0:
                            raise ValueError()
                    except:
                        result["errors"].append(f"Row {row_num}: Invalid Quantity '{raw_qty}'")
                        result["error_count"] += 1
                        continue

                    # --- DATE ---
                    try:
                        date_obj = pd.to_datetime(raw_date, errors='coerce')
                        if pd.isna(date_obj):
                            raise ValueError()
                        date_brought = date_obj.strftime("%Y-%m-%d")
                    except:
                        result["errors"].append(f"Row {row_num}: Invalid Date '{raw_date}' (use YYYY-MM-DD)")
                        result["error_count"] += 1
                        continue

                    # --- TERM & FORM ---
                    term = str(row.get("Term", "")).strip() if "Term" in df.columns else ""
                    form = str(row.get("Form", "")).strip() if "Form" in df.columns else None
                    recorded_by = str(row.get("Recorded By", "")).strip() if "Recorded By" in df.columns else user

                    # --- FETCH STUDENT ---
                    cursor.execute("""
                        SELECT student_id, form, total_brought, total_required
                        FROM students WHERE admission_no = ?
                    """, (adm_no,))
                    student = cursor.fetchone()
                    if not student:
                        result["skipped"].append(f"Row {row_num}: Student {adm_no} not found")
                        missing_students.append((adm_no, quantity, date_brought))
                        result["error_count"] += 1
                        continue

                    student_id, db_form, total_brought, total_required = student
                    form = form or db_form
                    if form not in cum_req:
                        result["skipped"].append(f"Row {row_num}: Invalid Form '{form}'")
                        result["error_count"] += 1
                        continue

                    # --- TERM FROM DATE ---
                    try:
                        term = term or get_term_from_date(date_brought)
                    except Exception as e:
                        result["skipped"].append(f"Row {row_num}: Invalid date for term: {e}")
                        result["error_count"] += 1
                        continue

                    # === ALLOW ANY QUANTITY → NEGATIVE REMAINING OK ===
                    # No check: quantity > remaining
                    # remaining_to_bring will be updated after insert

                    batch.append((
                        student_id,
                        quantity,
                        term,
                        form,
                        f"{date_brought} 00:00:00",
                        recorded_by
                    ))

                    # --- BATCH INSERT ---
                    if len(batch) >= BATCH_SIZE:
                        success = self._insert_ream_batch(cursor, batch, result, user)
                        result["success_count"] += success
                        processed += len(batch)
                        if progress_callback:
                            progress_callback(f"Imported {processed}/{total_rows} records...")
                        batch.clear()

                # Final batch
                if batch:
                    success = self._insert_ream_batch(cursor, batch, result, user)
                    result["success_count"] += success

                # === 7. UPDATE remaining_to_bring FOR ALL AFFECTED STUDENTS ===
                cursor.execute("""
                    UPDATE students
                    SET total_brought = total_brought + ?,
                        remaining_to_bring = total_required - (total_brought + ?),
                        status = CASE
                            WHEN total_required - (total_brought + ?) > 0 THEN 'Behind'
                            WHEN total_required - (total_brought + ?) = 0 THEN 'On Track'
                            ELSE 'Ahead'
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE student_id = ?
                """, (quantity, quantity, quantity, quantity, student_id))
                conn.commit()

                logger.info(f"Excel import completed: {result['success_count']} success, {result['error_count']} errors")

                # === 8. MISSING STUDENTS PDF ===
                if missing_students:
                    pdf_path = self._generate_missing_students_pdf(missing_students, user)
                    if pdf_path:
                        result["missing_pdf_path"] = pdf_path
                        logger.info(f"Missing students report saved: {pdf_path}")

            except Exception as e:
                conn.rollback()
                result["errors"].append(f"Database error: {str(e)}")
                logger.error(f"Import failed: {e}", exc_info=True)
            finally:
                self._release_connection(conn)

        except Exception as e:
            result["errors"].append(f"File error: {str(e)}")
            logger.error(f"Excel read error: {e}", exc_info=True)

        return result
        
    def _insert_ream_batch(self, cursor, batch: List[tuple], result: dict, user: str) -> int:
        success = 0
        for record in batch:
            student_id, quantity, term, form, date_brought, recorded_by = record
            try:
                # 1. Insert ream
                cursor.execute("""
                    INSERT INTO reams_brought
                    (student_id, quantity, term, form, date_brought, recorded_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, record)
                record_id = cursor.lastrowid

                # 2. Update student with CORRECT status & updated_at
                cursor.execute("""
                    UPDATE students
                    SET total_brought = total_brought + ?,
                        remaining_to_bring = remaining_to_bring - ?,
                        status = CASE
                            WHEN (total_required - (total_brought + ?)) > 0 THEN 'Behind'
                            WHEN (total_required - (total_brought + ?)) = 0 THEN 'On Track'
                            ELSE 'Ahead'
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE student_id = ?
                """, (quantity, quantity, quantity, quantity, student_id))

                self._log_audit_with_conn(
                    cursor.connection,
                    'record_ream', user, 'students', student_id,
                    f"Imported {quantity} ream(s) on {date_brought}"
                )
                success += 1
            except Exception as e:
                result["errors"].append(f"Insert failed for student_id {student_id}: {e}")
        return success


    def _generate_missing_students_pdf(self, missing_students: list, user: str) -> str:
        """Generate PDF of missing students and let user choose save location."""
        try:
            # Hide Tkinter root window
            root = Tk()
            root.withdraw()
            root.update()

            # Let user choose directory
            save_dir = filedialog.askdirectory(
                title="Choose folder to save Missing Students PDF"
            )
            root.destroy()

            if not save_dir:
                logger.info("User cancelled PDF save.")
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_path = os.path.join(save_dir, f"Missing_Students_Import_{timestamp}.pdf")

            # Build PDF
            doc = SimpleDocTemplate(pdf_path, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()

            # Title
            elements.append(Paragraph("Missing Students Report", styles['Title']))
            elements.append(Paragraph(f"Generated by: {user}", styles['Normal']))
            elements.append(Paragraph(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
            elements.append(Spacer(1, 12))

            # Table data
            data = [["Admission No", "Quantity", "Date Brought"]]
            for adm_no, qty, date in missing_students:
                data.append([adm_no, str(qty), date])

            # Create table
            table = Table(data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ]))
            elements.append(table)

            # Build PDF
            doc.build(elements)
            logger.info(f"Missing students PDF generated: {pdf_path}")
            return pdf_path

        except Exception as e:
            logger.error(f"Failed to generate missing students PDF: {e}")
            return None

    def record_ream(
        self,
        admission_no: str,
        quantity: int,
        term: str,
        user: str,
        role: str,
        form: Optional[str] = None,
        recorded_by: Optional[str] = None,
        date_brought: Optional[str] = None
    ) -> None:
        """
        Record reams brought by a student.
        - Allows NEGATIVE remaining_to_bring → excess carried to next form
        - No limit on quantity
        """
        conn = None
        try:
            if not self._check_user_auth(user, role, 'record_ream'):
                raise ValueError("Permission denied")

            self._validate_admission_no(admission_no)
            self._validate_quantity(quantity)
            self._validate_term(term)
            self._validate_form(form)
            self._validate_recorded_by(recorded_by)

            conn = self._get_connection()
            cursor = conn.cursor()

            # === 1. Fetch student + current stats ===
            cursor.execute("""
                SELECT student_id, name, form, total_brought, total_required
                FROM students WHERE admission_no = ?
            """, (admission_no,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Student {admission_no} not found")

            student_id, student_name, student_form, total_brought, total_required = row
            form = form or student_form

            # === 2. Set date ===
            final_date = date_brought or datetime.now().strftime("%Y-%m-%d")

            # === 3. Insert ream record ===
            cursor.execute("""
                INSERT INTO reams_brought (student_id, quantity, term, form, date_brought, recorded_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (student_id, quantity, term, form, final_date, recorded_by or user))
            record_id = cursor.lastrowid

            # === 4. UPDATE STUDENT STATS (ALLOW NEGATIVE) ===
            new_total_brought = total_brought + quantity
            new_remaining = total_required - new_total_brought  # Can be negative

            # Smart status
            if new_remaining > 0:
                new_status = "Behind"
            elif new_remaining == 0:
                new_status = "On Track"
            else:
                new_status = "Ahead"  # Brought extra!

            cursor.execute("""
                UPDATE students
                SET total_brought = ?,
                    remaining_to_bring = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE student_id = ?
            """, (new_total_brought, new_remaining, new_status, student_id))

            # === 5. Log audit ===
            self._log_audit_with_conn(
                conn, 'record_ream', user, 'reams_brought', record_id,
                f"Recorded {quantity} ream(s) for {student_name} ({admission_no}) on {final_date} → "
                f"remaining: {new_remaining}, status: {new_status}"
            )

            # === 6. Check stock ===
            self._check_stock_alert(conn)

            # === 7. Commit ===
            conn.commit()

            logger.info(
                f"Recorded {quantity} ream(s) for {admission_no} | "
                f"Total: {new_total_brought}, Remaining: {new_remaining}, Status: {new_status}"
            )

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error recording ream for {admission_no}: {e}")
            # Log failure
            try:
                fail_conn = conn if conn else self._get_connection()
                self._log_audit_with_conn(
                    fail_conn, 'record_ream', user, 'reams_brought', None,
                    f"Failed: {e}", False
                )
                if not conn:
                    self._release_connection(fail_conn)
            except:
                pass
            raise
        finally:
            if conn:
                self._release_connection(conn)

    def get_record_by_id(self, record_id: Union[int, str], user: str, role: str) -> Optional[Dict]:
        """Get a single ream record by ID. Accepts int or str."""
        try:
            if not self._check_user_auth(user, role, 'get_record_by_id'):
                logger.info(f"get_record_by_id: No record returned for unauthorized user {user}")
                return None
            try:
                rid = int(record_id)
                if rid <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Invalid record ID")
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT r.record_id, s.admission_no, s.name, s.form, s.stream,
                           r.quantity, r.term, r.date_brought, r.recorded_by
                    FROM reams_brought r
                    JOIN students s ON r.student_id = s.student_id
                    WHERE r.record_id = ?
                """, (rid,))
                row = cursor.fetchone()
                if not row:
                    logger.info(f"Ream record {rid} not found")
                    return None
                record = dict(row)
                record['date_issued'] = record['date_brought']
                self._log_audit('get_record_by_id', user, 'reams_brought', rid, f"Fetched ream record {rid}")
                logger.info(f"Fetched ream record {rid} by {user}")
                return record
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching ream record {record_id}: {e}")
            self._log_audit('get_record_by_id', user, 'reams_brought', None, f"Error: {e}", False)
            raise

    def fetch_all_records(self, user: str, role: str) -> List[Dict]:
        """Fetch all ream records."""
        try:
            if not self._check_user_auth(user, role, 'fetch_all_records'):
                logger.info(f"fetch_all_records: No records returned for unauthorized user {user}")
                return []
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT 
                        r.record_id, s.admission_no, s.name, s.form, s.stream, r.quantity, 
                        r.term, r.date_brought, r.recorded_by
                    FROM reams_brought r
                    JOIN students s ON r.student_id = s.student_id
                    ORDER BY r.date_brought DESC
                """)
                rows = cursor.fetchall()
                records = [dict(row) for row in rows]
                for rec in records:
                    rec['date_issued'] = rec['date_brought']
                self._log_audit('fetch_all_records', user, 'reams_brought', None,
                                f"Fetched {len(records)} ream records")
                logger.info(f"Fetched {len(records)} ream records by {user}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching all ream records: {e}")
            self._log_audit('fetch_all_records', user, 'reams_brought', None,
                            f"Error fetching all ream records: {e}", False)
            raise

    def get_purchase_by_id(self, purchase_id: Union[int, str], user: str, role: str) -> Optional[Dict]:
        """Get a single purchase record by ID. Accepts int or str."""
        try:
            if not self._check_user_auth(user, role, 'get_purchase_by_id'):
                logger.info(f"get_purchase_by_id: No record returned for unauthorized user {user}")
                return None

            # FIXED: Convert safely to int
            try:
                pid = int(purchase_id)
                if pid <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Invalid purchase ID")

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT purchase_id, quantity, supplier, invoice_no, purchase_date, recorded_by, remarks
                    FROM reams_purchased
                    WHERE purchase_id = ?
                """, (pid,))
                row = cursor.fetchone()
                if not row:
                    logger.info(f"Purchase record {pid} not found")
                    return None

                record = dict(row)
                record['date_issued'] = record['purchase_date']

                self._log_audit(
                    'get_purchase_by_id', user, 'reams_purchased', pid,
                    f"Fetched purchase record {pid}"
                )
                logger.info(f"Fetched purchase record {pid} by {user}")
                return record

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error fetching purchase record {purchase_id}: {e}")
            try:
                pid = int(purchase_id) if str(purchase_id).isdigit() else None
                self._log_audit(
                    'get_purchase_by_id', user, 'reams_purchased', pid,
                    f"Error: {e}", False
                )
            except:
                pass
            raise

    def fetch_purchase_records(self, user: str, role: str, supplier: Optional[str] = None,
                              start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        """Fetch purchase records with optional filters."""
        try:
            if not self._check_user_auth(user, role, 'fetch_purchase_records'):
                logger.info(f"fetch_purchase_records: No records returned for unauthorized user {user}")
                return []
            if supplier:
                self._validate_supplier(supplier)
            self._validate_date_range(start_date, end_date)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT purchase_id, quantity, supplier, invoice_no, purchase_date, recorded_by, remarks
                    FROM reams_purchased
                    WHERE 1=1
                """
                params = []
                if supplier:
                    query += " AND supplier LIKE ?"
                    params.append(f"%{supplier}%")
                if start_date:
                    query += " AND date(purchase_date) >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date(purchase_date) <= ?"
                    params.append(end_date)
                query += " ORDER BY purchase_date DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = [dict(row) for row in rows]
                for rec in records:
                    rec['date_issued'] = rec['purchase_date']
                self._log_audit('fetch_purchase_records', user, 'reams_purchased', None,
                                f"Fetched {len(records)} purchase records")
                logger.info(f"Fetched {len(records)} purchase records by {user}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching purchase records: {e}")
            self._log_audit('fetch_purchase_records', user, 'reams_purchased', None,
                            f"Error fetching purchase records: {e}", False)
            raise

    def delete_record(self, record_id: int, user: str, role: str) -> None:
        """Delete a ream record – ONE TRANSACTION + safe external calls."""
        conn = None
        try:
            if not self._check_user_auth(user, role, 'delete_record'):
                raise ValueError("Permission denied: Staff or Admin role required")
            if not isinstance(record_id, int) or record_id <= 0:
                raise ValueError("Invalid record ID")

            conn = self._get_connection()
            cursor = conn.cursor()

            # --- 1. Fetch record ---
            cursor.execute("""
                SELECT r.student_id, r.quantity, s.admission_no, s.name
                FROM reams_brought r
                JOIN students s ON r.student_id = s.student_id
                WHERE r.record_id = ?
            """, (record_id,))
            record = cursor.fetchone()
            if not record:
                raise ValueError(f"Ream record {record_id} not found")
            student_id, quantity, admission_no, student_name = record

            # --- 2. Delete the record ---
            cursor.execute("DELETE FROM reams_brought WHERE record_id = ?", (record_id,))

            # --- 3. Check stock alert (same conn) ---
            self._check_stock_alert(conn)

            # --- 4. Commit delete + stock check ---
            conn.commit()
            logger.info(f"Deleted ream record {record_id} by {user}")

            # --- 5. LOG AUDIT IN SEPARATE CALL (no conn=) ---
            self._log_audit(
                action='delete_record',
                user=user,
                table_name='reams_brought',
                record_id=record_id,
                details=f"Deleted record {record_id} with {quantity} reams for {student_name} ({admission_no})"
            )

            # --- 6. UPDATE STUDENT STATUS IN SEPARATE CALL (no conn=) ---
            try:
                self.student_manager.update_ream_status(student_id, user)
            except Exception as status_err:
                logger.warning(f"Failed to update student status after delete {record_id}: {status_err}")

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error in delete_record {record_id}: {e}")
            # Log failure using normal _log_audit (no conn=)
            try:
                self._log_audit(
                    action='delete_record', user=user, table_name='reams_brought',
                    record_id=record_id, details=f"Failed: {e}", success=False
                )
            except:
                pass  # Silent fail if audit is broken
            raise
        finally:
            if conn:
                self._release_connection(conn)

    def delete_purchase(self, purchase_id: Union[int, str], user: str, role: str) -> None:
        """Delete a purchase record. Accepts int or str."""
        conn = None  # ← Declare early for finally
        try:
            if not self._check_user_auth(user, role, 'delete_purchase'):
                raise ValueError("Permission denied: Staff or Admin role required")

            # FIXED: Convert safely
            try:
                pid = int(purchase_id)
                if pid <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("Invalid purchase ID")

            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "SELECT quantity, supplier, invoice_no FROM reams_purchased WHERE purchase_id = ?",
                    (pid,)
                )
                record = cursor.fetchone()
                if not record:
                    raise ValueError("Purchase record not found")
                quantity, supplier, invoice_no = record

                cursor.execute("DELETE FROM reams_purchased WHERE purchase_id = ?", (pid,))

                # FIXED: Pass conn to avoid opening new one -> prevents "database is locked"
                self._log_audit(
                    'delete_purchase', user, 'reams_purchased', pid,
                    f"Deleted purchase {pid} with {quantity} reams from {supplier} (invoice {invoice_no})",
                    conn=conn  # ← ONLY CHANGE
                )

                self._check_stock_alert(conn)
                conn.commit()
                logger.info(f"Deleted purchase record {pid} by {user}")

            except Exception as e:
                conn.rollback()
                logger.error(f"Error deleting purchase record {purchase_id}: {e}")
                self._log_audit(
                    'delete_purchase', user, 'reams_purchased', pid if 'pid' in locals() else None,
                    f"Error: {e}", False,
                    conn=conn  # ← Use same conn for failure log
                )
                raise
            finally:
                if conn:
                    self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error in delete_purchase {purchase_id}: {e}")
            raise


    def get_ream_contribution_report(self, user: str, role: str) -> List[Dict]:
        """
        Generate cumulative ream contribution report.
        - Uses per-form cumulative requirements
        - Allows NEGATIVE remaining → shows excess carried forward
        - Accurate averages and totals
        """
        try:
            if not self._check_user_auth(user, role, 'get_ream_contribution_report'):
                return []

            # === 1. CUMULATIVE REQUIREMENTS ===
            cum_req = get_cumulative_ream_requirements()
            if not cum_req:
                logger.warning("No cumulative ream settings — using fallback")
                cum_req = {form: 8 for form in self.valid_forms}  # Default 8

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                # === 2. AGGREGATE BY FORM & STREAM ===
                cursor.execute("""
                    SELECT
                        s.form,
                        s.stream,
                        COUNT(DISTINCT s.student_id) AS total_students,
                        COALESCE(SUM(r.quantity), 0) AS total_brought,
                        COALESCE(SUM(s.total_required), 0) AS total_required_all
                    FROM students s
                    LEFT JOIN reams_brought r ON s.student_id = r.student_id
                    GROUP BY s.form, s.stream
                    ORDER BY s.form, s.stream
                """)
                rows = cursor.fetchall()
                records = []

                for row in rows:
                    form = row['form']
                    stream = row['stream'] or 'N/A'
                    total_students = row['total_students']
                    total_brought = row['total_brought']
                    total_required_all = row['total_required_all']  # From DB

                    # Use DB total_required (supports per-student overrides)
                    required = total_required_all
                    remaining = required - total_brought  # Can be negative
                    excess = max(0, -remaining)  # Positive excess
                    remaining_display = remaining  # Can be negative

                    avg_per_student = round(total_brought / total_students, 2) if total_students > 0 else 0.0

                    records.append({
                        'form': form,
                        'stream': stream,
                        'total_students': total_students,
                        'total_brought': total_brought,
                        'required': required,
                        'remaining': remaining_display,  # Can be -3
                        'excess': excess,                # +3 carried
                        'avg_per_student': avg_per_student,
                        'completion_pct': round((total_brought / required) * 100, 1) if required > 0 else 0.0
                    })

                # === 3. LOG AUDIT ===
                self._log_audit(
                    'get_ream_contribution_report', user, 'reams_brought', None,
                    f"Generated cumulative report: {len(records)} entries"
                )
                logger.info(f"Generated cumulative ream contribution report by {user}")

                return records

            finally:
                self._release_connection(conn)

        except Exception as e:
            logger.error(f"Error in cumulative ream contribution report: {e}")
            self._log_audit(
                'get_ream_contribution_report', user, 'reams_brought', None,
                f"Error: {e}", False
            )
            raise

    def export_ream_report_to_pdf(self, file_path: str, user: str, role: str) -> None:
        """Export ream records to a PDF file using LaTeX."""
        try:
            if not self._check_user_auth(user, role, 'export_ream_report_to_pdf'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")
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
                doc.append(f"Generated by {user} on {datetime.now().strftime('%Y-%m-%d')}")
                with doc.create(Subsection('Records')):
                    with doc.create(Tabular('|l|l|l|l|l|r|l|l|l|')) as table:
                        table.add_hline()
                        table.add_row(('Record ID', 'Adm No', 'Name', 'Form', 'Stream', 'Qty', 'Term', 'Date', 'Recorded By'))
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
                                record['date_issued'],
                                record['recorded_by'] or ''
                            ))
                            table.add_hline()

            doc.generate_pdf(file_path.replace('.pdf', ''), clean_tex=True, compiler='pdflatex')
            self._log_audit('export_ream_report_to_pdf', user, 'reams_brought', None,
                            f"Exported ream report to {file_path}")
            logger.info(f"Exported ream report to {file_path} by {user}")
        except Exception as e:
            logger.error(f"Error exporting ream report to {file_path}: {e}")
            self._log_audit('export_ream_report_to_pdf', user, 'reams_brought', None,
                            f"Error exporting ream report to {file_path}: {e}", False)
            raise

    def get_min_stock_alert(self, user: str, role: str) -> int:
        """Get the minimum stock alert threshold."""
        try:
            if not self._check_user_auth(user, role, 'get_min_stock_alert'):
                logger.info(f"get_min_stock_alert: No value returned for unauthorized user {user}")
                return 10
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT min_stock_alert FROM settings LIMIT 1")
                result = cursor.fetchone()
                min_stock = result[0] if result else 10
                self._log_audit('get_min_stock_alert', user, 'settings', None,
                                f"Fetched min stock alert ({min_stock})")
                logger.info(f"Fetched min stock alert ({min_stock}) by {user}")
                return min_stock
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching min stock alert: {e}")
            self._log_audit('get_min_stock_alert', user, 'settings', None,
                            f"Error fetching min stock alert: {e}", False)
            raise

    def get_total_reams(self, user: str, role: str) -> int:
        """Get the total number of reams in stock."""
        try:
            if not self._check_user_auth(user, role, 'get_total_reams'):
                logger.info(f"get_total_reams: No value returned for unauthorized user {user}")
                return 0
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT current_balance FROM ream_stock_summary ORDER BY summary_id DESC LIMIT 1")
                result = cursor.fetchone()
                total_reams = result[0] if result else 0
                self._log_audit('get_total_reams', user, 'ream_stock_summary', None,
                                f"Fetched total reams ({total_reams})")
                logger.info(f"Fetched total reams ({total_reams}) by {user}")
                return total_reams
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error fetching total reams: {e}")
            self._log_audit('get_total_reams', user, 'ream_stock_summary', None,
                            f"Error fetching total reams: {e}", False)
            raise

    def search_records(self, user: str, role: str, keyword: Optional[str] = None, field: Optional[str] = None, term: Optional[str] = None,
                      form: Optional[str] = None, min_qty: Optional[int] = None, max_qty: Optional[int] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        """Search ream records with filters."""
        try:
            if not self._check_user_auth(user, role, 'search_records'):
                logger.info(f"search_records: No records returned for unauthorized user {user}")
                return []
            if keyword and (not isinstance(keyword, str) or len(keyword) < 2 or not re.match(r'^[A-Za-z0-9\s]+$', keyword)):
                raise ValueError("Keyword must be at least 2 characters and contain only letters, numbers, or spaces")
            if term:
                self._validate_term(term)
            if form:
                self._validate_form(form)
            self._validate_date_range(start_date, end_date)
            if min_qty is not None:
                self._validate_quantity(min_qty)
            if max_qty is not None:
                self._validate_quantity(max_qty)
            if min_qty and max_qty and min_qty > max_qty:
                raise ValueError("Minimum quantity must not exceed maximum quantity")

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                query = """
                    SELECT 
                        r.record_id, s.admission_no, s.name, s.form, s.stream, r.quantity, 
                        r.term, r.date_brought, r.recorded_by
                    FROM reams_brought r
                    JOIN students s ON r.student_id = s.student_id
                    WHERE 1=1
                """
                params = []
                if keyword and field == "All":
                    pattern = f"%{keyword}%"
                    query += " AND (s.name LIKE ? OR s.admission_no LIKE ? OR r.term LIKE ? OR s.form LIKE ? OR r.recorded_by LIKE ?)"
                    params.extend([pattern, pattern, pattern, pattern, pattern])
                elif keyword:
                    field_map = {
                        "Adm No": "s.admission_no",
                        "Name": "s.name",
                        "Term": "r.term",
                        "Form": "s.form",
                        "Recorded By": "r.recorded_by"
                    }
                    if field not in field_map:
                        raise ValueError(f"Invalid search field: {field}")
                    pattern = f"%{keyword}%"
                    query += f" AND {field_map[field]} LIKE ?"
                    params.append(pattern)
                if term:
                    query += " AND r.term = ?"
                    params.append(term)
                if form:
                    query += " AND s.form = ?"
                    params.append(form)
                if min_qty is not None:
                    query += " AND r.quantity >= ?"
                    params.append(min_qty)
                if max_qty is not None:
                    query += " AND r.quantity <= ?"
                    params.append(max_qty)
                if start_date:
                    query += " AND date(r.date_brought) >= ?"
                    params.append(start_date)
                if end_date:
                    query += " AND date(r.date_brought) <= ?"
                    params.append(end_date)
                query += " ORDER BY r.date_brought DESC"

                cursor.execute(query, params)
                rows = cursor.fetchall()
                records = [dict(row) for row in rows]
                for rec in records:
                    rec['date_issued'] = rec['date_brought']
                self._log_audit('search_records', user, 'reams_brought', None,
                                f"Searched ream records with filters")
                logger.info(f"Searched ream records by {user}")
                return records
            finally:
                self._release_connection(conn)
        except Exception as e:
            logger.error(f"Error searching ream records: {e}")
            self._log_audit('search_records', user, 'reams_brought', None,
                            f"Error searching ream records: {e}", False)
            raise

    def backup_ream_database(self, backup_path: str, user: str, role: str) -> None:
        try:
            if not self._check_user_auth(user, role, 'backup_ream_database'):
                raise ValueError("Permission denied")

            abs_path = os.path.abspath(backup_path)
            if not abs_path.endswith('.db'):
                abs_path += '.db'

            # Use SQLite's online backup
            conn = self._get_connection()
            try:
                backup_conn = sqlite3.connect(abs_path)
                conn.backup(backup_conn)
                backup_conn.close()
            finally:
                self._release_connection(conn)

            self._log_audit('backup_ream_database', user, 'database', None,
                            f"Backup created at {abs_path}")
            logger.info(f"Backup created at {abs_path} by {user}")

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            self._log_audit('backup_ream_database', user, 'database', None,
                            f"Backup failed: {e}", False)
            raise


if __name__ == "__main__":
    ream_mgr = ReamManager()