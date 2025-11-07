import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox
from modules.ream_manager import ReamManager
from gui.utils import show_error, show_info, validate_not_empty, validate_positive_int
import logging
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from typing import List, Dict, Optional
import pandas as pd
import inspect
import re
import os
import subprocess
import threading
from threading import Event
from tkinter import filedialog, messagebox
from PIL import Image
from datetime import datetime
from tkcalendar import Calendar

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/reams_tab.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helper: safe default term selection
# ----------------------------------------------------------------------
def _safe_default_term(ream_mgr, combo_widget):
    """Return the first term (sorted) or '' and set the combo box safely."""
    if not ream_mgr.valid_terms:
        combo_widget.set("")
        return ""
    terms = sorted(ream_mgr.valid_terms)          
    default = terms[0]
    values = combo_widget.cget("values")
    if default in values:
        combo_widget.set(default)
    else:
        combo_widget.set("")
    return default

    
class RecordStudentReamForm(ctk.CTkToplevel):
    def __init__(self, parent, ream_mgr, username, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Record Student Ream")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.ream_mgr = ream_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing RecordStudentReamForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Admission No", "admission_no", ctk.CTkEntry, {}),
            ("Quantity", "quantity", ctk.CTkEntry, {}),
            ("Term", "term", ctk.CTkComboBox,
             {"values": sorted(ream_mgr.valid_terms)}),                    
            ("Form", "form", ctk.CTkComboBox,
             {"values": [""] + list(ream_mgr.valid_forms)}),
            ("Date Brought (YYYY-MM-DD)", "date_brought", ctk.CTkEntry, {}),
            ("Recorded By", "recorded_by", ctk.CTkEntry, {"state": "readonly"})
        ]

        for label, key, widget_type, kwargs in fields:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            if "values" in kwargs:
                self.entries[key] = widget_type(frame, values=kwargs["values"],
                                                font=("Arial", 12), height=35)
            else:
                self.entries[key] = widget_type(frame, font=("Arial", 12), height=35, **kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=5)
            frame.pack(fill="x", pady=5)
            logger.debug(f"Added field: {label}")

        # Auto-populate recorded_by
        self.entries['recorded_by'].insert(0, self.username)
        logger.debug(f"Auto-populated recorded_by with {self.username}")

        # Set default date to today
        self.entries['date_brought'].insert(0, datetime.now().strftime("%Y-%m-%d"))
        logger.debug("Set default date_brought to today")

        # ---- SAFE DEFAULT TERM ----
        _safe_default_term(self.ream_mgr, self.entries['term'])

        # Set default form to empty
        self.entries['form'].set("")

        # Calendar button for date_brought
        calendar_button = ctk.CTkButton(
            form_frame,
            text="Pick Date",
            image=self.icons['calendar'],
            compound="left",
            command=lambda: self.show_calendar(self.entries['date_brought']),
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12),
            width=100,
            height=35
        )
        calendar_button.pack(pady=5)

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
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
        ).pack(side="left", padx=5)
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
        ).pack(side="left", padx=5)
        button_frame.pack(pady=10)

        # Bind Enter / Escape
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("RecordStudentReamForm initialized")

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
        top.geometry("300x300")
        top.transient(self)
        top.grab_set()
        cal = Calendar(top, selectmode="day", date_pattern="yyyy-mm-dd")
        cal.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkButton(top, text="Confirm", command=set_date).pack(pady=5)
        logger.info("Opened calendar widget")

    def submit(self):
        try:
            admission_no = self.entries['admission_no'].get().strip()
            quantity = self.entries['quantity'].get().strip()
            term = self.entries['term'].get()
            form = self.entries['form'].get() or None
            date_brought = self.entries['date_brought'].get().strip()
            recorded_by = self.entries['recorded_by'].get().strip() or None

            # === VALIDATIONS ===
            if not validate_not_empty(admission_no, "Admission No", self.log_feedback):
                show_error(self, "Admission No is required"); return
            if not validate_not_empty(quantity, "Quantity", self.log_feedback):
                show_error(self, "Quantity is required"); return
            if not validate_positive_int(quantity, self.log_feedback):
                show_error(self, "Quantity must be a positive integer"); return
            if not validate_not_empty(term, "Term", self.log_feedback):
                show_error(self, "Term is required"); return
            if form and form not in self.ream_mgr.valid_forms:
                show_error(self, f"Invalid form: {form}"); return
            if not validate_not_empty(date_brought, "Date Brought", self.log_feedback):
                show_error(self, "Date Brought is required"); return
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_brought):
                show_error(self, "Date must be YYYY-MM-DD"); return
            if recorded_by and not re.match(r'^[A-Za-z0-9_]{3,20}$', recorded_by):
                show_error(self, "Recorded By: 3-20 alphanum + _"); return

            # === CALL record_ream ===
            self.ream_mgr.record_ream(
                admission_no=admission_no,
                quantity=int(quantity),
                term=term,
                form=form,
                user=self.username,
                role="staff",  
                recorded_by=recorded_by,
                date_brought=date_brought  
            )
            show_info(self, f"Recorded {quantity} ream(s) for {admission_no}")
            self.log_feedback(f"Recorded {quantity} ream(s) for {admission_no}")
            if self.callback:
                self.callback()
            self.destroy()

        except Exception as e:
            show_error(self, f"Error: {str(e)}")
            self.log_feedback(f"Error recording ream: {str(e)}")
            logger.error(f"Error: {e}")

