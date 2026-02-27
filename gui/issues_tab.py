import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox, StringVar
from modules.issue_manager import IssueManager
from modules.ream_manager import ReamManager
from gui.utils import show_error, show_info, validate_positive_int
from modules.db_setup import get_logs_dir
import logging
from typing import List, Dict, Optional
import re
import os
import threading
from PIL import Image
from datetime import datetime
from tkcalendar import Calendar



# ----------------------------------------------------------------------
# Logging (first thing!)
# ----------------------------------------------------------------------
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, "issue_tab.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DepartmentSummaryWindow(ctk.CTkToplevel):
    def __init__(self, parent, records, icons, log_feedback=None):
        super().__init__(parent)
        self.title("Department Summary")
        self.geometry("1000x700")  # Increased size
        self.configure(fg_color="#1E1E1E")
        self.icons = icons
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info("Initializing DepartmentSummaryWindow")

        # Scrollable main container
        scrollable_frame = ctk.CTkScrollableFrame(self, corner_radius=10, fg_color="#2B2B2B")
        scrollable_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Table frame inside scrollable
        table_frame = ctk.CTkFrame(scrollable_frame, corner_radius=10, fg_color="#333333")
        table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("Department", "Total Reams Issued")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=300, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for r in records:
            tree.insert("", "end", values=(r['department'], r['total_issued']))

        # Close button below scrollable area
        close_button = ctk.CTkButton(
            self,
            text="Close",
            image=self.icons['cancel'],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        close_button.pack(pady=15, padx=15, anchor="center")
        logger.debug("Close button added to DepartmentSummaryWindow")

        # Bind Enter and Escape keys to close
        self.bind("<Return>", lambda event: self.destroy())
        self.bind("<Escape>", lambda event: self.destroy())
        self.log_feedback(f"Displayed department summary with {len(records)} entries")

    def destroy(self):
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except Exception:
            pass
        super().destroy()


class IssuesByTermWindow(ctk.CTkToplevel):
    def __init__(self, parent, term, records, icons, log_feedback=None):
        super().__init__(parent)
        self.title(f"Issues for {term}")
        self.geometry("1200x700")  
        self.configure(fg_color="#1E1E1E")
        self.icons = icons
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing IssuesByTermWindow for {term}")

        # Scrollable container
        scrollable_frame = ctk.CTkScrollableFrame(self, corner_radius=10, fg_color="#2B2B2B")
        scrollable_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Table frame
        table_frame = ctk.CTkFrame(scrollable_frame, corner_radius=10, fg_color="#333333")
        table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("Issue ID", "Department", "Quantity", "Date Issued", "Issued By", "Purpose")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for r in records:
            tree.insert("", "end", values=(
                r['issue_id'], r['department'], r['quantity'], r['date_issued'],
                r['issued_by'] or '', r['purpose'] or ''
            ))

        # Close button
        close_button = ctk.CTkButton(
            self,
            text="Close",
            image=self.icons['cancel'],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        close_button.pack(pady=15, padx=15, anchor="center")
        logger.debug("Close button added to IssuesByTermWindow")

        # Bind Enter and Escape keys to close
        self.bind("<Return>", lambda event: self.destroy())
        self.bind("<Escape>", lambda event: self.destroy())
        self.log_feedback(f"Displayed issues for {term} with {len(records)} entries")

    def destroy(self):
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except Exception:
            pass
        super().destroy()


class DashboardWindow(ctk.CTkToplevel):
    def __init__(self, parent, issue_mgr, ream_mgr, username, role, icons, log_feedback=None):
        super().__init__(parent)
        self.title("Issue Management Dashboard")
        self.geometry("1400x800")  
        self.configure(fg_color="#1E1E1E")
        self.issue_mgr = issue_mgr
        self.ream_mgr = ream_mgr
        self.username = username
        self.role = role
        self.icons = icons
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info("Initializing DashboardWindow")

        # Main scrollable container
        main_scroll = ctk.CTkScrollableFrame(self, fg_color="#1E1E1E")
        main_scroll.pack(fill="both", expand=True, padx=20, pady=20)

        # Stock Status Table
        stock_frame = ctk.CTkFrame(main_scroll, corner_radius=10, fg_color="#2B2B2B")
        stock_frame.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(stock_frame, text="Stock Status", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=8)
        stock_columns = ("Metric", "Value")
        stock_tree = ttk.Treeview(stock_frame, columns=stock_columns, show="headings", height=4)
        for col in stock_columns:
            stock_tree.heading(col, text=col)
            stock_tree.column(col, width=200, anchor="center")
        stock_tree.pack(fill="both", expand=True, padx=15, pady=10)

        total_reams = self.ream_mgr.get_total_reams(self.username, self.role)
        min_stock = self.ream_mgr.get_min_stock_alert(self.username, self.role)
        stock_status = "Normal" if total_reams >= min_stock else "Low"

        stock_tree.insert("", "end", values=("Total Reams", str(total_reams)))
        stock_tree.insert("", "end", values=("Minimum Threshold", str(min_stock)))
        stock_tree.insert("", "end", values=("Status", stock_status))

        # Recent Issues Table
        issue_frame = ctk.CTkFrame(main_scroll, corner_radius=10, fg_color="#2B2B2B")
        issue_frame.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(issue_frame, text="Recent Issue Records (Last 5)", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=8)
        issue_columns = ("Issue ID", "Department", "Quantity", "Date Issued", "Issued By", "Purpose")
        issue_tree = ttk.Treeview(issue_frame, columns=issue_columns, show="headings")
        for col in issue_columns:
            issue_tree.heading(col, text=col)
            issue_tree.column(col, width=140, anchor="center")
        issue_tree.pack(fill="both", expand=True, padx=15, pady=10)

        recent_issues = self.issue_mgr.get_all_issues(self.username, self.role)[:5]
        for record in recent_issues:
            issue_tree.insert("", "end", values=(
                record['issue_id'], record['department'], record['quantity'],
                record['date_issued'], record['issued_by'] or '', record['purpose'] or ''
            ))

        # Department Summary Table
        dept_frame = ctk.CTkFrame(main_scroll, corner_radius=10, fg_color="#2B2B2B")
        dept_frame.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(dept_frame, text="Department Summary", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=8)
        dept_columns = ("Department", "Total Reams Issued")
        dept_tree = ttk.Treeview(dept_frame, columns=dept_columns, show="headings")
        for col in dept_columns:
            dept_tree.heading(col, text=col)
            dept_tree.column(col, width=250, anchor="center")
        dept_tree.pack(fill="both", expand=True, padx=15, pady=10)

        dept_summary = self.issue_mgr.get_department_summary(self.username, self.role)
        for record in dept_summary:
            dept_tree.insert("", "end", values=(record['department'], record['total_issued']))

        # Issues by Term Table
        term_frame = ctk.CTkFrame(main_scroll, corner_radius=10, fg_color="#2B2B2B")
        term_frame.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(term_frame, text="Issues by Term", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=8)
        term_columns = ("Term", "Total Reams Issued")
        term_tree = ttk.Treeview(term_frame, columns=term_columns, show="headings")
        for col in term_columns:
            term_tree.heading(col, text=col)
            term_tree.column(col, width=250, anchor="center")
        term_tree.pack(fill="both", expand=True, padx=15, pady=10)

        terms = ['Term 1', 'Term 2', 'Term 3']
        for term in terms:
            term_issues = self.issue_mgr.get_issues_by_term(term, self.username, self.role)
            total_issued = sum(record['quantity'] for record in term_issues)
            term_tree.insert("", "end", values=(term, total_issued))

        # Close button
        close_button = ctk.CTkButton(
            self,
            text="Close",
            image=self.icons['cancel'],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        close_button.pack(pady=15, padx=20, anchor="center")
        logger.debug("Close button added to DashboardWindow")

        # Bind Enter and Escape keys to close
        self.bind("<Return>", lambda event: self.destroy())
        self.bind("<Escape>", lambda event: self.destroy())
        self.log_feedback(f"Displayed issue management dashboard with {len(recent_issues)} recent issues and {len(dept_summary)} departments")
    
    def destroy(self):
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except Exception:
            pass
        super().destroy()

class IssueReamsForm(ctk.CTkToplevel):
    def __init__(self, parent, issue_mgr, username, role, valid_departments, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Issue Reams")
        self.geometry("900x750")  
        self.configure(fg_color="#1E1E1E")
        self.issue_mgr = issue_mgr
        self.username = username
        self.role = role
        self.valid_departments = valid_departments
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing IssueReamsForm for user {username}")

        # Scrollable main frame
        scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="#1E1E1E")
        scrollable_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Form frame inside scrollable
        form_frame = ctk.CTkFrame(scrollable_frame, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Department", "department", ctk.CTkComboBox, {"values": valid_departments}),
            ("Quantity", "quantity", ctk.CTkEntry, {}),
            ("Term", "term", ctk.CTkComboBox, {"values": [""] + ['Term 1', 'Term 2', 'Term 3']}),
            ("Date Issued (YYYY-MM-DD)", "date_issued", ctk.CTkEntry, {}),
            ("Issued By", "issued_by", ctk.CTkEntry, {"state": "readonly"}),
            ("Purpose", "purpose", ctk.CTkEntry, {})
        ]

        # === DYNAMIC FIELD CREATION (except issued_by) ===
        for label, key, widget_type, kwargs in fields:
            if key == "issued_by":
                continue  # Skip — handled separately below

            field_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            field_frame.pack(fill="x", pady=8, padx=15)
            ctk.CTkLabel(field_frame, text=label, width=150, anchor="w", text_color="#FFFFFF").pack(side="left")
            self.entries[key] = widget_type(field_frame, font=("Arial", 12), height=35, **kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=10)
            logger.debug(f"Added field: {label}")

        # === SPECIAL: issued_by with StringVar (fixes readonly bug) ===
        field_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
        field_frame.pack(fill="x", pady=8, padx=15)
        ctk.CTkLabel(field_frame, text="Issued By", width=150, anchor="w", text_color="#FFFFFF").pack(side="left")

        self.issued_by_var = ctk.StringVar(value=self.username)
        self.entries['issued_by'] = ctk.CTkEntry(
            field_frame,
            font=("Arial", 12),
            height=35,
            textvariable=self.issued_by_var,
            state="readonly",
            fg_color="#3A3A3A",
            text_color="#FFFFFF"
        )
        self.entries['issued_by'].pack(side="left", fill="x", expand=True, padx=10)
        logger.debug(f"Auto-populated issued_by with {self.username}")

        # Set default date_issued to today
        self.entries['date_issued'].insert(0, datetime.now().strftime("%Y-%m-%d"))
        logger.debug("Set default date_issued to today")

        # Calendar button
        calendar_button = ctk.CTkButton(
            form_frame,
            text="Pick Date",
            image=self.icons['calendar'],
            compound="left",
            command=lambda: self.show_calendar(self.entries['date_issued']),
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12),
            width=120,
            height=35
        )
        calendar_button.pack(pady=12, anchor="center")

        # Buttons outside scrollable (fixed at bottom)
        button_frame = ctk.CTkFrame(self, fg_color="#1E1E1E")
        button_frame.pack(fill="x", pady=15, padx=20)
        ctk.CTkButton(
            button_frame,
            text="Submit",
            image=self.icons['save'],
            compound="left",
            command=self.submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=10)
        ctk.CTkButton(
            button_frame,
            text="Cancel",
            image=self.icons['cancel'],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=10)

        # Bind Enter to submit and Escape to cancel
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("IssueReamsForm initialized")

    def show_calendar(self, entry_widget):
        """Open a calendar widget to select a date."""
        def set_date():
            selected_date = cal.get_date()
            entry_widget.delete(0, "end")
            entry_widget.insert(0, selected_date)
            top.destroy()
            logger.info(f"Selected date: {selected_date} for {entry_widget}")

        top = ctk.CTkToplevel(self)
        top.title("Select Date")
        top.geometry("350x350")
        top.transient(self)
        top.grab_set()
        cal = Calendar(top, selectmode="day", date_pattern="yyyy-mm-dd")
        cal.pack(pady=15, padx=15, fill="both", expand=True)
        ctk.CTkButton(top, text="Confirm", command=set_date).pack(pady=10)
        logger.info("Opened calendar widget")

    def submit(self):
        """Submit the issue reams form."""
        try:
            department = self.entries['department'].get().strip()
            quantity = self.entries['quantity'].get().strip()
            term = self.entries['term'].get().strip() or None
            date_issued = self.entries['date_issued'].get().strip()
            issued_by = self.issued_by_var.get().strip() 
            purpose = self.entries['purpose'].get().strip()

            # === REQUIRED FIELD CHECK ===
            if not all([department, quantity, date_issued, issued_by, purpose]):
                show_error(self, "Department, Quantity, Date Issued, Issued By, and Purpose are required")
                self.log_feedback("Issue reams failed: Missing required fields")
                return

            # === QUANTITY VALIDATION ===
            if not validate_positive_int(quantity) or not (1 <= int(quantity) <= 50):
                show_error(self, "Quantity must be an integer between 1 and 50")
                self.log_feedback("Issue reams failed: Invalid quantity")
                return

            # === CALL MANAGER ===
            self.issue_mgr.issue_reams(
                department=department,
                quantity=int(quantity),
                term=term,
                date_issued=date_issued,
                issued_by=issued_by,
                purpose=purpose,
                user=self.username,
                role=self.role
            )

            show_info(self, f"Issued {quantity} ream(s) to {department}")
            self.log_feedback(f"Issued {quantity} ream(s) to {department}")
            logger.info(f"Issued {quantity} reams to {department} by {self.username}")

            if self.callback:
                self.callback()
            self.destroy()

        except Exception as e:
            show_error(self, f"Error: {str(e)}")
            self.log_feedback(f"Issue reams error: {str(e)}")
            logger.error(f"Issue reams failed: {e}")

    def destroy(self):
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except Exception:
            pass
        super().destroy()


class TermInputForm(ctk.CTkToplevel):
    
    # Define the list of available terms
    TERM_OPTIONS = ["Term 1", "Term 2", "Term 3"]
    
    def __init__(self, parent, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Select Term")
        self.geometry("400x250")  
        self.configure(fg_color="#1E1E1E")
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        self._submitted = False  # Prevent double submit
        logger.info("Initializing TermInputForm")

        # Scrollable frame 
        scrollable_frame = ctk.CTkScrollableFrame(self, fg_color="#1E1E1E")
        scrollable_frame.pack(fill="both", expand=True, padx=20, pady=20)

        form_frame = ctk.CTkFrame(scrollable_frame, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=20, padx=20, fill="both", expand=True)

        # Label
        ctk.CTkLabel(form_frame, text="Select Term:", font=("Arial", 14), text_color="#FFFFFF").pack(pady=15)
        
        # ComboBox
        self.term_combobox = ctk.CTkComboBox(
            form_frame, 
            font=("Arial", 14), 
            height=40,
            values=self.TERM_OPTIONS,
            state="readonly"
        )
        self.term_combobox.pack(fill="x", padx=30, pady=10)
        
        # Set default
        if self.TERM_OPTIONS:
            self.term_combobox.set(self.TERM_OPTIONS[0])

        # === BUTTONS ===
        button_frame = ctk.CTkFrame(self, fg_color="#1E1E1E")
        button_frame.pack(fill="x", pady=15, padx=40)

        # Submit Button — SAVE REFERENCE
        self.submit_btn = ctk.CTkButton(
            button_frame,
            text="Submit",
            image=self.icons['save'],
            compound="left",
            command=self.submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        self.submit_btn.pack(side="left", padx=10)

        # Cancel Button
        ctk.CTkButton(
            button_frame,
            text="Cancel",
            image=self.icons['cancel'],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=10)

        # Key bindings
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("TermInputForm initialized")


    def submit(self):
        """Submit the term – never destroy here."""
        if self._submitted:
            return
        self._submitted = True
        self.submit_btn.configure(state="disabled")

        # === UNBIND KEYS IMMEDIATELY ===
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except:
            pass

        term = self.term_combobox.get().strip()
        if not term or term not in self.TERM_OPTIONS:
            show_error(self, "Please select a valid Term.")
            self.log_feedback("Issues by term failed: Invalid or no term provided")
            self._submitted = False
            self.submit_btn.configure(state="normal")
            # Re-bind only if error
            self.bind("<Return>", lambda e: self.submit())
            return

        if self.callback:
            self.callback(term)
        # DO NOT destroy here


    def destroy(self):
        """Safely destroy: unbind keys first."""
        try:
            self.unbind("<Return>")
            self.unbind("<Escape>")
        except Exception:
            pass
        super().destroy()
            
        
                

class IssuesTab:
    def __init__(self, parent, db_name: str, username: Optional[str], role: Optional[str], main_window, icons):
        self.parent = parent
        self.db_name = db_name
        self.username = username
        self.role = role
        self.main_window = main_window
        self.icons = icons
        self.issue_mgr = IssueManager(db_name)
        self.ream_mgr = ReamManager(db_name)
        self.deleted_issue_records: List[Dict] = []
        self.sort_column_name = None
        self.sort_reverse = False
        self.setup_gui()
        logger.info(f"Initializing IssuesTab with username={username}, role={role}")
        self.main_window.log_feedback("IssuesTab initialized; data will load after login")

    def setup_gui(self):
        """Set up the IssuesTab GUI."""
        # Main scrollable frame for the entire tab
        self.main_scrollable = ctk.CTkScrollableFrame(self.parent, fg_color="#1E1E1E")
        self.main_scrollable.pack(fill="both", expand=True, padx=15, pady=15)

        self.main_frame = ctk.CTkFrame(self.main_scrollable, fg_color="#2B2B2B", corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.role and self.role not in {'admin', 'staff'}:
            ctk.CTkLabel(self.main_frame, text="Permission Denied: Admin or Staff role required",
                         font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=20)
            self.main_window.log_feedback("Access denied: Admin or Staff role required")
            return

        # Search bar
        logger.debug("Creating search_frame in IssuesTab")
        self.search_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.search_frame, text="Search Issues:", width=100, text_color="#FFFFFF").pack(side="left", padx=5)
        self.search_field = ctk.CTkComboBox(self.search_frame, values=["All", "Department", "Issued By", "Purpose"], font=("Arial", 12), height=35)
        self.search_field.pack(side="left", padx=5)
        self.search_entry = ctk.CTkEntry(self.search_frame, font=("Arial", 12), height=35)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkLabel(self.search_frame, text="Department:", width=80, text_color="#FFFFFF").pack(side="left", padx=5)
        self.search_department = ctk.CTkComboBox(self.search_frame, values=[""] + list(self.issue_mgr.valid_departments), font=("Arial", 12), height=35)
        self.search_department.pack(side="left", padx=5)
        ctk.CTkButton(
            self.search_frame,
            text="Search",
            image=self.icons['search'] if 'search' in self.icons else None,
            compound="left",
            command=self.search_issues,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        logger.debug("Packing search_frame in IssuesTab")
        self.search_frame.pack(pady=8, padx=15, fill="x")

        # Date range filter
        logger.debug("Creating date_frame in IssuesTab")
        self.date_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.date_frame, text="Start Date (YYYY-MM-DD):", text_color="#FFFFFF").pack(side="left", padx=5)
        self.start_date = ctk.CTkEntry(self.date_frame, width=120, font=("Arial", 12), height=35)
        self.start_date.pack(side="left", padx=5)
        ctk.CTkLabel(self.date_frame, text="End Date (YYYY-MM-DD):", text_color="#FFFFFF").pack(side="left", padx=5)
        self.end_date = ctk.CTkEntry(self.date_frame, width=120, font=("Arial", 12), height=35)
        self.end_date.pack(side="left", padx=5)
        logger.debug("Packing date_frame in IssuesTab")
        self.date_frame.pack(pady=8, padx=15, fill="x")

        # Action frame
        logger.debug("Creating action_frame in IssuesTab")
        self.action_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkButton(
            self.action_frame,
            text="Show Dashboard",
            image=self.icons['dashboard'] if 'dashboard' in self.icons else None,
            compound="left",
            command=self.show_dashboard,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                self.action_frame,
                text="Export to PDF",
                image=self.icons['export'] if 'export' in self.icons else None,
                compound="left",
                command=self.export_to_pdf,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.action_frame,
                text="Department Summary",
                image=self.icons['summary'] if 'summary' in self.icons else None,
                compound="left",
                command=self.show_department_summary,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.action_frame,
                text="Issues by Term",
                image=self.icons['term'] if 'term' in self.icons else None,
                compound="left",
                command=self.show_issues_by_term,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.action_frame,
                text="Undo Delete",
                image=self.icons['undo'] if 'undo' in self.icons else None,
                compound="left",
                command=self.undo_delete,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
        if self.role == 'admin':
            ctk.CTkButton(
                self.action_frame,
                text="Backup Database",
                image=self.icons['backup'] if 'backup' in self.icons else None,
                compound="left",
                command=self.backup_database,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
        logger.debug("Packing action_frame in IssuesTab")
        self.action_frame.pack(pady=8, padx=15, fill="x")

        # Buttons
        logger.debug("Creating button_frame in IssuesTab")
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                self.button_frame,
                text="Issue Reams",
                image=self.icons['add'],
                compound="left",
                command=self.open_issue_reams_form,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Delete Issued Reams",
                image=self.icons['delete'],
                compound="left",
                command=self.delete_issue,
                fg_color="#C53030",
                hover_color="#9B2A2A",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.button_frame,
            text="Refresh",
            image=self.icons['refresh'] if 'refresh' in self.icons else None,
            compound="left",
            command=self.refresh_data,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        logger.debug("Packing button_frame in IssuesTab")
        self.button_frame.pack(pady=10, padx=15, fill="x")

        # Issues table with its own scroll
        logger.debug("Creating table_frame in IssuesTab")
        self.table_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        columns = ("Issue ID", "Department", "Quantity", "Date Issued", "Issued By", "Purpose")
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c))
            self.tree.column(col, width=150, anchor="center")
        self.tree_scroll = ctk.CTkScrollbar(self.table_frame, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.tree_scroll.pack(side="right", fill="y")
        logger.debug("Packing table_frame in IssuesTab")
        self.table_frame.pack(fill="both", expand=True, padx=15, pady=15)

        self.load_issues()
        self.main_frame.update_idletasks()
        logger.info("IssuesTab GUI initialized")

    def sort_column(self, col: str):
        """Sort the table by the specified column."""
        try:
            records = [(self.tree.set(item, col), item) for item in self.tree.get_children()]
            if self.sort_column_name == col:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_reverse = False
                self.sort_column_name = col

            def convert(value):
                try:
                    return int(value) if col in ["Issue ID", "Quantity"] else value.lower()
                except (ValueError, AttributeError):
                    return value

            records.sort(key=lambda x: convert(x[0]), reverse=self.sort_reverse)

            for index, (value, item) in enumerate(records):
                self.tree.move(item, "", index)

            for column in self.tree["columns"]:
                self.tree.heading(column, text=column)
            arrow = " DESC" if self.sort_reverse else " ASC"
            self.tree.heading(col, text=col + arrow)
            self.main_window.log_feedback(f"Sorted issues table by {col} {'descending' if self.sort_reverse else 'ascending'}")
        except Exception as e:
            show_error(self.main_window, f"Error sorting table: {str(e)}")
            self.main_window.log_feedback(f"Error sorting table by {col}: {str(e)}")
            logger.error(f"Error sorting table by {col}: {str(e)}")

    def on_select_issue(self, event):
        """Handle issue selection."""
        selected = self.tree.selection()
        if not selected:
            return
        issue_id = self.tree.item(selected[0])['values'][0]
        self.main_window.log_feedback(f"Selected issue record: {issue_id}")
        logger.info(f"Selected issue record: {issue_id} by user {self.username}")

    def open_issue_reams_form(self):
        """Open the issue reams form in a new window."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open issue reams form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Issue Reams",
            form_class=IssueReamsForm,
            issue_mgr=self.issue_mgr,
            username=self.username,
            role=self.role,
            valid_departments=list(self.issue_mgr.valid_departments),
            icons=self.icons,
            callback=self.load_issues,
            log_feedback=self.main_window.log_feedback
        )

    def delete_issue(self):
        """Delete a selected issue record."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Delete issue failed: Permission denied")
            return
        
        selected = self.tree.selection()
        if not selected:
            show_error(self.main_window, "No issue record selected")
            self.main_window.log_feedback("Delete issue failed: No record selected")
            return
        
        issue_id = self.tree.item(selected[0])['values'][0]
        
        try:
            if not messagebox.askyesno("Confirm Delete", f"Delete issue record {issue_id}?"):
                self.main_window.log_feedback(f"Delete issue {issue_id} cancelled")
                return
            
            # Pass self.role as the third positional argument.
            issue_record = self.issue_mgr.get_issue_by_id(issue_id, self.username, self.role)
            
            if not issue_record:
                # Handle the case where a record was selected in the UI but deleted by another user.
                self.main_window.log_feedback(f"Delete issue {issue_id} failed: Record not found in DB.")
                self.load_issues() 
                return 
                
            self.issue_mgr.delete_issue(issue_id, self.username, self.role)
            self.deleted_issue_records.append(issue_record)
            
            show_info(self.main_window, f"Issue record {issue_id} deleted successfully")
            self.main_window.log_feedback(f"Issue record {issue_id} deleted successfully")
            logger.info(f"Issue record {issue_id} deleted by {self.username}")
            
            self.load_issues()
        except Exception as e:
            show_error(self.main_window, f"Error deleting issue record: {str(e)}")
            self.main_window.log_feedback(f"Error deleting issue record {issue_id}: {str(e)}")
            logger.error(f"Error deleting issue record {issue_id}: {str(e)}")

    def undo_delete(self):
        """Undo the last deletion of an issue record."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Undo delete failed: Permission denied")
            return
        if not self.deleted_issue_records:
            show_error(self.main_window, "No deletions to undo")
            self.main_window.log_feedback("Undo delete failed: No deletions to undo")
            return
        try:
            record = self.deleted_issue_records.pop()
            self.issue_mgr.issue_reams(
                record['department'], record['quantity'], record['term'], record['date_issued'],
                record['issued_by'], record['purpose'], self.username, self.role
            )
            show_info(self.main_window, f"Issue record {record['issue_id']} restored")
            self.main_window.log_feedback(f"Issue record {record['issue_id']} restored")
            logger.info(f"Issue record {record['issue_id']} restored by {self.username}")
            self.load_issues()
        except Exception as e:
            show_error(self.main_window, f"Error undoing deletion: {str(e)}")
            self.main_window.log_feedback(f"Error undoing deletion: {str(e)}")
            logger.error(f"Error undoing deletion: {str(e)}")

    def search_issues(self):
        """Search issue records with filters."""
        try:
            keyword = self.search_entry.get().strip() or None
            field = self.search_field.get()
            department = self.search_department.get() or None
            start_date = self.start_date.get().strip() or None
            end_date = self.end_date.get().strip() or None

            if keyword and len(keyword) < 2:
                show_error(self.main_window, "Keyword must be at least 2 characters")
                self.main_window.log_feedback("Search failed: Keyword too short")
                return
            if start_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', start_date):
                show_error(self.main_window, "Start date must be in YYYY-MM-DD format")
                self.main_window.log_feedback("Search failed: Invalid start date")
                return
            if end_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', end_date):
                show_error(self.main_window, "End date must be in YYYY-MM-DD format")
                self.main_window.log_feedback("Search failed: Invalid end date")
                return
            if start_date and end_date and start_date > end_date:
                show_error(self.main_window, "Start date must be before or equal to end date")
                self.main_window.log_feedback("Search failed: Invalid date range")
                return

            for item in self.tree.get_children():
                self.tree.delete(item)
            records = self.issue_mgr.search_issues(keyword, field, start_date, end_date, self.username, self.role)
            for r in records:
                if not department or r['department'] == department:
                    self.tree.insert("", "end", values=(
                        r['issue_id'], r['department'], r['quantity'], r['date_issued'],
                        r['issued_by'] or '', r['purpose'] or ''
                    ))
            self.main_window.log_feedback(f"Searched issues with filters (keyword={keyword}, field={field}, department={department}, date_range={start_date} to {end_date}), found {len(self.tree.get_children())} results")
            logger.info(f"Searched issues with filters (keyword={keyword}, field={field}, department={department}, date_range={start_date} to {end_date}), found {len(self.tree.get_children())} results by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error searching issues: {str(e)}")
            self.main_window.log_feedback(f"Error searching issues: {str(e)}")
            logger.error(f"Error searching issues: {str(e)}")

    def export_to_pdf(self):
        """Export issue records to PDF."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Export to PDF failed: Permission denied")
            return
        try:
            file_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
            if not file_path:
                self.main_window.log_feedback("Export to PDF cancelled: No file selected")
                logger.info(f"Export to PDF cancelled by user {self.username}: No file selected")
                return
            self.issue_mgr.export_issues_report(file_path, self.username, self.role)
            show_info(self.main_window, f"Issues exported to {file_path}")
            self.main_window.log_feedback(f"Issues exported to {file_path}")
            logger.info(f"Issues exported to {file_path} by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error exporting to PDF: {str(e)}")
            self.main_window.log_feedback(f"Error exporting to PDF: {str(e)}")
            logger.error(f"Error exporting to PDF: {str(e)}")

    def show_department_summary(self):
        """Display department summary in a new window."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Department summary failed: Permission denied")
            return
        try:
            records = self.issue_mgr.get_department_summary(self.username, self.role)
            self.main_window.open_form_window(
                title="Department Summary",
                form_class=DepartmentSummaryWindow,
                records=records,
                icons=self.icons,
                log_feedback=self.main_window.log_feedback
            )
            self.main_window.log_feedback(f"Displayed department summary with {len(records)} entries")
            logger.info(f"Displayed department summary with {len(records)} entries by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error displaying department summary: {str(e)}")
            self.main_window.log_feedback(f"Error displaying department summary: {str(e)}")
            logger.error(f"Error displaying department summary: {str(e)}")

    def show_issues_by_term(self):
        """Open a form to input term and display issues by term."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Issues by term failed: Permission denied")
            return

        # Prevent multiple instances
        if hasattr(self, '_current_term_form') and self._current_term_form and self._current_term_form.winfo_exists():
            self._current_term_form.lift()
            return

        def on_term_submit(term):
            """Handle term submission - safe cleanup."""
            try:
                # Fetch records
                records = self.issue_mgr.get_issues_by_term(term, self.username, self.role)
                logger.info(f"Fetched {len(records)} issue records for term {term} by {self.username}")

                # Open results window
                self.main_window.open_form_window(
                    title=f"Issues for {term}",
                    form_class=IssuesByTermWindow,
                    term=term,
                    records=records,
                    icons=self.icons,
                    log_feedback=self.main_window.log_feedback
                )
                self.main_window.log_feedback(f"Displayed issues for {term} with {len(records)} entries")

            except Exception as e:
                show_error(self.main_window, f"Error displaying issues by term: {str(e)}")
                self.main_window.log_feedback(f"Error displaying issues by term {term}: {str(e)}")
                logger.error(f"Error displaying issues by term {term}: {str(e)}")
                
            finally:
                if hasattr(self, '_current_term_form') and self._current_term_form:
                    try:
                        if self._current_term_form.winfo_exists():
                            self._current_term_form.destroy()
                    except Exception:
                        pass
                    self._current_term_form = None

        # Create the input form 
        self._current_term_form = self.main_window.open_form_window(
            title="Enter Term",
            form_class=TermInputForm,
            icons=self.icons,
            callback=on_term_submit,  
            log_feedback=self.main_window.log_feedback
        )

    def show_dashboard(self):
        """Display issue management dashboard in a GUI window."""
        try:
            self.main_window.open_form_window(
                title="Issue Management Dashboard",
                form_class=DashboardWindow,
                issue_mgr=self.issue_mgr,
                ream_mgr=self.ream_mgr,
                username=self.username,
                role=self.role,
                icons=self.icons,
                log_feedback=self.main_window.log_feedback
            )
            self.main_window.log_feedback("Displayed issue management dashboard")
            logger.info(f"Displayed issue management dashboard by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error displaying dashboard: {str(e)}")
            self.main_window.log_feedback(f"Error displaying dashboard: {str(e)}")
            logger.error(f"Error displaying dashboard: {str(e)}")

    def backup_database(self):
        """Backup the database."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Backup database failed: Permission denied")
            return
        try:
            backup_path = filedialog.asksaveasfilename(defaultextension=".db", filetypes=[("Database files", "*.db")])
            if not backup_path:
                self.main_window.log_feedback("Backup database cancelled: No file selected")
                logger.info(f"Backup database cancelled by user {self.username}: No file selected")
                return
            self.issue_mgr.backup_issue_database(backup_path, self.username, self.role)
            show_info(self.main_window, f"Database backed up to {backup_path}")
            self.main_window.log_feedback(f"Database backed up to {backup_path}")
            logger.info(f"Database backed up to {backup_path} by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error backing up database: {str(e)}")
            self.main_window.log_feedback(f"Error backing up database: {str(e)}")
            logger.error(f"Error backing up database: {str(e)}")

    def load_issues(self):
        """Load all issue records into the table."""
        try:
            for item in self.tree.get_children():
                self.tree.delete(item)
            records = self.issue_mgr.get_all_issues(self.username, self.role)
            for r in records:
                self.tree.insert("", "end", values=(
                    r['issue_id'], r['department'], r['quantity'], r['date_issued'],
                    r['issued_by'] or '', r['purpose'] or ''
                ))
            self.main_window.log_feedback(f"Loaded {len(records)} issue records")
            logger.info(f"Loaded {len(records)} issue records by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error loading issues: {str(e)}")
            self.main_window.log_feedback(f"Error loading issues: {str(e)}")
            logger.error(f"Error loading issues: {str(e)}")

    def refresh_data(self):
        """Refresh tab data."""
        logger.debug(f"Refreshing IssuesTab with username={self.username}, role={self.role}")
        self.load_issues()
        self.search_entry.delete(0, "end")
        self.search_field.set("All")
        self.search_department.set("")
        self.start_date.delete(0, "end")
        self.end_date.delete(0, "end")
        self.main_window.log_feedback("Refreshed IssuesTab data")
        self.main_frame.update_idletasks()
        logger.info("Refreshed IssuesTab data")