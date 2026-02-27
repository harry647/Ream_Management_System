import sqlite3
import logging
import shutil
import os
from datetime import datetime
from typing import List, Dict, Optional
from modules.db_setup import get_db_connection, release_db_connection, backup_database, get_db_pool, get_logs_dir, get_database_path
from modules.user_manager import UserManager
from modules.ream_manager import ReamManager
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import re
import threading



# Configure logging
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'issue_manager.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_NAME = get_database_path()

class IssueManager:
    def __init__(self, db_name: str = DB_NAME):
        self.db_name = db_name
        # Uses global db_pool from db_setup.py
        self.user_manager = UserManager(db_name)
        self.ream_manager = ReamManager(db_name)
        self.edit_lock = threading.Lock()
        self.valid_departments = {'Mathematics', 'Sciences', 'Languages', 'Humanities', 'Technical', 'Library', 'Administration', 'Exams', 'Store'}

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool."""
        pool = get_db_pool()
        return pool.get_connection(timeout=30)

    def _release_connection(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool."""
        if conn:
            pool = get_db_pool()
            pool.release_connection(conn)

    def _validate_department(self, department: str) -> bool:
        """Validate department against allowed values."""
        if department not in self.valid_departments:
            raise ValueError(f"Department must be one of {self.valid_departments}")
        return True

    def _validate_quantity(self, quantity: int) -> bool:
        """Validate ream quantity (positive integer, 1-50)."""
        if not isinstance(quantity, int) or quantity < 1 or quantity > 50:
            raise ValueError("Quantity must be an integer between 1 and 50")
        return True

    def _validate_issued_by(self, issued_by: str) -> bool:
        """Validate issued_by (alphanumeric with underscores, 3-20 characters, non-empty)."""
        if not issued_by or not re.match(r'^[A-Za-z0-9_]{3,20}$', issued_by):
            raise ValueError("Issued_by must be 3-20 alphanumeric characters with underscores and cannot be empty")
        return True

    def _validate_purpose(self, purpose: str) -> bool:
        """Validate purpose (alphanumeric with spaces and hyphens, 1-100 characters, non-empty)."""
        if not purpose or not re.match(r'^[A-Za-z0-9\s\-]{1,100}$', purpose):
            raise ValueError("Purpose must be 1-100 alphanumeric characters with spaces and hyphens and cannot be empty")
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

    def _validate_keyword(self, keyword: str) -> bool:
        """Validate keyword (alphanumeric with spaces, 2+ characters if provided)."""
        if keyword and (not isinstance(keyword, str) or len(keyword) < 2 or not re.match(r'^[A-Za-z0-9\s]+$', keyword)):
            raise ValueError("Keyword must be at least 2 characters and contain only letters, numbers, or spaces")
        return True

    def _check_user_auth(self, user: str, role: str, required_role: str = 'admin') -> bool:
        """Check if the user has the required role."""
        if not user or not role:
            logger.warning(f"Access denied: No user or role provided for {required_role} action")
            return False
        try:
            if not re.match(r'^[A-Za-z0-9_]{3,20}$', user):
                raise ValueError("User must be 3-20 alphanumeric characters with underscores")
            if not self.user_manager.check_user_role(user, required_role):
                logger.warning(f"User {user} lacks required role: {required_role}")
                return False
            return True
        except Exception as e:
            logger.error(f"Authentication error for {user}: {e}")
            raise

    def _log_audit(self, action: str, user: str, table_name: str, record_id: Optional[int], 
               details: str, success: bool = True, conn=None, cursor=None) -> None:
        """Log an audit entry."""

        # Use existing connection/cursor if provided
        if conn and cursor:
            is_independent_transaction = False
        else:
            is_independent_transaction = True
            conn = self._get_connection()
            cursor = conn.cursor()

        try:
            valid_operations = {'INSERT', 'UPDATE', 'DELETE', 'LOGIN', 'DISPLAY', 'REPORT', 'EXPORT'}
            fetch_actions = {'get_all_issues', 'fetch_issue_records', 'get_issue_by_id', 'search_issues', 'get_department_summary', 'get_issues_by_term'}
            insert_actions = {'issue_reams'}
            delete_actions = {'delete_issue'}
            export_actions = {'export_issues_report', 'backup_issue_database'}

            if action in fetch_actions:
                operation = 'DISPLAY'
            elif action in insert_actions:
                operation = 'INSERT'
            elif action in delete_actions:
                operation = 'DELETE'
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

            # Only commit if it's an independent transaction
            if is_independent_transaction:
                conn.commit()
                logger.info(f"Audit logged: {operation} ({action}) by {user}")
            else:
                # Audit log inserted, but the main function (issue_reams) will handle the commit
                logger.info(f"Audit prepared: {operation} ({action}) by {user}")

        except Exception as e:
            if is_independent_transaction:
                conn.rollback()
            logger.error(f"Failed to log audit: {e}")
            raise
        finally:
            # Only release connection if it was created in this function
            if is_independent_transaction:
                self._release_connection(conn)

    def _validate_stock_before_issue(self, quantity: int, user: str, role: str) -> bool:
        """Validate if enough stock is available and check for low stock."""
        try:
            total_stock = self.ream_manager.get_total_reams(user, role)
            min_stock = self.ream_manager.get_min_stock_alert(user, role)

            if total_stock < quantity:
                logger.error(f"Cannot issue {quantity} reams. Only {total_stock} available.")
                return False
            if total_stock - quantity < min_stock:
                logger.warning(f"Low stock warning! Only {total_stock - quantity} reams would remain after issuing {quantity}.")
            return True
        except Exception as e:
            logger.error(f"Error validating stock for issuing {quantity} reams: {e}")
            raise

    def issue_reams(self, department: str, quantity: int, term: Optional[str], 
                    date_issued: str, issued_by: str, purpose: str, 
                    user: str, role: str) -> None:
        """Issue reams to a department with date_issued."""
        
        # Initialize conn to None for safe cleanup in the outer finally block
        conn = None 
        
        try:
            if not self._check_user_auth(user, role, required_role='staff'):
                raise ValueError("Permission denied: Staff or Admin role required")

            # === VALIDATIONS ===
            self._validate_department(department)
            self._validate_quantity(quantity)
            if term and term not in {'Term 1', 'Term 2', 'Term 3'}:
                raise ValueError("Term must be Term 1, Term 2, or Term 3")
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_issued):
                raise ValueError("Date issued must be in YYYY-MM-DD format")
            self._validate_issued_by(issued_by)
            self._validate_purpose(purpose)

            if not self._validate_stock_before_issue(quantity, user, role):
                raise ValueError("Insufficient stock to issue")

            # === DATABASE INSERT ===
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Inner try block for the transaction logic
            try: 
                # 1. Main INSERT
                cursor.execute("""
                    INSERT INTO reams_issued 
                    (department, quantity, term, date_issued, issued_by, purpose)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (department, quantity, term, date_issued, issued_by, purpose))
                issue_id = cursor.lastrowid

                # 2. LOG AUDIT using the SAME TRANSACTION
                self._log_audit(
                    'issue_reams', user, 'reams_issued', issue_id,
                    f"Issued {quantity} reams to {department} on {date_issued}",
                    conn=conn, cursor=cursor 
                )
                
                # 3. Commit BOTH the main INSERT and the audit log entry
                conn.commit()
                logger.info(f"Issued {quantity} reams to {department} on {date_issued} by {user}")

            except Exception as e:
                # Handle database-specific errors (lock, SQL issues, etc.)
                if conn: # Only rollback if connection was successfully acquired
                    conn.rollback() 
                
                # Log failure using the independent _log_audit (no conn/cursor passed)
                self._log_audit('issue_reams', user, 'reams_issued', 0,
                                f"Failed: {str(e)}", False)
                raise 

        except Exception as e:
            # Catch validation errors, permission errors, and re-raised DB errors
            logger.error(f"Issue reams failed: {e}")
            raise 

        finally:
            # Crucial: Ensure the connection is always released
            if conn:
                self._release_connection(conn)


    def get_all_issues(self, user: str, role: str) -> List[Dict]:
        """Get all issue records."""
        conn = None 
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"get_all_issues: No records returned for unauthorized user {user}")
                return []
                
            conn = self._get_connection() 
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            
            cursor.execute("""
                SELECT issue_id, department, quantity, date_issued, issued_by, purpose
                FROM reams_issued
                ORDER BY date_issued DESC
            """)
            rows = cursor.fetchall()
            
            records = [
                {
                    'issue_id': row['issue_id'],
                    'department': row['department'],
                    'quantity': row['quantity'],
                    'date_issued': row['date_issued'],
                    'issued_by': row['issued_by'],
                    'purpose': row['purpose']
                } for row in rows
            ]
            
            # Audit log for success
            self._log_audit(
                'get_all_issues', user, 'reams_issued', 0,
                f"Fetched {len(records)} issue records"
            )
            logger.info(f"Fetched {len(records)} issue records by {user}")
            return records
            
        except Exception as e:
            # Audit log for failure
            logger.error(f"Error fetching issue records: {e}")
            self._log_audit(
                'get_all_issues', user, 'reams_issued', 0,
                f"Error fetching issue records: {e}", False
            )
            raise 

        finally:
            if conn:
                self._release_connection(conn)

    def get_issues_by_term(self, term: str, user: str, role: str) -> List[Dict]:
        """Get issue records for a specific term."""
        conn = None 
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"get_issues_by_term: No records returned for unauthorized user {user}")
                return []
                
            if term not in {'Term 1', 'Term 2', 'Term 3'}:
                raise ValueError(f"Invalid term: {term}. Must be one of Term 1, Term 2, Term 3")
            
            conn = self._get_connection() 
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Merge inner try block with outer try
            query = """
                SELECT issue_id, department, quantity, date_issued, issued_by, purpose
                FROM reams_issued
                WHERE term = ?
                ORDER BY date_issued DESC
            """
            cursor.execute(query, (term,))
            rows = cursor.fetchall()
            
            records = [
                {
                    'issue_id': row['issue_id'],
                    'department': row['department'],
                    'quantity': row['quantity'],
                    'date_issued': row['date_issued'],
                    'issued_by': row['issued_by'],
                    'purpose': row['purpose']
                } for row in rows
            ]
            
            # Audit log for success
            self._log_audit(
                'get_issues_by_term', user, 'reams_issued', 0,
                f"Fetched {len(records)} issue records for term {term}"
            )
            logger.info(f"Fetched {len(records)} issue records for term {term} by {user}")
            return records
            
        except Exception as e:
            # Audit log for failure
            logger.error(f"Error fetching issues for term {term}: {e}")
            self._log_audit(
                'get_issues_by_term', user, 'reams_issued', 0,
                f"Error fetching issues for term {term}: {e}", False
            )
            raise 

        finally:
            if conn:
                self._release_connection(conn)

    def get_issue_by_id(self, issue_id: int, user: str, role: str) -> Dict:
        """Get a single issue record by ID."""
        conn = None
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"get_issue_by_id: No record returned for unauthorized user {user}")
                return None
                
            if not isinstance(issue_id, int) or issue_id <= 0:
                raise ValueError("Invalid issue ID")
                
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Merge inner try block with outer try
            cursor.execute("""
                SELECT issue_id, department, quantity, date_issued, issued_by, purpose
                FROM reams_issued
                WHERE issue_id = ?
            """, (issue_id,))
            row = cursor.fetchone()
            
            if not row:
                logger.info(f"Issue record {issue_id} not found")
                return None
                
            record = {
                'issue_id': row['issue_id'],
                'department': row['department'],
                'quantity': row['quantity'],
                'date_issued': row['date_issued'],
                'issued_by': row['issued_by'],
                'purpose': row['purpose']
            }
            
            # Audit log for success
            self._log_audit(
                'get_issue_by_id', user, 'reams_issued', issue_id,
                f"Fetched issue record {issue_id}"
            )
            logger.info(f"Fetched issue record {issue_id} by {user}")
            return record
            
        except Exception as e:
            # Audit log for failure
            logger.error(f"Error fetching issue record {issue_id}: {e}")
            self._log_audit(
                'get_issue_by_id', user, 'reams_issued', issue_id,
                f"Error fetching issue record {issue_id}: {e}", False
            )
            raise 

        finally:
            if conn:
                self._release_connection(conn)


    def search_issues(self, keyword: str, field: str, start_date: Optional[str], end_date: Optional[str], user: str, role: str) -> List[Dict]:
        """Search issue records with filters."""
        conn = None 
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"search_issues: No records returned for unauthorized user {user}")
                return []
                
            # Validation runs before connection acquisition
            self._validate_keyword(keyword)
            self._validate_date_range(start_date, end_date)

            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            query = """
                SELECT issue_id, department, quantity, date_issued, issued_by, purpose
                FROM reams_issued
                WHERE 1=1
            """
            params = []
            if keyword and field == "All":
                pattern = f"%{keyword}%"
                query += " AND (department LIKE ? OR issued_by LIKE ? OR purpose LIKE ?)"
                params.extend([pattern, pattern, pattern])
            elif keyword:
                field_map = {
                    "Department": "department",
                    "Issued By": "issued_by",
                    "Purpose": "purpose"
                }
                if field not in field_map:
                    raise ValueError(f"Invalid search field: {field}")
                pattern = f"%{keyword}%"
                query += f" AND {field_map[field]} LIKE ?"
                params.append(pattern)
            if start_date:
                query += " AND date(date_issued) >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date(date_issued) <= ?"
                params.append(end_date)
            query += " ORDER BY date_issued DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            records = [
                {
                    'issue_id': row['issue_id'],
                    'department': row['department'],
                    'quantity': row['quantity'],
                    'date_issued': row['date_issued'],
                    'issued_by': row['issued_by'],
                    'purpose': row['purpose']
                } for row in rows
            ]
            
            # Audit log for success
            self._log_audit(
                'search_issues', user, 'reams_issued', 0,
                f"Searched issue records with filters (keyword={keyword}, field={field}, date_range={start_date} to {end_date})"
            )
            logger.info(f"Searched issue records with filters (keyword={keyword}, field={field}, date_range={start_date} to {end_date}) by {user}")
            return records
            
        except Exception as e:
            # Audit log for failure
            logger.error(f"Error searching issue records: {e}")
            self._log_audit(
                'search_issues', user, 'reams_issued', 0,
                f"Error searching issue records: {e}", False
            )
            raise 

        finally:
            if conn:
                self._release_connection(conn)

    def delete_issue(self, issue_id: int, user: str, role: str) -> None:
        """Delete an issue record."""
        conn = None 
        try:
            if not self._check_user_auth(user, role, required_role='staff'):
                raise ValueError("Permission denied: Staff or Admin role required")
            if not isinstance(issue_id, int) or issue_id <= 0:
                raise ValueError("Invalid issue ID")

            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Inner try block for the transaction
            try:
                # 1. Select the record details first
                cursor.execute("SELECT department, quantity, purpose FROM reams_issued WHERE issue_id = ?", (issue_id,))
                record = cursor.fetchone()
                if not record:
                    raise ValueError("Issue record not found")
                department, quantity, purpose = record[0], record[1], record[2] # Access by index for safety if row_factory isn't guaranteed

                # 2. DELETE operation
                cursor.execute("DELETE FROM reams_issued WHERE issue_id = ?", (issue_id,))

                # 3. LOG AUDIT using the SAME TRANSACTION
                self._log_audit(
                    'delete_issue', user, 'reams_issued', issue_id,
                    f"Deleted issue {issue_id} of {quantity} reams to {department}: {purpose}",
                    conn=conn, cursor=cursor 
                )

                # 4. Commit BOTH the DELETE and the Audit Log entry
                conn.commit()
                logger.info(f"Deleted issue record {issue_id} by {user}")
            
            except Exception as e:
                if conn:
                    conn.rollback()
                
                # Log failure using the independent _log_audit (no conn/cursor passed)
                self._log_audit(
                    'delete_issue', user, 'reams_issued', issue_id,
                    f"Error deleting issue record {issue_id}: {e}", False
                )
                logger.error(f"Error deleting issue record {issue_id}: {e}")
                raise 
            
            finally:
                pass 

        except Exception as e:
            logger.error(f"Error in delete_issue {issue_id}: {e}")
            raise

        finally:
            if conn:
                self._release_connection(conn)


    def get_department_summary(self, user: str, role: str) -> List[Dict]:
        """Get summary of reams issued per department."""
        conn = None
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                logger.info(f"get_department_summary: No records returned for unauthorized user {user}")
                return []
                
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Merge inner try block with outer try
            cursor.execute("""
                SELECT department, COALESCE(SUM(quantity), 0) AS total_issued
                FROM reams_issued
                GROUP BY department
                ORDER BY total_issued DESC
            """)
            rows = cursor.fetchall()
            
            records = [
                {
                    'department': row['department'],
                    'total_issued': row['total_issued']
                } for row in rows
            ]
            
            # Audit log for success
            self._log_audit(
                'get_department_summary', user, 'reams_issued', 0,
                f"Fetched department summary with {len(records)} entries"
            )
            logger.info(f"Fetched department summary with {len(records)} entries by {user}")
            return records
            
        except Exception as e:
            # Audit log for failure
            logger.error(f"Error fetching department summary: {e}")
            self._log_audit(
                'get_department_summary', user, 'reams_issued', 0,
                f"Error fetching department summary: {e}", False
            )
            raise 

        finally:
            if conn:
                self._release_connection(conn)

                
    def export_issues_report(self, file_path: str, user: str, role: str) -> None:
        """Export issue records to a PDF file using ReportLab."""
        
        conn = None 
        try:
            if not self._check_user_auth(user, role, required_role='viewer'):
                raise ValueError("Permission denied: Viewer, Staff, or Admin role required")

            records = self.get_all_issues(user, role)
            if not records:
                records = []  

            doc = SimpleDocTemplate(file_path, pagesize=A4,
                                    topMargin=0.8*inch, bottomMargin=0.8*inch,
                                    leftMargin=0.6*inch, rightMargin=0.6*inch)
            elements = []
            styles = getSampleStyleSheet()

            elements.append(Paragraph("Issue Records Report", styles['Title']))
            elements.append(Paragraph(f"Generated by: {user} | {datetime.now().strftime('%Y-%m-%d')}",
                                    styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))

            data = [["Issue ID", "Department", "Quantity", "Date Issued", "Issued By", "Purpose"]]
            for r in records:
                 data.append([
                     str(r['issue_id']), r['department'], str(r['quantity']), 
                     r['date_issued'], r['issued_by'], r['purpose']
                 ])
            
            table = Table(data, colWidths=[0.6*inch, 1.2*inch, 0.7*inch, 1*inch, 1*inch, 2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5EAA')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F6F5')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(table)

            def footer(canvas, doc):
                 canvas.saveState()
                 canvas.setFont('Helvetica', 9)
                 page_num = canvas.getPageNumber()
                 text = f"Page {page_num} | Printed by: {user}"
                 canvas.drawCentredString(doc.width/2 + doc.leftMargin, 0.5*inch, text)
                 canvas.restoreState()

            doc.build(elements, onFirstPage=footer, onLaterPages=footer)
            
            self._log_audit(
                'export_issues_report', user, 'reams_issued', 0,
                f"Exported issue report to {file_path}"
            )
            logger.info(f"Exported issue report to {file_path} by {user}")
            
        except Exception as e:
            logger.error(f"Error exporting issue report to {file_path}: {e}")
            self._log_audit(
                'export_issues_report', user, 'reams_issued', 0,
                f"Error exporting issue report to {file_path}: {e}", False
            )
            raise
        
        finally:
            pass

    def backup_issue_database(self, backup_path: str, user: str, role: str) -> None:
        """Create a backup of the database using SQLite's .backup command."""

        conn = None         
        backup_conn = None 
        
        try:
            if not self._check_user_auth(user, role, required_role='admin'):
                raise ValueError("Permission denied: Admin role required")

            if not os.path.exists(self.db_name):
                raise FileNotFoundError(f"Database file not found: {self.db_name}")

            # Ensure backup directory exists
            backup_dir = os.path.dirname(backup_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # 1. Connect to both databases
            conn = sqlite3.connect(self.db_name)
            backup_conn = sqlite3.connect(backup_path)
            
            # 2. Perform backup
            with backup_conn:
                conn.backup(backup_conn) 

            self._log_audit(
                'backup_issue_database', user, 'database', 0,
                f"Database backup created at {backup_path}"
            )
            logger.info(f"Database backup created at {backup_path} by {user}")
            
        except Exception as e:
            logger.error(f"Error creating backup at {backup_path}: {e}")
            self._log_audit(
                'backup_issue_database', user, 'database', 0,
                f"Error creating backup at {backup_path}: {e}", False
            )
            raise
            
        finally:
            if conn:
                conn.close()
            if backup_conn:
                backup_conn.close()

if __name__ == "__main__":
    issue_mgr = IssueManager()