class RecordPurchaseForm(ctk.CTkToplevel):
    def __init__(self, parent, ream_mgr, username, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Record School Purchase")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.ream_mgr = ream_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing RecordPurchaseForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Quantity", "quantity", ctk.CTkEntry, {}),
            ("Supplier", "supplier", ctk.CTkEntry, {}),
            ("Invoice No", "invoice_no", ctk.CTkEntry, {}),
            ("Purchase Date (YYYY-MM-DD)", "purchase_date", ctk.CTkEntry, {}),
            ("Recorded By", "recorded_by", ctk.CTkEntry, {"state": "readonly"}),
            ("Remarks", "remarks", ctk.CTkEntry, {})
        ]

        for label, key, widget_type, kwargs in fields:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.entries[key] = widget_type(frame, font=("Arial", 12), height=35, **kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=5)
            frame.pack(fill="x", pady=5)
            logger.debug(f"Added field: {label}")

        # Auto-populate recorded_by
        self.entries['recorded_by'].insert(0, self.username)
        logger.debug(f"Auto-populated recorded_by with {self.username}")

        # Set default purchase date to today
        self.entries['purchase_date'].insert(0, datetime.now().strftime("%Y-%m-%d"))
        logger.debug("Set default purchase_date to today")

        # Calendar button for purchase_date
        calendar_button = ctk.CTkButton(
            form_frame,
            text="Pick Date",
            image=self.icons['calendar'],
            compound="left",
            command=lambda: self.show_calendar(self.entries['purchase_date']),
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12),
            width=100,
            height=35
        )
        calendar_button.pack(pady=5)

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
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
        ).pack(side="left", padx=5)
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
        ).pack(side="left", padx=5)
        button_frame.pack(pady=10)

        # Bind Enter to submit and Escape to cancel
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("RecordPurchaseForm initialized")

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
        top.geometry("300x300")
        top.transient(self)
        top.grab_set()
        cal = Calendar(top, selectmode="day", date_pattern="yyyy-mm-dd")
        cal.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkButton(top, text="Confirm", command=set_date).pack(pady=5)
        logger.info("Opened calendar widget")

    def submit(self):
        """Submit the school purchase form."""
        try:
            quantity = self.entries['quantity'].get().strip()
            supplier = self.entries['supplier'].get().strip()
            invoice_no = self.entries['invoice_no'].get().strip()
            purchase_date = self.entries['purchase_date'].get().strip()
            recorded_by = self.entries['recorded_by'].get().strip() or None
            remarks = self.entries['remarks'].get().strip() or None

            if not validate_not_empty(quantity, "Quantity", self.log_feedback):
                show_error(self, "Quantity is required")
                return
            if not validate_positive_int(quantity, self.log_feedback): 
                show_error(self, "Quantity must be a positive integer")
                return
            if not validate_not_empty(supplier, "Supplier", self.log_feedback):
                show_error(self, "Supplier is required")
                return
            if not validate_not_empty(invoice_no, "Invoice No", self.log_feedback):
                show_error(self, "Invoice No is required")
                return
            if not validate_not_empty(purchase_date, "Purchase Date", self.log_feedback):
                show_error(self, "Purchase Date is required")
                return
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', purchase_date):
                show_error(self, "Purchase Date must be in YYYY-MM-DD format")
                self.log_feedback("Invalid purchase_date format")
                return
            if recorded_by and not re.match(r'^[A-Za-z0-9_]{3,20}$', recorded_by):
                show_error(self, "Recorded By must be 3-20 alphanumeric characters with underscores")
                self.log_feedback("Invalid recorded_by format")
                return

            self.ream_mgr.add_purchase(
                quantity=int(quantity),
                supplier=supplier,
                invoice_no=invoice_no,
                user=self.username,       
                role="staff",             
                recorded_by=recorded_by,   
                remarks=remarks
                # purchase_date is NOT passed — method uses today
            )
            show_info(self, "Purchase recorded successfully")
            self.log_feedback(f"Recorded purchase of {quantity} reams from {supplier} (invoice {invoice_no})")
            logger.info(f"Recorded purchase of {quantity} reams from {supplier} (invoice {invoice_no}) by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()
        except Exception as e:
            show_error(self, f"Error recording purchase: {str(e)}")
            self.log_feedback(f"Error recording purchase for invoice {invoice_no}: {str(e)}")
            logger.error(f"Error recording purchase for invoice {invoice_no}: {str(e)}")


class DeleteStudentReamForm(ctk.CTkToplevel):
    def __init__(self, parent, ream_mgr, username, role, icons, selected_record=None, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Delete Student Ream Record")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.ream_mgr = ream_mgr
        self.username = username
        self.role = role
        self.icons = icons
        self.selected_record = selected_record  # List: [record_id] or full dict
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing DeleteStudentReamForm for user {username}")

        # === 1. CREATE WIDGETS FIRST ===
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        ctk.CTkLabel(form_frame, text="Record ID:", text_color="#FFFFFF").pack(side="left", padx=5)
        self.record_id_entry = ctk.CTkEntry(form_frame, font=("Arial", 12), height=35)
        self.record_id_entry.pack(side="left", fill="x", expand=True, padx=5)
        form_frame.pack(fill="x", pady=5)

        # === 2. NOW FILL THE ENTRY (after creation) ===
        if selected_record:
            try:
                # Accept both [id] list and full dict
                record_id = selected_record[0] if isinstance(selected_record, (list, tuple)) else selected_record.get('record_id')
                record_id = int(record_id)
                self.record_id_entry.insert(0, str(record_id))
                self.record_id_entry.configure(state="disabled")
            except (ValueError, IndexError, TypeError):
                self.record_id_entry.insert(0, "")
                self.record_id_entry.configure(state="normal")

        # === 3. BUTTONS ===
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        button_frame.pack(pady=10)

        ctk.CTkButton(
            button_frame,
            text="Submit",
            image=self.icons.get('save'),
            compound="left",
            command=self.submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            button_frame,
            text="Cancel",
            image=self.icons.get('cancel'),
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)

        # === 4. KEY BINDINGS ===
        self.bind("<Return>", lambda e: self.submit())
        self.bind("<Escape>", lambda e: self.destroy())

        logger.debug("DeleteStudentReamForm initialized")

    def submit(self):
        """Submit the delete student ream form."""
        try:
            # --- 1. Get and validate record_id ---
            raw_id = self.record_id_entry.get().strip()
            if not raw_id:
                show_error(self, "Record ID is required")
                self.log_feedback("Delete ream record failed: Record ID is required")
                return

            try:
                record_id = int(raw_id)
                if record_id <= 0:
                    raise ValueError
            except ValueError:
                show_error(self, "Record ID must be a positive number")
                self.log_feedback(f"Delete ream record failed: Invalid ID '{raw_id}'")
                return

            # --- 2. Fetch record using int ID ---
            record = self.ream_mgr.get_record_by_id(
                record_id=record_id,
                user=self.username,
                role=self.role
            )
            if not record:
                show_error(self, f"Ream record {record_id} not found")
                self.log_feedback(f"Delete ream record failed: Record {record_id} not found")
                return

            # --- 3. Confirm deletion ---
            if not messagebox.askyesno(
                "Confirm Delete",
                f"Permanently delete ream record {record_id}?\n"
                f"Student: {record['name']} ({record['admission_no']})\n"
                f"Quantity: {record['quantity']} | Date: {record['date_brought']}",
                parent=self
            ):
                self.log_feedback(f"Delete ream record {record_id} cancelled")
                logger.info(f"Delete ream record {record_id} cancelled by {self.username}")
                return

            # --- 4. Delete using int ID ---
            self.ream_mgr.delete_record(
                record_id=record_id,
                user=self.username,
                role=self.role
            )

            # --- 5. Success ---
            if self.callback:
                self.callback(record)
            show_info(self, f"Ream record {record_id} deleted successfully")
            self.log_feedback(f"Ream record {record_id} deleted successfully")
            logger.info(f"Ream record {record_id} deleted by {self.username}")
            self.destroy()

        except Exception as e:
            error_msg = f"Error deleting ream record {raw_id}: {str(e)}"
            show_error(self, error_msg)
            self.log_feedback(error_msg)
            logger.error(error_msg)


class DeletePurchaseForm(ctk.CTkToplevel):
    def __init__(self, parent, ream_mgr, username, role, icons, selected_record=None, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Delete Purchase Record")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.ream_mgr = ream_mgr
        self.username = username
        self.role = role
        self.icons = icons
        self.selected_record = selected_record
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing DeletePurchaseForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        ctk.CTkLabel(form_frame, text="Purchase ID:", text_color="#FFFFFF").pack(side="left")
        self.purchase_id_entry = ctk.CTkEntry(form_frame, font=("Arial", 12), height=35)
        if selected_record:
            self.purchase_id_entry.insert(0, selected_record[0])
            self.purchase_id_entry.configure(state="disabled")
        self.purchase_id_entry.pack(side="left", fill="x", expand=True, padx=5)
        form_frame.pack(fill="x", pady=5)

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
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
        ).pack(side="left", padx=5)
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
        ).pack(side="left", padx=5)
        button_frame.pack(pady=10)

        # Bind Enter to submit and Escape to cancel
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("DeletePurchaseForm initialized")

    def submit(self):
        """Submit the delete purchase form."""
        try:
            purchase_id = self.purchase_id_entry.get().strip()
            if not validate_not_empty(purchase_id, "Purchase ID", self.log_feedback):
                show_error(self, "Purchase ID is required")
                return
            record = self.ream_mgr.get_purchase_by_id(
                purchase_id=purchase_id,
                user=self.username,
                role=self.role
            )
            if not record:
                show_error(self, "Purchase record not found")
                self.log_feedback("Delete purchase record failed: Record not found")
                return
            if not messagebox.askyesno("Confirm Delete", f"Delete purchase record {purchase_id}?", parent=self):
                self.log_feedback(f"Delete purchase record {purchase_id} cancelled")
                logger.info(f"Delete purchase record {purchase_id} cancelled by {self.username}")
                return
            self.ream_mgr.delete_purchase(
                purchase_id=purchase_id,
                user=self.username,
                role=self.role
            )
            if self.callback:
                self.callback(record)
            show_info(self, f"Purchase record {purchase_id} deleted successfully")
            self.log_feedback(f"Purchase record {purchase_id} deleted successfully")
            logger.info(f"Purchase record {purchase_id} deleted by {self.username}")
            self.destroy()
        except Exception as e:
            show_error(self, f"Error deleting purchase record: {str(e)}")
            self.log_feedback(f"Error deleting purchase record {purchase_id}: {str(e)}")
            logger.error(f"Error deleting purchase record {purchase_id}: {str(e)}")


class ReamsTab:
    def __init__(self, parent, db_name: str, username: Optional[str], role: Optional[str],
                 main_window, icons):
        self.parent = parent
        self.db_name = db_name
        self.username = username
        self.role = role
        self.main_window = main_window
        self.icons = icons
        self.ream_mgr = ReamManager(db_name)
        self.deleted_ream_records: List[Dict] = []
        self.deleted_purchase_records: List[Dict] = []
        self.sort_column_name = None
        self.sort_reverse = False
        self.sort_purchase_column_name = None
        self.sort_purchase_reverse = False
        self._refreshing = False
        self._dashboard_open = False

        self.student_entries: Dict[str, ctk.CTkBaseClass] = {}
        self.purchase_entries: Dict[str, ctk.CTkBaseClass] = {}

        self.setup_gui()
        logger.info(f"Initialized ReamsTab with username={username}, role={role}")
        self.main_window.log_feedback("ReamsTab initialized; data will load after login")

    def setup_gui(self):
        """Set up the ReamsTab GUI."""
        self.main_frame = ctk.CTkFrame(self.parent, fg_color="#2B2B2B", corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.role and self.role not in {'admin', 'staff', 'viewer'}:
            ctk.CTkLabel(self.main_frame,
                         text="Permission Denied: Admin, Staff, or Viewer role required",
                         font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=20)
            self.main_window.log_feedback("Access denied: Admin, Staff, or Viewer role required")
            return

        # === INLINE STUDENT REAM FORM ===
        student_form_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        student_form_frame.pack(fill="x", padx=10, pady=5)

        fields_student = [
            ("Admission No", "admission_no", ctk.CTkEntry, {}),
            ("Quantity", "quantity", ctk.CTkEntry, {}),
            ("Term", "term", ctk.CTkComboBox,
             {"values": sorted(self.ream_mgr.valid_terms)}),               
            ("Form", "form", ctk.CTkComboBox,
             {"values": [""] + list(self.ream_mgr.valid_forms)}),
            ("Recorded By", "recorded_by", ctk.CTkEntry, {"state": "readonly"})
        ]
        for label, key, wtype, kwargs in fields_student:
            row = ctk.CTkFrame(student_form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(row, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.student_entries[key] = wtype(row, font=("Arial", 12), height=35, **kwargs)
            self.student_entries[key].pack(side="left", fill="x", expand=True, padx=5)
            row.pack(fill="x", pady=2)

        self.student_entries['recorded_by'].insert(0, self.username or "")

        # ---- SAFE DEFAULT TERM ----
        _safe_default_term(self.ream_mgr, self.student_entries['term'])

        self.student_entries['form'].set("")

        # === INLINE PURCHASE FORM ===
        purchase_form_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        purchase_form_frame.pack(fill="x", padx=10, pady=5)

        fields_purchase = [
            ("Quantity", "quantity", ctk.CTkEntry, {}),
            ("Supplier", "supplier", ctk.CTkEntry, {}),
            ("Invoice No", "invoice_no", ctk.CTkEntry, {}),
            ("Recorded By", "recorded_by", ctk.CTkEntry, {"state": "readonly"}),
            ("Remarks", "remarks", ctk.CTkEntry, {})
        ]
        for label, key, wtype, kwargs in fields_purchase:
            row = ctk.CTkFrame(purchase_form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(row, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.purchase_entries[key] = wtype(row, font=("Arial", 12), height=35, **kwargs)
            self.purchase_entries[key].pack(side="left", fill="x", expand=True, padx=5)
            row.pack(fill="x", pady=2)

        self.purchase_entries['recorded_by'].insert(0, self.username or "")

        # === INLINE ACTION BUTTONS ===
        inline_btn_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B")
        inline_btn_frame.pack(fill="x", padx=10, pady=5)

        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                inline_btn_frame, text="Record Student Ream",
                image=self.icons.get('save'), compound="left",
                command=self.open_record_student_ream_form,
                fg_color="#2B6CB0", hover_color="#1E4E79"
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                inline_btn_frame, text="Record Purchase",
                image=self.icons.get('save'), compound="left",
                command=self.open_record_purchase_form,
                fg_color="#2B6CB0", hover_color="#1E4E79"
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                inline_btn_frame, text="Delete Student Ream",
                image=self.icons.get('delete'), compound="left",
                command=self.open_delete_ream_form,
                fg_color="#C53030", hover_color="#9B2A2A"
            ).pack(side="left", padx=5)

            ctk.CTkButton(
                inline_btn_frame, text="Delete Purchase",
                image=self.icons.get('delete'), compound="left",
                command=self.open_delete_purchase_form,
                fg_color="#C53030", hover_color="#9B2A2A"
            ).pack(side="left", padx=5)

        # Search bar
        logger.debug("Creating search_frame in ReamsTab")
        self.search_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.search_frame, text="Search Records:", width=100, text_color="#FFFFFF").pack(side="left")
        self.search_field = ctk.CTkComboBox(self.search_frame, values=["All", "Adm No", "Name", "Term", "Form", "Recorded By"], font=("Arial", 12), height=35)
        self.search_field.pack(side="left", padx=5)
        self.search_entry = ctk.CTkEntry(self.search_frame, font=("Arial", 12), height=35)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkLabel(self.search_frame, text="Term:", width=50, text_color="#FFFFFF").pack(side="left")
        self.search_term = ctk.CTkComboBox(self.search_frame, values=["", "Term 1", "Term 2", "Term 3"], font=("Arial", 12), height=35)
        self.search_term.pack(side="left", padx=5)
        ctk.CTkLabel(self.search_frame, text="Form:", width=50, text_color="#FFFFFF").pack(side="left")
        self.search_form = ctk.CTkComboBox(self.search_frame, values=[""] + list(self.ream_mgr.valid_forms), font=("Arial", 12), height=35)
        self.search_form.pack(side="left", padx=5)
        ctk.CTkLabel(self.search_frame, text="Min Qty:", width=50, text_color="#FFFFFF").pack(side="left")
        self.search_min_qty = ctk.CTkEntry(self.search_frame, width=50, font=("Arial", 12), height=35)
        self.search_min_qty.pack(side="left", padx=5)
        ctk.CTkLabel(self.search_frame, text="Max Qty:", width=50, text_color="#FFFFFF").pack(side="left")
        self.search_max_qty = ctk.CTkEntry(self.search_frame, width=50, font=("Arial", 12), height=35)
        self.search_max_qty.pack(side="left", padx=5)
        ctk.CTkButton(
            self.search_frame,
            text="Search",
            image=self.icons['search'] if 'search' in self.icons else None,
            compound="left",
            command=self.search_records,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left")
        self.search_frame.pack(pady=5, padx=10, fill="x")

        # Date range filter
        logger.debug("Creating date_frame in ReamsTab")
        self.date_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.date_frame, text="Start Date (YYYY-MM-DD):", text_color="#FFFFFF").pack(side="left")
        self.start_date = ctk.CTkEntry(self.date_frame, width=100, font=("Arial", 12), height=35)
        self.start_date.pack(side="left", padx=5)
        ctk.CTkLabel(self.date_frame, text="End Date (YYYY-MM-DD):", text_color="#FFFFFF").pack(side="left")
        self.end_date = ctk.CTkEntry(self.date_frame, width=100, font=("Arial", 12), height=35)
        self.end_date.pack(side="left", padx=5)
        self.date_frame.pack(pady=5, padx=10, fill="x")

        # Action frame
        logger.debug("Creating action_frame in ReamsTab")
        self.action_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                self.action_frame,
                text="Export to CSV",
                image=self.icons['export'] if 'export' in self.icons else None,
                compound="left",
                command=self.export_to_csv,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
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
                text="Contribution Report",
                image=self.icons['report'] if 'report' in self.icons else None,
                compound="left",
                command=self.show_contribution_report,
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

            ctk.CTkButton(
                self.action_frame,
                text="Import Reams from Excel",
                image=self.icons.get('excel') or self.icons.get('import'),
                compound="left",
                command=self.open_import_excel_form,
                fg_color="#1E6B3D",
                hover_color="#1A5A33",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)

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
        self.action_frame.pack(pady=5, padx=10, fill="x")

        # Progress bar
        logger.debug("Creating progress_frame in ReamsTab")
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=5)
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", text_color="#FFFFFF")
        self.progress_label.pack()
        self.progress_frame.pack(pady=5, padx=10, fill="x")

        # Reams table
        logger.debug("Creating ream_table_frame in ReamsTab")
        self.ream_table_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ream_columns = ("Record ID", "Adm No", "Name", "Form", "Quantity", "Term", "Date Brought", "Recorded By")
        self.ream_tree = ttk.Treeview(self.ream_table_frame, columns=ream_columns, show="headings")
        for col in ream_columns:
            self.ream_tree.heading(col, text=col, command=lambda c=col: self.sort_column(c, is_purchase=False))
            self.ream_tree.column(col, width=100)
        self.ream_tree.pack(side="left", fill="both", expand=True)
        ream_scrollbar = ctk.CTkScrollbar(self.ream_table_frame, command=self.ream_tree.yview)
        ream_scrollbar.pack(side="right", fill="y")
        self.ream_tree.configure(yscrollcommand=ream_scrollbar.set)
        self.ream_tree.bind("<<TreeviewSelect>>", self.on_select_ream_record)
        self.ream_table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Purchases table
        logger.debug("Creating purchase_table_frame in ReamsTab")
        self.purchase_table_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        purchase_columns = ("Purchase ID", "Quantity", "Supplier", "Invoice No", "Date", "Recorded By", "Remarks")
        self.purchase_tree = ttk.Treeview(self.purchase_table_frame, columns=purchase_columns, show="headings")
        for col in purchase_columns:
            self.purchase_tree.heading(col, text=col, command=lambda c=col: self.sort_column(c, is_purchase=True))
            self.purchase_tree.column(col, width=100)
        self.purchase_tree.pack(side="left", fill="both", expand=True)
        purchase_scrollbar = ctk.CTkScrollbar(self.purchase_table_frame, command=self.purchase_tree.yview)
        purchase_scrollbar.pack(side="right", fill="y")
        self.purchase_tree.configure(yscrollcommand=purchase_scrollbar.set)
        self.purchase_tree.bind("<<TreeviewSelect>>", self.on_select_purchase_record)
        self.purchase_table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_data()
        self.main_frame.update_idletasks()
        logger.info("ReamsTab GUI initialized")

    def open_record_student_ream_form(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open record student ream form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Record Student Ream",
            form_class=RecordStudentReamForm,
            ream_mgr=self.ream_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_record_purchase_form(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open record purchase form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Record Purchase",
            form_class=RecordPurchaseForm,
            ream_mgr=self.ream_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_delete_ream_form(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            return

        selected = self.ream_tree.selection()
        if not selected:
            show_error(self.main_window, "Please select a ream record")
            return

        values = self.ream_tree.item(selected[0])['values']
        if not values:
            show_error(self.main_window, "Invalid selection")
            return

        try:
            record_id = int(values[0])  # First column = record_id
        except (ValueError, IndexError):
            show_error(self.main_window, "Invalid Record ID")
            return

        # Fetch full record to pass rich data
        record = self.ream_mgr.get_record_by_id(record_id, self.username, self.role)
        if not record:
            show_error(self.main_window, f"Record {record_id} not found")
            return

        def callback(deleted_record):
            if deleted_record:
                self.deleted_ream_records.append(deleted_record)
            self.refresh_data()

        self.main_window.open_form_window(
            title="Delete Student Ream Record",
            form_class=DeleteStudentReamForm,
            ream_mgr=self.ream_mgr,
            username=self.username,
            role=self.role,
            icons=self.icons,
            selected_record=record,  # ← Pass full record dict
            callback=callback,
            log_feedback=self.main_window.log_feedback
        )

    def open_delete_purchase_form(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open delete purchase form failed: Permission denied")
            return
        selected = self.purchase_tree.selection()
        selected_record = None
        if selected:
            selected_record = self.purchase_tree.item(selected[0])['values']
        def callback(record):
            if record:
                self.deleted_purchase_records.append(record)
            self.refresh_data()
        self.main_window.open_form_window(
            title="Delete Purchase Record",
            form_class=DeletePurchaseForm,
            ream_mgr=self.ream_mgr,
            username=self.username,
            role=self.role,
            icons=self.icons,
            selected_record=selected_record,
            callback=callback,
            log_feedback=self.main_window.log_feedback
        )

    def refresh_data(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            if not self.username or not self.role:
                return
            if self.role not in {'admin', 'staff', 'viewer'}:
                return

            # === REAM RECORDS ===
            ream_records = self.ream_mgr.fetch_all_records(self.username, self.role)
            self.ream_tree.delete(*self.ream_tree.get_children())
            for r in ream_records:
                self.ream_tree.insert("", "end", values=(
                    r['record_id'], r['admission_no'], r['name'], r['form'],
                    r['quantity'], r['term'], r['date_brought'], r['recorded_by'] or ''
                ))

            # === PURCHASE RECORDS ===
            purchase_records = self.ream_mgr.fetch_purchase_records(self.username, self.role)
            self.purchase_tree.delete(*self.purchase_tree.get_children())
            for p in purchase_records:
                self.purchase_tree.insert("", "end", values=(
                    p['purchase_id'], p['quantity'], p['supplier'], p['invoice_no'],
                    p['purchase_date'], p['recorded_by'] or '', p['remarks'] or ''
                ))

            self.main_window.log_feedback(f"Loaded {len(ream_records)} ream records and {len(purchase_records)} purchase records")
            logger.info(f"Loaded {len(ream_records)} ream records and {len(purchase_records)} purchase records for {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error loading records: {e}")
        finally:
            self._refreshing = False

    def sort_column(self, col: str, is_purchase: bool):
        tree = self.purchase_tree if is_purchase else self.ream_tree
        sort_column_name = self.sort_purchase_column_name if is_purchase else self.sort_column_name
        sort_reverse = self.sort_purchase_reverse if is_purchase else self.sort_reverse
        try:
            records = [(tree.set(item, col), item) for item in tree.get_children()]
            if sort_column_name == col:
                sort_reverse = not sort_reverse
            else:
                sort_reverse = False
                sort_column_name = col

            def convert(value):
                try:
                    if col in ["Record ID", "Purchase ID", "Quantity"]:
                        return int(value)
                    return value.lower()
                except (ValueError, AttributeError):
                    return value

            records.sort(key=lambda x: convert(x[0]), reverse=sort_reverse)

            for index, (value, item) in enumerate(records):
                tree.move(item, "", index)

            for column in tree["columns"]:
                tree.heading(column, text=column)
            arrow = " ↓" if not sort_reverse else " ↑"
            tree.heading(col, text=col + arrow)

            if is_purchase:
                self.sort_purchase_column_name = sort_column_name
                self.sort_purchase_reverse = sort_reverse
            else:
                self.sort_column_name = sort_column_name
                self.sort_reverse = sort_reverse

            self.main_window.log_feedback(f"Sorted {'purchase' if is_purchase else 'ream'} table by {col} {'descending' if sort_reverse else 'ascending'}")
            logger.info(f"Sorted {'purchase' if is_purchase else 'ream'} table by {col} {'descending' if sort_reverse else 'ascending'} by user {self.username}")
        except Exception as e:
            self.main_window.log_feedback(f"Error sorting {'purchase' if is_purchase else 'ream'} table by {col}: {str(e)}")
            logger.error(f"Error sorting {'purchase' if is_purchase else 'ream'} table by {col} for user {self.username}: {str(e)}")
            show_error(self.main_window, f"Error sorting {'purchase' if is_purchase else 'ream'} table: {str(e)}")

    def on_select_ream_record(self, event):
        selected = self.ream_tree.selection()
        if not selected:
            return
        item = self.ream_tree.item(selected[0])['values']
        record_id, admission_no, name, form, quantity, term, _, recorded_by = item
        self.student_entries['admission_no'].delete(0, "end")
        self.student_entries['admission_no'].insert(0, admission_no)
        self.student_entries['quantity'].delete(0, "end")
        self.student_entries['quantity'].insert(0, str(quantity))
        self.student_entries['term'].set(term)
        self.student_entries['form'].set(form or "")
        self.student_entries['recorded_by'].delete(0, "end")
        self.student_entries['recorded_by'].insert(0, recorded_by or "")
        self.main_window.log_feedback(f"Selected ream record: {record_id} for {admission_no}")
        logger.info(f"Selected ream record: {record_id} for {admission_no} by user {self.username}")

    def on_select_purchase_record(self, event):
        selected = self.purchase_tree.selection()
        if not selected:
            return
        item = self.purchase_tree.item(selected[0])['values']
        purchase_id, quantity, supplier, invoice_no, _, recorded_by, remarks = item
        self.purchase_entries['quantity'].delete(0, "end")
        self.purchase_entries['quantity'].insert(0, str(quantity))
        self.purchase_entries['supplier'].delete(0, "end")
        self.purchase_entries['supplier'].insert(0, supplier)
        self.purchase_entries['invoice_no'].delete(0, "end")
        self.purchase_entries['invoice_no'].insert(0, invoice_no)
        self.purchase_entries['recorded_by'].delete(0, "end")
        self.purchase_entries['recorded_by'].insert(0, recorded_by or "")
        self.purchase_entries['remarks'].delete(0, "end")
        self.purchase_entries['remarks'].insert(0, remarks or "")
        self.main_window.log_feedback(f"Selected purchase record: {purchase_id} for invoice {invoice_no}")
        logger.info(f"Selected purchase record: {purchase_id} for invoice {invoice_no} by user {self.username}")

    def undo_delete(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Undo delete failed: Permission denied")
            return
        if not (self.deleted_ream_records or self.deleted_purchase_records):
            show_error(self.main_window, "No deletions to undo")
            self.main_window.log_feedback("Undo delete failed: No deletions to undo")
            return
        try:
            self.progress_bar.set(0)
            self.progress_label.configure(text="Undoing deletion...")
            self.main_frame.update()

            total = len(self.deleted_ream_records) + len(self.deleted_purchase_records)
            restored_count = 0

            for record in self.deleted_ream_records:
                self.ream_mgr.record_ream(
                    record['admission_no'], record['quantity'], record['term'], record['form'],
                    record['date_brought'], record['recorded_by'], self.username
                )
                restored_count += 1
                self.progress_bar.set(restored_count / total)
                self.main_frame.update()

            for record in self.deleted_purchase_records:
                self.ream_mgr.add_purchase(
                    record['quantity'], record['supplier'], record['invoice_no'],
                    record['purchase_date'], record['recorded_by'], record['remarks'], self.username
                )
                restored_count += 1
                self.progress_bar.set(restored_count / total)
                self.main_frame.update()

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            self.deleted_ream_records.clear()
            self.deleted_purchase_records.clear()
            show_info(self.main_window, f"Restored {restored_count} records")
            self.main_window.log_feedback(f"Restored {restored_count} records")
            logger.info(f"Restored {restored_count} records by {self.username}")
            self.refresh_data()
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error undoing deletion: {str(e)}")
            self.main_window.log_feedback(f"Error undoing deletion: {str(e)}")
            logger.error(f"Error undoing deletion by {self.username}: {str(e)}")

    def search_records(self):
        try:
            keyword = self.search_entry.get().strip() or None
            term = self.search_term.get() or None
            form = self.search_form.get() or None
            min_qty = self.search_min_qty.get().strip() or None
            max_qty = self.search_max_qty.get().strip() or None
            start_date = self.start_date.get().strip() or None
            end_date = self.end_date.get().strip() or None

            if keyword and len(keyword) < 2:
                show_error(self.main_window, "Keyword must be at least 2 characters")
                self.main_window.log_feedback("Search failed: Keyword too short")
                return
            if min_qty and not validate_positive_int(min_qty, "Minimum Quantity", self.main_window.log_feedback):
                show_error(self.main_window, "Minimum Quantity must be a positive integer")
                return
            if max_qty and not validate_positive_int(max_qty, "Maximum Quantity", self.main_window.log_feedback):
                show_error(self.main_window, "Maximum Quantity must be a positive integer")
                return
            if min_qty and max_qty and int(min_qty) > int(max_qty):
                show_error(self.main_window, "Minimum Quantity must not exceed Maximum Quantity")
                self.main_window.log_feedback("Search failed: Invalid quantity range")
                return
            if start_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', start_date):
                show_error(self.main_window, "Start Date must be in YYYY-MM-DD format")
                self.main_window.log_feedback("Search failed: Invalid start date format")
                return
            if end_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', end_date):
                show_error(self.main_window, "End Date must be in YYYY-MM-DD format")
                self.main_window.log_feedback("Search failed: Invalid end date format")
                return

            records = self.ream_mgr.search_records(
                keyword=keyword, field=self.search_field.get(), term=term, form=form,
                min_qty=int(min_qty) if min_qty else None, max_qty=int(max_qty) if max_qty else None,
                start_date=start_date, end_date=end_date, user=self.username, role=self.role
            )

            self.ream_tree.delete(*self.ream_tree.get_children())
            for r in records:
                self.ream_tree.insert("", "end", values=(
                    r['record_id'], r['admission_no'], r['name'], r['form'],
                    r['quantity'], r['term'], r['date_brought'], r['recorded_by'] or ''
                ))
            self.main_window.log_feedback(f"Searched records with filters (keyword={keyword}, term={term}, form={form}, qty_range={min_qty}-{max_qty}, date_range={start_date}-{end_date}), found {len(records)} results")
            logger.info(f"Searched records with filters (keyword={keyword}, term={term}, form={form}, qty_range={min_qty}-{max_qty}, date_range={start_date}-{end_date}), found {len(records)} results by user {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error searching records: {str(e)}")
            self.main_window.log_feedback(f"Error searching records: {str(e)}")
            logger.error(f"Error searching records by user {self.username}: {str(e)}")

    def export_to_csv(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Export to CSV failed: Permission denied")
            return
        try:
            file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
            if not file_path:
                self.main_window.log_feedback("Export to CSV cancelled: No file selected")
                logger.info(f"Export to CSV cancelled by user {self.username}: No file selected")
                return
            self.progress_bar.set(0)
            self.progress_label.configure(text="Exporting to CSV...")
            self.main_frame.update()

            records = self.ream_mgr.fetch_all_records(self.username, self.role)
            total = len(records)
            df = pd.DataFrame(records, columns=['record_id', 'admission_no', 'name', 'form', 'quantity', 'term', 'date_brought', 'recorded_by'])
            for i in range(total):
                self.progress_bar.set((i + 1) / total)
                self.main_frame.update()
            df.to_csv(file_path, index=False)

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_info(self.main_window, f"Records exported to {file_path}")
            self.main_window.log_feedback(f"Records exported to {file_path}")
            logger.info(f"Records exported to {file_path} by user {self.username}")
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error exporting to CSV: {str(e)}")
            self.main_window.log_feedback(f"Error exporting to CSV: {str(e)}")
            logger.error(f"Error exporting to CSV by user {self.username}: {str(e)}")

    def export_to_pdf(self):
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
            self.progress_bar.set(0)
            self.progress_label.configure(text="Exporting to PDF...")
            self.main_frame.update()

            self.ream_mgr.export_ream_report_to_pdf(file_path, self.username, self.role)
            self.progress_bar.set(1.0)
            self.main_frame.update()

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_info(self.main_window, f"Records exported to {file_path}")
            self.main_window.log_feedback(f"Records exported to {file_path}")
            logger.info(f"Records exported to {file_path} by user {self.username}")
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error exporting to PDF: {str(e)}")
            self.main_window.log_feedback(f"Error exporting to PDF: {str(e)}")
            logger.error(f"Error exporting to PDF by user {self.username}: {str(e)}")


    def _export_contribution_excel(self, records):
        try:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx"), ("CSV files", "*.csv")]
            )
            if not file_path:
                return
            df = pd.DataFrame(records)
            df.to_excel(file_path, index=False)
            show_info(self.main_window, f"Exported to Excel:\n{file_path}")
            self.main_window.log_feedback(f"Contribution report -> Excel: {file_path}")
            logger.info(f"Contribution Excel export: {file_path}")
        except Exception as e:
            show_error(self.main_window, f"Excel export failed: {e}")
            logger.error(f"Excel export error: {e}")

    def _export_contribution_pdf(self, records):
        try:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")]
            )
            if not file_path:
                return

            df = pd.DataFrame(records)
            fig, ax = plt.subplots(figsize=(10, len(df) * 0.3 + 2))
            ax.axis('tight')
            ax.axis('off')
            table = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center', loc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1.2, 1.5)

            with PdfPages(file_path) as pdf:
                pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)

            show_info(self.main_window, f"Exported to PDF:\n{file_path}")
            self.main_window.log_feedback(f"Contribution report -> PDF: {file_path}")
            logger.info(f"Contribution PDF export: {file_path}")

        except Exception as e:
            show_error(self.main_window, f"PDF export failed: {e}")
            logger.error(f"PDF export error: {e}")

        
    def show_contribution_report(self):
        try:
            records = self.ream_mgr.get_ream_contribution_report(self.username, self.role)
            if not records:
                show_info(self.main_window, "No contribution data")
                return

            report_window = ctk.CTkToplevel(self.main_window)
            report_window.title("Ream Contribution Report")
            report_window.geometry("1200x750")
            report_window.configure(fg_color="#1E1E1E")

            # Header
            header = ctk.CTkFrame(report_window, fg_color="#1E1E1E")
            header.pack(fill="x", padx=10, pady=10)
            ctk.CTkLabel(header, text="Ream Contribution Report", font=("Arial", 18, "bold"), text_color="#FFFFFF").pack(side="left")
            btn_frame = ctk.CTkFrame(header, fg_color="transparent")
            btn_frame.pack(side="right")
            ctk.CTkButton(btn_frame, text="Excel", image=self.icons.get('excel'), command=lambda: self._export_contribution_excel(records), fg_color="#1E6B3D").pack(side="left", padx=3)
            ctk.CTkButton(btn_frame, text="PDF", image=self.icons.get('pdf'), command=lambda: self._export_contribution_pdf(records), fg_color="#B91C1C").pack(side="left", padx=3)
            ctk.CTkButton(btn_frame, text="Close", command=report_window.destroy, fg_color="#6B7280").pack(side="left", padx=3)

            # Table
            table_frame = ctk.CTkFrame(report_window, fg_color="#2B2B2B", corner_radius=10)
            table_frame.pack(fill="both", expand=True, padx=10, pady=10)
            columns = ("Form", "Stream", "Students", "Brought", "Required", "Remaining", "Excess", "Avg")
            tree = ttk.Treeview(table_frame, columns=columns, show="headings")
            widths = [90, 90, 90, 90, 90, 90, 90, 90]
            for col, w in zip(columns, widths):
                tree.heading(col, text=col)
                tree.column(col, width=w, anchor="center")
            tree.pack(side="left", fill="both", expand=True)
            sb = ctk.CTkScrollbar(table_frame, command=tree.yview)
            sb.pack(side="right", fill="y")
            tree.configure(yscrollcommand=sb.set)

            for r in records:
                remaining = r['remaining']
                excess = max(0, -remaining)
                status = "Complete" if remaining == 0 else "On Track" if remaining <= r['total_brought'] * 0.3 else "Behind"
                color = "#10B981" if remaining <= 0 else "#F59E0B" if status == "On Track" else "#EF4444"
                tree.insert("", "end", values=(
                    r['form'], r['stream'] or "N/A", r['total_students'], r['total_brought'],
                    r['required'], remaining, excess, f"{r['avg_per_student']:.2f}"
                ), tags=(status,))
                tree.tag_configure("Complete", foreground="#10B981")
                tree.tag_configure("On Track", foreground="#F59E0B")
                tree.tag_configure("Behind", foreground="#EF4444")

            # Summary
            total_students = sum(r['total_students'] for r in records)
            total_brought = sum(r['total_brought'] for r in records)
            total_required = sum(r['required'] for r in records)
            total_remaining = sum(r['remaining'] for r in records)
            total_excess = sum(max(0, -r['remaining']) for r in records)
            overall_percent = (total_brought / total_required) * 100 if total_required else 0

            footer = ctk.CTkFrame(report_window, fg_color="#1E4E79", corner_radius=8)
            footer.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(
                footer,
                text=f"SUMMARY: {total_students} students | {total_brought}/{total_required} reams | "
                     f"{total_remaining} remaining | {total_excess} excess | {overall_percent:.1f}% achieved",
                font=("Arial", 13, "bold"), text_color="#FFFFFF"
            ).pack(pady=8)

            self.main_window.log_feedback(f"Contribution report: {len(records)} groups")
        except Exception as e:
            show_error(self.main_window, f"Error: {e}")

    def show_dashboard(self):
        if getattr(self, "_dashboard_open", False):
            return
        self._dashboard_open = True
        try:
            dash = ctk.CTkToplevel(self.main_window)
            dash.title("Ream Management Dashboard")
            dash.geometry("1000x800")
            dash.configure(fg_color="#1E1E1E")
            dash.protocol("WM_DELETE_WINDOW", lambda: setattr(self, "_dashboard_open", False) or dash.destroy())

            canvas = ctk.CTkCanvas(dash, highlightthickness=0)
            canvas.pack(side="left", fill="both", expand=True)
            v_scroll = ctk.CTkScrollbar(dash, command=canvas.yview)
            v_scroll.pack(side="right", fill="y")
            canvas.configure(yscrollcommand=v_scroll.set)
            inner = ctk.CTkFrame(canvas, fg_color="#1E1E1E")
            inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_configure(event=None):
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.itemconfig(inner_id, width=event.width if event else dash.winfo_width())
            inner.bind("<Configure>", _on_configure)
            canvas.bind("<Configure>", _on_configure)

            def _section(title, cols, widths):
                frm = ctk.CTkFrame(inner, fg_color="#2B2B2B", corner_radius=10)
                frm.pack(fill="x", padx=15, pady=8)
                ctk.CTkLabel(frm, text=title, font=("Arial", 14, "bold"), text_color="#FFFFFF").pack(pady=(6, 3))
                tree = ttk.Treeview(frm, columns=cols, show="headings")
                for c, w in zip(cols, widths):
                    tree.heading(c, text=c)
                    tree.column(c, width=w, anchor="center")
                tree.pack(side="left", fill="both", expand=True)
                sb = ctk.CTkScrollbar(frm, command=tree.yview)
                sb.pack(side="right", fill="y")
                tree.configure(yscrollcommand=sb.set)
                return tree

            # Stock Status
            stock = _section("Stock Status", ("Metric", "Value"), [300, 200])
            total_reams = self.ream_mgr.get_total_reams(self.username, self.role)
            min_stock = self.ream_mgr.get_min_stock_alert(self.username, self.role)
            status = "Normal" if total_reams >= min_stock else "Low"
            for m, v in [("Total Reams", total_reams), ("Min Threshold", min_stock), ("Status", status)]:
                stock.insert("", "end", values=(m, v))

            # Recent Reams
            ream = _section("Recent Ream Records (Last 5)", ("ID", "Adm No", "Name", "Qty", "Term", "Date"), [60, 90, 120, 60, 80, 110])
            for r in self.ream_mgr.fetch_all_records(self.username, self.role)[:5]:
                ream.insert("", "end", values=(r['record_id'], r['admission_no'], r['name'], r['quantity'], r['term'], r['date_brought']))

            # Contribution
            contrib = _section("Contribution Summary", ("Form", "Students", "Brought", "Required", "Remaining", "Excess"), [80, 90, 90, 90, 90, 90])
            for row in self.ream_mgr.get_ream_contribution_report(self.username, self.role):
                remaining = row['remaining']
                excess = max(0, -remaining)
                contrib.insert("", "end", values=(row['form'], row['total_students'], row['total_brought'], row['required'], remaining, excess))

            self.main_window.log_feedback("Dashboard opened")
        except Exception as e:
            self._dashboard_open = False
            show_error(self.main_window, f"Dashboard error: {e}")


    def open_import_excel_form(self):
        """Open file dialog and import reams from Excel with progress & results."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Import Excel failed: Permission denied")
            return

        # === 1. File Selection ===
        file_path = filedialog.askopenfilename(
            title="Select Excel File for Ream Import",
            filetypes=[
                ("Excel Files", "*.xlsx *.xls"),
                ("All Files", "*.*")
            ],
            initialdir=os.path.expanduser("~/Desktop")
        )
        if not file_path:
            self.main_window.log_feedback("Import cancelled: No file selected")
            return

        # === 2. Progress Setup (Uses your existing progress_frame) ===
        self.progress_bar.set(0)
        self.progress_label.configure(text="Starting import...")
        self.main_frame.update_idletasks()

        def progress_callback(msg: str):
            """Update progress label and bar safely."""
            self.progress_label.configure(text=msg)
            # Simulate progress (optional: can be real % from backend)
            current = self.progress_bar.get()
            self.progress_bar.set(min(current + 0.05, 0.95))
            self.main_frame.update_idletasks()

        # === 3. Run Import in Background Thread ===

        cancel_event = Event()

        def run_import():
            try:
                result = self.ream_mgr.import_reams_from_excel(
                    file_path=file_path,
                    user=self.username,
                    role=self.role,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event
                )
                self.main_window.after(0, lambda: self._show_import_result(result, file_path))
            except Exception as e:
                self.main_window.after(0, lambda: self._handle_import_error(e))

        thread = threading.Thread(target=run_import, daemon=True)
        thread.start()

        # === 4. Add Cancel Button (Uses your action_frame) ===
        self._add_cancel_button(cancel_event, thread)


    def _show_import_result(self, result: dict, file_path: str):
        """Display final result with PDF handling."""
        try:
            # Final progress
            self.progress_bar.set(1.0)
            self.progress_label.configure(text="Import complete!")
            self.main_frame.update_idletasks()

            # Build message
            lines = [
                f"File: {os.path.basename(file_path)}",
                f"Imported: {result['success_count']} records",
            ]
            if result['error_count']:
                lines.append(f"Errors: {result['error_count']}")
            if result['skipped']:
                lines.append(f"Skipped: {len(result['skipped'])} rows")
            if result['missing_pdf_path']:
                lines.append(f"Missing Students PDF saved:")
                lines.append(f"   {os.path.basename(result['missing_pdf_path'])}")

            full_msg = "\n".join(lines)
            show_info(self.main_window, full_msg, title="Import Complete")

            # Offer to open PDF
            if result['missing_pdf_path'] and os.path.exists(result['missing_pdf_path']):
                if messagebox.askyesno(
                    "Open Report?",
                    f"Open missing students report?\n{os.path.basename(result['missing_pdf_path'])}",
                    parent=self.main_window
                ):
                    try:
                        os.startfile(result['missing_pdf_path'])  # Windows
                    except:
                        try:
                            subprocess.call(('open', result['missing_pdf_path']))  # macOS
                        except:
                            subprocess.call(('xdg-open', result['missing_pdf_path']))  # Linux

            # Log & Refresh
            self.main_window.log_feedback(
                f"Excel import: {result['success_count']} success, {result['error_count']} errors"
            )
            logger.info(f"Excel import result: {result}")
            self.refresh_data()

        except Exception as e:
            logger.error(f"Error displaying result: {e}")
            show_error(self.main_window, f"Failed to show result: {e}")
        finally:
            self._reset_progress()


    def _handle_import_error(self, error: Exception):
        """Handle import failure."""
        msg = f"Import failed: {str(error)}"
        show_error(self.main_window, msg)
        self.main_window.log_feedback(msg)
        logger.error(msg, exc_info=True)
        self._reset_progress()


    def _reset_progress(self):
        """Reset progress bar and label."""
        self.progress_label.configure(text="")
        self.progress_bar.set(0)
        self.main_frame.update_idletasks()


    def _add_cancel_button(self, cancel_event, thread):
        """Add a cancel button during import."""
        if hasattr(self, 'cancel_button') and self.cancel_button.winfo_exists():
            self.cancel_button.destroy()

        self.cancel_button = ctk.CTkButton(
            self.action_frame,  # Uses your existing action_frame
            text="Cancel Import",
            fg_color="#C53030",
            hover_color="#9B2A2A",
            width=120,
            height=35,
            corner_radius=8,
            command=lambda: self._cancel_import(cancel_event, thread)
        )
        self.cancel_button.pack(side="right", padx=5, pady=5)

        # Auto-remove when import finishes
        def check_done():
            if not thread.is_alive():
                if hasattr(self, 'cancel_button') and self.cancel_button.winfo_exists():
                    self.cancel_button.destroy()
            else:
                self.main_window.after(500, check_done)
        self.main_window.after(500, check_done)


    def _cancel_import(self, cancel_event, thread):
        """Cancel ongoing import."""
        cancel_event.set()
        self.progress_label.configure(text="Cancelling...")
        self.main_window.log_feedback("Import cancellation requested...")
        logger.info("User cancelled Excel import")



    def _close_dashboard(self, window):
        self._dashboard_open = False
        window.destroy()
        logger.debug("Dashboard window closed")

    def backup_database(self):
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
            self.progress_bar.set(0)
            self.progress_label.configure(text="Backing up database...")
            self.main_frame.update()

            self.ream_mgr.backup_ream_database(backup_path, self.username, self.role)
            self.progress_bar.set(1.0)
            self.main_frame.update()

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_info(self.main_window, f"Database backed up to {backup_path}")
            self.main_window.log_feedback(f"Database backed up to {backup_path}")
            logger.info(f"Database backed up to {backup_path} by user {self.username}")
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error backing up database: {str(e)}")
            self.main_window.log_feedback(f"Error backing up database: {str(e)}")
            logger.error(f"Error backing up database by user {self.username}: {str(e)}")

    # ------------------------------------------------------------------
    # clear_student_form – also uses the safe helper
    # ------------------------------------------------------------------
    def clear_student_form(self):
        for key in ['admission_no', 'quantity', 'recorded_by']:
            self.student_entries[key].delete(0, "end")
        _safe_default_term(self.ream_mgr, self.student_entries['term'])
        self.student_entries['form'].set("")
        self.main_window.log_feedback("Student ream form cleared")
        logger.info(f"Student ream form cleared by user {self.username}")

    def clear_purchase_form(self):
        for key in self.purchase_entries:
            self.purchase_entries[key].delete(0, "end")
        self.main_window.log_feedback("School purchase form cleared")
        logger.info(f"School purchase form cleared by user {self.username}")