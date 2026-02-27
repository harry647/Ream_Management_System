import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox
from modules.student_manager import StudentManager
from gui.utils import show_error, show_info
from modules.db_setup import get_logs_dir
import logging
import os
from typing import List, Dict, Optional
import time
import threading
from threading import Event
from PIL import Image
import json
from contextlib import contextmanager

class CancelledException(Exception):
    pass



# Configure logging
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'students_tab.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@contextmanager
def cancellable_timeout(seconds, cancel_event=None):
    """Context manager that allows safe cancellation after timeout."""
    if cancel_event is None:
        cancel_event = Event()

    def _raise_timeout():
        cancel_event.set()

    timer = threading.Timer(seconds, _raise_timeout)
    timer.start()
    try:
        yield cancel_event
    finally:
        timer.cancel()

class AddStudentForm(ctk.CTkToplevel):
    def __init__(self, parent, student_mgr, username, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Add Student")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing AddStudentForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Admission No", "admission_no", ctk.CTkEntry, {}),
            ("Name", "name", ctk.CTkEntry, {}),
            ("Form", "form", ctk.CTkComboBox, {"values": ["Form 1", "Form 2", "Form 3", "Form 4", "Grade 10", "Grade 11", "Grade 12"]}),
            ("Stream", "stream", ctk.CTkEntry, {}),
            ("Total Required", "total_required", ctk.CTkEntry, {"state": "disabled"})
        ]

        for label, key, widget_type, kwargs in fields:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.entries[key] = widget_type(frame, font=("Arial", 12), height=35, **kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=5)
            frame.pack(fill="x", pady=5)
            logger.debug(f"Added field: {label}")

        # Set default total_required based on form selection
        self.entries['form'].bind("<<ComboboxSelected>>", self.update_total_required)
        self.entries['form'].set("Form 1") 
        self.update_total_required(None)

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
        logger.debug("AddStudentForm initialized")

    def update_total_required(self, event):
        """Update total_required based on selected form."""
        try:
            form = self.entries['form'].get()
            ream_required = self.student_mgr.get_ream_required_per_form()
            total_required = ream_required.get(form, 8) 
            self.entries['total_required'].configure(state="normal")
            self.entries['total_required'].delete(0, "end")
            self.entries['total_required'].insert(0, str(total_required))
            self.entries['total_required'].configure(state="disabled")
        except Exception as e:
            logger.error(f"Error updating total_required: {str(e)}")
            show_error(self, f"Error updating total required: {str(e)}")

    def submit(self):
        """Submit the add student form."""
        try:
            admission_no = self.entries['admission_no'].get().strip()
            name = self.entries['name'].get().strip()
            form = self.entries['form'].get().strip()
            stream = self.entries['stream'].get().strip() or None
            total_required = self.entries['total_required'].get().strip()

            if not admission_no or not name:
                show_error(self, "Admission Number and Name are required")
                self.log_feedback("Add student failed: Admission Number and Name required")
                return

            self.student_mgr.add_student(admission_no, name, form, stream, int(total_required), self.username)
            show_info(self, "Student added successfully")
            self.log_feedback(f"Student {admission_no} added successfully")
            logger.info(f"Student {admission_no} added by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()
        except ValueError as e:
            show_error(self, f"Invalid input: {str(e)}")
            self.log_feedback(f"Error adding student {admission_no}: {str(e)}")
            logger.error(f"Error adding student {admission_no} by {self.username}: {str(e)}")
        except Exception as e:
            show_error(self, f"Error adding student: {str(e)}")
            self.log_feedback(f"Error adding student {admission_no}: {str(e)}")
            logger.error(f"Error adding student {admission_no} by {self.username}: {str(e)}")

class UpdateStudentForm(ctk.CTkToplevel):
    def __init__(self, parent, student_mgr, username, icons, selected_student=None, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Update Student")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.selected_student = selected_student
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing UpdateStudentForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Admission No", "admission_no", ctk.CTkEntry, {}),
            ("Name", "name", ctk.CTkEntry, {}),
            ("Form", "form", ctk.CTkComboBox, {"values": ["Form 1", "Form 2", "Form 3", "Form 4", "Grade 10", "Grade 11", "Grade 12"]}),
            ("Stream", "stream", ctk.CTkEntry, {}),
            ("Total Required", "total_required", ctk.CTkEntry, {"state": "disabled"})
        ]

        for label, key, widget_type, kwargs in fields:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.entries[key] = widget_type(frame, font=("Arial", 12), height=35, **kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=5)
            frame.pack(fill="x", pady=5)
            logger.debug(f"Added field: {label}")

        # Populate fields if a student is selected
        if selected_student:
            self.entries['admission_no'].insert(0, selected_student[0])
            self.entries['admission_no'].configure(state="disabled")
            self.entries['name'].insert(0, selected_student[1] or "")
            self.entries['form'].set(selected_student[2] or "Form 1")
            self.entries['stream'].insert(0, selected_student[3] or "")
            self.entries['total_required'].configure(state="normal")
            self.entries['total_required'].insert(0, selected_student[4] or "")
            self.entries['total_required'].configure(state="disabled")

        # Update total_required when form changes
        self.entries['form'].bind("<<ComboboxSelected>>", self.update_total_required)

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
        logger.debug("UpdateStudentForm initialized")

    def update_total_required(self, event):
        """Update total_required based on selected form."""
        try:
            form = self.entries['form'].get()
            ream_required = self.student_mgr.get_ream_required_per_form()
            total_required = ream_required.get(form, 8)
            self.entries['total_required'].configure(state="normal")
            self.entries['total_required'].delete(0, "end")
            self.entries['total_required'].insert(0, str(total_required))
            self.entries['total_required'].configure(state="disabled")
        except Exception as e:
            logger.error(f"Error updating total_required: {str(e)}")
            show_error(self, f"Error updating total required: {str(e)}")

    def submit(self):
        """Submit the update student form."""
        try:
            admission_no = self.entries['admission_no'].get().strip()
            name = self.entries['name'].get().strip() or None
            form = self.entries['form'].get().strip() or None
            stream = self.entries['stream'].get().strip() or None
            total_required = self.entries['total_required'].get().strip()

            if not admission_no:
                show_error(self, "Admission No is required")
                self.log_feedback("Update student failed: Admission No required")
                return
            if not any([name, form, stream, total_required]):
                show_error(self, "At least one field must be provided to update")
                self.log_feedback("Update student failed: No fields provided")
                return
            total_required_reams = int(total_required) if total_required else None

            self.student_mgr.update_student_info(admission_no, name, form, stream, total_required_reams, self.username)
            show_info(self, "Student updated successfully")
            self.log_feedback(f"Student {admission_no} updated successfully")
            logger.info(f"Student {admission_no} updated by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()
        except ValueError as e:
            show_error(self, f"Invalid input: {str(e)}")
            self.log_feedback(f"Error updating student {admission_no}: {str(e)}")
            logger.error(f"Error updating student {admission_no} by {self.username}: {str(e)}")
        except Exception as e:
            show_error(self, f"Error updating student: {str(e)}")
            self.log_feedback(f"Error updating student {admission_no}: {str(e)}")
            logger.error(f"Error updating student {admission_no} by {self.username}: {str(e)}")

# ==============================================================
#                    BULK DELETE FORM 
# ==============================================================
class BulkDeleteForm(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        student_mgr: StudentManager,
        username: str,
        icons: Dict,
        callback=None,
        log_feedback=None,
    ):
        super().__init__(parent)
        self.title("Bulk Delete Students")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")

        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)

        logger.info(f"Initializing BulkDeleteForm for user {username}")

        # ---------- UI ----------
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        ctk.CTkLabel(
            form_frame,
            text="Example: 4400, 4401, ABC123 (max 12 chars, no spaces)",
            text_color="#FFFFFF",
        ).pack(pady=5, anchor="w", padx=10)

        self.admission_entry = ctk.CTkEntry(
            form_frame, font=("Arial", 12), height=35
        )
        self.admission_entry.pack(fill="x", padx=10, pady=5)

        # ---- progress area (hidden until we start) ----
        self.progress_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=10, pady=5)
        self.progress_label = ctk.CTkLabel(
            self.progress_frame, text="", text_color="#FFFFFF"
        )
        self.progress_label.pack(pady=2)

        # ---- buttons ----
        btn_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        btn_frame.pack(pady=10)

        self.submit_btn = ctk.CTkButton(
            btn_frame,
            text="Submit",
            image=self.icons.get("save"),
            compound="left",
            command=self._start_bulk_delete,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.submit_btn.pack(side="left", padx=5)

        self.cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            image=self.icons.get("cancel"),
            compound="left",
            command=self._cancel_and_close,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.cancel_btn.pack(side="left", padx=5)

        # ---- keyboard shortcuts ----
        self.bind("<Return>", lambda e: self._start_bulk_delete())
        self.bind("<Escape>", lambda e: self._cancel_and_close())

        # ---- internal state ----
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        logger.debug("BulkDeleteForm UI ready")

    # ------------------------------------------------------------------
    # UI entry points (called from buttons / shortcuts)
    # ------------------------------------------------------------------
    def _start_bulk_delete(self):
        """Validate input, ask confirmation, then launch background thread."""
        raw = self.admission_entry.get().strip()
        if not raw:
            show_error(self, "Enter at least one admission number")
            self.log_feedback("Bulk delete failed: No admission numbers")
            return

        admission_numbers = [
            a.strip() for a in raw.split(",") if a.strip()
        ]

        if not messagebox.askyesno(
            "Confirm Bulk Delete",
            f"Delete {len(admission_numbers)} student(s)?",
            parent=self,
        ):
            self.log_feedback("Bulk delete cancelled")
            logger.info(f"Bulk delete cancelled by {self.username}")
            return

        # ---- UI → processing mode ----
        self.submit_btn.configure(state="disabled", text="Processing…")
        self.cancel_btn.configure(text="Cancel")
        self.progress_frame.pack(fill="x", padx=10, pady=5)
        self.progress_bar.set(0)
        self.progress_label.configure(text="Preparing…")
        self.update_idletasks()

        # ---- start background worker ----
        self._cancel_event.clear()
        self._worker_thread = threading.Thread(
            target=self._background_worker,
            args=(admission_numbers,),
            daemon=True,
        )
        self._worker_thread.start()

    def _cancel_and_close(self):
        """User pressed Cancel – stop worker (if any) and close window."""
        self._cancel_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self.after(100, self._cancel_and_close)  
            return
        self.destroy()

    # ------------------------------------------------------------------
    # Background worker – **never touches Tkinter directly**
    # ------------------------------------------------------------------
    def _background_worker(self, admission_numbers: List[str]):
        total = len(admission_numbers)
        existing_students: List[Dict] = []
        errors: List[str] = []

        try:
            for idx, raw_adm in enumerate(admission_numbers):
                if self._cancel_event.is_set():
                    self.after(0, lambda: self._show_final("Cancelled by user", existing_students))
                    return

                adm = raw_adm.strip()
                if not adm:
                    errors.append(f"{raw_adm}: Empty")
                    continue
                if len(adm) > 12 or not adm.isalnum():
                    errors.append(f"{adm}: Invalid (1-12 alphanum only)")
                    continue

                try:
                    student = self.student_mgr.get_student_by_admission(adm, self.username)
                    if student:
                        existing_students.append(student)
                except Exception as e:
                    errors.append(f"{adm}: {str(e)}")
                    continue

                progress = (idx + 1) / total
                self.after(0, lambda p=progress, i=idx+1: self._update_progress(p, i, total))

            if self._cancel_event.is_set():
                return

            result = self.student_mgr.bulk_delete_students(admission_numbers, self.username)
            success = result.get("success_count", 0)
            errors = result.get("errors", []) + errors

            msg = f"Deleted {success} student(s)"
            if errors:
                msg += "\nErrors:\n" + "\n".join(errors)

            self.after(0, lambda: self._show_final(msg, existing_students))

        except Exception as exc:
            logger.exception("Unexpected error in bulk delete worker")
            self.after(
                0,
                lambda e=exc: self._show_final(f"Error: {e}", existing_students),
            )

    # ------------------------------------------------------------------
    # UI helpers – always called via `self.after` (main thread)
    # ------------------------------------------------------------------
    def _update_progress(self, fraction: float, current: int, total: int):
        self.progress_bar.set(fraction)
        self.progress_label.configure(
            text=f"Processing {current}/{total}…"
        )

    def _show_final(self, message: str, existing_students: List[Dict]):
        """Finish UI, invoke callback, close window."""
        self.submit_btn.configure(state="normal", text="Submit")
        self.progress_frame.pack_forget()

        show_info(self, message)
        self.log_feedback(message)
        logger.info(f"{message} (bulk delete) by {self.username}")

        if self.callback:
            self.callback(existing_students)

        self.destroy()

class PromoteStudentForm(ctk.CTkToplevel):
    def __init__(self, parent, student_mgr, username, icons, selected_student=None, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Promote Student")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.selected_student = selected_student
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing PromoteStudentForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries = {}
        fields = [
            ("Admission No", "admission_no", ctk.CTkEntry, {}),
            ("Current Form", "form", ctk.CTkEntry, {"state": "disabled"}),
            ("Current Stream", "stream", ctk.CTkEntry, {"state": "disabled"}),
            ("Next Form", "next_form", ctk.CTkEntry, {"state": "disabled"}),
            ("Next Total Required", "next_total_required", ctk.CTkEntry, {"state": "disabled"})
        ]
        for label, key, widget_type, kwargs in fields:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=120, anchor="w", text_color="#FFFFFF").pack(side="left", padx=(10, 5))
            
            # Base style
            base_kwargs = {
                "font": ("Arial", 12),
                "height": 35,
                "corner_radius": 8,
                "fg_color": "#3B3B3B",
                "border_width": 1,
                "border_color": "#555555",
                "text_color": "#FFFFFF"
            }

            # Disabled style
            if kwargs.get("state") == "disabled":
                base_kwargs["fg_color"] = "#2F2F2F"

            final_kwargs = {**base_kwargs, **kwargs}
            
            self.entries[key] = ctk.CTkEntry(frame, **final_kwargs)
            self.entries[key].pack(side="left", fill="x", expand=True, padx=5, pady=2)
            frame.pack(fill="x", pady=4, padx=10)
            logger.debug(f"Added field: {label}")

        if selected_student:
            self.entries['admission_no'].insert(0, selected_student[0])
            self.entries['admission_no'].configure(state="disabled")

            self.entries['form'].insert(0, selected_student[2] or "N/A")
            self.entries['form'].configure(state="disabled")

            self.entries['stream'].insert(0, selected_student[3] or "N/A")
            self.entries['stream'].configure(state="disabled")

            next_form = self.student_mgr.get_next_form(selected_student[2])
            self.entries['next_form'].insert(0, next_form or "Cannot Promote")
            self.entries['next_form'].configure(state="disabled")

            ream_required = self.student_mgr.get_ream_required_per_form()
            next_total = ream_required.get(next_form, "N/A") if next_form else "N/A"
            self.entries['next_total_required'].insert(0, str(next_total))
            self.entries['next_total_required'].configure(state="disabled")
            
        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        ctk.CTkButton(
            button_frame,
            text="Promote",
            image=self.icons.get('promote', self.icons['save']),
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
        logger.debug("PromoteStudentForm initialized")

    def submit(self):
        """Submit the promote student form."""
        try:
            admission_no = self.entries['admission_no'].get().strip()
            if not admission_no:
                show_error(self, "Admission No is required")
                self.log_feedback("Promote student failed: Admission No required")
                return

            next_form_text = self.entries['next_form'].get() 
            if next_form_text == "Cannot Promote":
                show_error(self, "Student cannot be promoted further")
                self.log_feedback(f"Promote student {admission_no} failed: Cannot promote further")
                return

            if not messagebox.askyesno(
                "Confirm Promotion", 
                f"Promote student {admission_no} to {next_form_text}?", 
                parent=self
            ):
                self.log_feedback(f"Promote student {admission_no} cancelled")
                logger.info(f"Promote student {admission_no} cancelled by {self.username}")
                return

            self.student_mgr.promote_student(admission_no, self.username)
            show_info(self, f"Student {admission_no} promoted successfully")
            self.log_feedback(f"Student {admission_no} promoted successfully")
            logger.info(f"Student {admission_no} promoted by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()

        except ValueError as e:
            show_error(self, f"Invalid input: {str(e)}")
            self.log_feedback(f"Error promoting student {admission_no}: {str(e)}")
            logger.error(f"Error promoting student {admission_no} by {self.username}: {str(e)}")
        except Exception as e:
            show_error(self, f"Error promoting student: {str(e)}")
            self.log_feedback(f"Error promoting student {admission_no}: {str(e)}")
            logger.error(f"Error promoting student {admission_no} by {self.username}: {str(e)}")

class BulkPromoteForm(ctk.CTkToplevel):
    def __init__(self, parent, student_mgr, username, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Bulk Promote Students")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing BulkPromoteForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        # Option to select by admission numbers or form
        self.promote_option = ctk.CTkOptionMenu(
            form_frame,
            values=["By Admission Numbers", "By Form"],
            font=("Arial", 12),
            dropdown_font=("Arial", 12),
            fg_color="#2B6CB0",
            button_color="#1E4E79",
            button_hover_color="#1E4E79",
            text_color="#FFFFFF"
        )
        self.promote_option.pack(pady=5)

        # Admission numbers input
        self.admission_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
        ctk.CTkLabel(self.admission_frame, text="Admission Numbers (comma-separated):", text_color="#FFFFFF").pack(pady=5)
        self.admission_entry = ctk.CTkEntry(self.admission_frame, font=("Arial", 12), height=35)
        self.admission_entry.pack(fill="x", padx=5)
        self.admission_frame.pack(fill="x", pady=5)

        # Form selection
        self.form_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
        ctk.CTkLabel(self.form_frame, text="Select Form:", text_color="#FFFFFF").pack(pady=5)
        self.form_entry = ctk.CTkComboBox(
            self.form_frame,
            values=["Form 1", "Form 2", "Form 3", "Grade 10", "Grade 11"], # Excludes Form 4, Grade 12 
            font=("Arial", 12),
            dropdown_font=("Arial", 12),
            fg_color="#2B6CB0",
            button_color="#1E4E79",
            button_hover_color="#1E4E79",
            text_color="#FFFFFF"
        )
        self.form_entry.pack(fill="x", padx=5)
        self.form_frame.pack(fill="x", pady=5)
        self.form_frame.pack_forget()  

        # Next form and total required display
        self.next_form_frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
        ctk.CTkLabel(self.next_form_frame, text="Next Form:", text_color="#FFFFFF").pack(side="left", padx=5)
        self.next_form_label = ctk.CTkLabel(self.next_form_frame, text="N/A", text_color="#FFFFFF", font=("Arial", 12))
        self.next_form_label.pack(side="left", padx=5)
        ctk.CTkLabel(self.next_form_frame, text="Next Total Required:", text_color="#FFFFFF").pack(side="left", padx=5)
        self.next_total_required_label = ctk.CTkLabel(self.next_form_frame, text="N/A", text_color="#FFFFFF", font=("Arial", 12))
        self.next_total_required_label.pack(side="left", padx=5)
        self.next_form_frame.pack(fill="x", pady=5)
        self.next_form_frame.pack_forget()  

        # Toggle visibility based on promote_option
        self.promote_option.bind("<<ComboboxSelected>>", self.toggle_input_fields)
        self.form_entry.bind("<<ComboboxSelected>>", self.update_next_form_info)

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        ctk.CTkButton(
            button_frame,
            text="Promote",
            image=self.icons.get('promote', self.icons['save']),
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

        # Progress bar
        self.progress_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=10)
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=5)
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", text_color="#FFFFFF")
        self.progress_label.pack()
        self.progress_frame.pack(pady=5, padx=10, fill="x")

        # Bind Enter to submit and Escape to cancel
        self.bind("<Return>", lambda event: self.submit())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug("BulkPromoteForm initialized")

    def toggle_input_fields(self, event=None):
        """Toggle visibility of admission numbers or form input based on selection."""
        option = self.promote_option.get()
        if option == "By Admission Numbers":
            self.admission_frame.pack(fill="x", pady=5)
            self.form_frame.pack_forget()
            self.next_form_frame.pack_forget()
        else:
            self.form_frame.pack(fill="x", pady=5)
            self.admission_frame.pack_forget()
            self.next_form_frame.pack(fill="x", pady=5)
            self.update_next_form_info(None)
        logger.debug(f"Toggled input fields to {option}")

    def update_next_form_info(self, event=None):
        """Update next form and total required based on selected form."""
        try:
            form = self.form_entry.get()
            next_form = self.student_mgr.get_next_form(form)
            self.next_form_label.configure(text=next_form or "Cannot Promote")
            ream_required = self.student_mgr.get_ream_required_per_form()
            next_total_required = ream_required.get(next_form, "N/A") if next_form else "N/A"
            self.next_total_required_label.configure(text=str(next_total_required))
        except Exception as e:
            logger.error(f"Error updating next form info: {str(e)}")
            show_error(self, f"Error updating next form info: {str(e)}")

    def submit(self):
        """Submit the bulk promote form."""
        try:
            option = self.promote_option.get()
            if option == "By Admission Numbers":
                admission_numbers = self.admission_entry.get().strip().split(',')
                admission_numbers = [an.strip() for an in admission_numbers if an.strip()]
                if not admission_numbers:
                    show_error(self, "Enter at least one admission number")
                    self.log_feedback("Bulk promote failed: No admission numbers provided")
                    return
                if not messagebox.askyesno("Confirm Bulk Promote", f"Promote {len(admission_numbers)} students?", parent=self):
                    self.log_feedback("Bulk promote cancelled")
                    logger.info(f"Bulk promote cancelled by {self.username}")
                    return
                self.progress_bar.set(0)
                self.progress_label.configure(text="Promoting students...")
                self.update()

                result = self.student_mgr.promote_students(admission_numbers=admission_numbers, user=self.username)
                total = result['success_count'] + len(result['errors'])
                self.progress_bar.set(1.0)
                self.update()
                time.sleep(0.1)  # Brief pause for visual feedback
            else:
                form = self.form_entry.get().strip()
                if not form:
                    show_error(self, "Select a form")
                    self.log_feedback("Bulk promote failed: No form selected")
                    return
                if self.next_form_label.cget("text") == "Cannot Promote":
                    show_error(self, f"Students in {form} cannot be promoted further")
                    self.log_feedback(f"Bulk promote failed: Students in {form} cannot be promoted further")
                    return
                if not messagebox.askyesno("Confirm Bulk Promote", f"Promote all students in {form} to {self.next_form_label.cget('text')}?", parent=self):
                    self.log_feedback(f"Bulk promote for {form} cancelled")
                    logger.info(f"Bulk promote for {form} cancelled by {self.username}")
                    return
                self.progress_bar.set(0)
                self.progress_label.configure(text=f"Promoting students in {form}...")
                self.update()

                result = self.student_mgr.promote_students(form=form, user=self.username)
                total = result['success_count'] + len(result['errors'])
                self.progress_bar.set(1.0)
                self.update()
                time.sleep(0.1)  # Brief pause for visual feedback

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            message = f"Promoted {result['success_count']} students"
            if result['errors']:
                message += f"\nErrors:\n" + "\n".join(result['errors'])
            show_info(self, message)
            self.log_feedback(message)
            logger.info(f"{message} by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self, f"Error in bulk promote: {str(e)}")
            self.log_feedback(f"Error in bulk promote: {str(e)}")
            logger.error(f"Error in bulk promote by {self.username}: {str(e)}")

class SettingsForm(ctk.CTkToplevel):
    def __init__(self, parent, student_mgr, username, icons, callback=None, log_feedback=None):
        super().__init__(parent)
        self.title("Ream Requirements Settings")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.student_mgr = student_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info(f"Initializing SettingsForm for user {username}")

        # Form frame
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        ctk.CTkLabel(form_frame, text="Ream Requirements per Form", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=5)

        self.entries = {}
        forms = ["Form 1", "Form 2", "Form 3", "Form 4", "Grade 10", "Grade 11", "Grade 12"]
        ream_required = self.student_mgr.get_ream_required_per_form()

        for form in forms:
            frame = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=f"{form}:", width=100, text_color="#FFFFFF").pack(side="left")
            self.entries[form] = ctk.CTkEntry(frame, font=("Arial", 12), height=35)
            self.entries[form].insert(0, str(ream_required.get(form, 8)))
            self.entries[form].pack(side="left", fill="x", expand=True, padx=5)
            frame.pack(fill="x", pady=5)
            logger.debug(f"Added field: {form}")

        # Buttons
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        ctk.CTkButton(
            button_frame,
            text="Save",
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
        logger.debug("SettingsForm initialized")

    def submit(self):
        """Submit the settings form."""
        try:
            ream_required = {}
            for form in self.entries:
                value = self.entries[form].get().strip()
                if not value.isdigit() or int(value) < 0:
                    show_error(self, f"Ream requirement for {form} must be a non-negative integer")
                    self.log_feedback(f"Settings update failed: Invalid ream requirement for {form}")
                    return
                ream_required[form] = int(value)

            self.student_mgr.update_ream_required_per_form(ream_required, self.username)
            show_info(self, "Ream requirements updated successfully")
            self.log_feedback("Ream requirements updated successfully")
            logger.info(f"Ream requirements updated by {self.username}")
            if self.callback:
                self.callback()
            self.destroy()
        except ValueError as e:
            show_error(self, f"Invalid input: {str(e)}")
            self.log_feedback(f"Error updating ream requirements: {str(e)}")
            logger.error(f"Error updating ream requirements by {self.username}: {str(e)}")
        except Exception as e:
            show_error(self, f"Error updating ream requirements: {str(e)}")
            self.log_feedback(f"Error updating ream requirements: {str(e)}")
            logger.error(f"Error updating ream requirements by {self.username}: {str(e)}")

class StudentsTab:
    def __init__(self, parent, db_name: str, username: Optional[str], role: Optional[str], main_window, icons):
        self.parent = parent
        self.db_name = db_name
        self.username = username
        self.role = role
        self.main_window = main_window
        self.icons = icons
        self.student_mgr = StudentManager(db_name)
        self.deleted_students: List[Dict] = []
        self.sort_column_name = None
        self.sort_reverse = False
        self.tree = None
        self.entries = {}
        self.setup_gui()
        logger.info(f"Initialized StudentsTab with username={username}, role={role}")
        self.main_window.log_feedback("StudentsTab initialized; data will load after login")

    def setup_gui(self):
        """Set up the StudentsTab GUI."""
        self.main_frame = ctk.CTkFrame(self.parent, fg_color="#2B2B2B", corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.role and self.role not in {'admin', 'staff', 'viewer'}:
            ctk.CTkLabel(self.main_frame, text="Permission Denied: Admin, Staff, or Viewer role required",
                         font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=20)
            self.main_window.log_feedback("Access denied: Admin, Staff, or Viewer role required")
            return

        # Search bar
        logger.debug("Creating search_frame in StudentsTab")
        self.search_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.search_frame, text="Search Students:", width=100, text_color="#FFFFFF").pack(side="left")
        self.search_field = ctk.CTkComboBox(self.search_frame, values=["All", "Adm No", "Name", "Form", "Stream"], font=("Arial", 12), height=35)
        self.search_field.pack(side="left", padx=5)
        self.search_entry = ctk.CTkEntry(self.search_frame, font=("Arial", 12), height=35)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(
            self.search_frame,
            text="Search",
            image=self.icons['search'] if 'search' in self.icons else None,
            compound="left",
            command=self.search_students,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        self.search_frame.pack(pady=5, padx=10, fill="x")

        # Action frame
        logger.debug("Creating action_frame in StudentsTab")
        self.action_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                self.action_frame,
                text="Import from Excel",
                image=self.icons['import'] if 'import' in self.icons else None,
                compound="left",
                command=self.import_students,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.action_frame,
                text="Export to CSV",
                image=self.icons['export'] if 'export' in self.icons else None,
                compound="left",
                command=self.export_students,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.action_frame,
                text="Update All Statuses",
                image=self.icons['update'] if 'update' in self.icons else None,
                compound="left",
                command=self.update_all_statuses,
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
                    text="Settings",
                    image=self.icons.get('settings', self.icons['edit']),
                    compound="left",
                    command=self.open_settings_form,
                    fg_color="#2B6CB0",
                    hover_color="#1E4E79",
                    text_color="#FFFFFF",
                    font=("Arial", 12, "bold"),
                    height=40,
                    corner_radius=10
                ).pack(side="left", padx=5)
        self.action_frame.pack(pady=5, padx=10, fill="x")

        # Progress bar
        logger.debug("Creating progress_frame in StudentsTab")
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=5)
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", text_color="#FFFFFF")
        self.progress_label.pack()
        self.progress_frame.pack(pady=5, padx=10, fill="x")

        # Student form (for selection only)
        logger.debug("Creating form_frame in StudentsTab")
        self.form_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.form_frame, text="Manage Student", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=5)
        fields = [("Admission No", "admission_no"), ("Name", "name"), ("Form", "form"),
                  ("Stream", "stream"), ("Total Required", "total_required")]
        for label, key in fields:
            frame = ctk.CTkFrame(self.form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            self.entries[key] = ctk.CTkEntry(frame, font=("Arial", 12), height=35)
            if key == "total_required":
                self.entries[key].insert(0, "4")
            self.entries[key].pack(side="left", fill="x", expand=True)
            frame.pack(fill="x", pady=2)
            logger.debug(f"Added field: {label}")
        self.form_frame.pack(pady=10, padx=10, fill="x")

        # Buttons
        logger.debug("Creating button_frame in StudentsTab")
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        if self.role in {'admin', 'staff'}:
            ctk.CTkButton(
                self.button_frame,
                text="Add Student",
                image=self.icons['add'],
                compound="left",
                command=self.open_add_student_form,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Update Student",
                image=self.icons['edit'],
                compound="left",
                command=self.open_update_student_form,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Delete Student",
                image=self.icons['delete'],
                compound="left",
                command=self.delete_student,
                fg_color="#C53030",
                hover_color="#9B2A2A",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Bulk Delete",
                image=self.icons['delete'],
                compound="left",
                command=self.open_bulk_delete_form,
                fg_color="#C53030",
                hover_color="#9B2A2A",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Update Status",
                image=self.icons['update'] if 'update' in self.icons else None,
                compound="left",
                command=self.update_student_status,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Promote Student",
                image=self.icons.get('promote', self.icons['edit']),
                compound="left",
                command=self.open_promote_student_form,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
            ctk.CTkButton(
                self.button_frame,
                text="Bulk Promote",
                image=self.icons.get('promote', self.icons['edit']),
                compound="left",
                command=self.open_bulk_promote_form,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 12, "bold"),
                height=40,
                corner_radius=10
            ).pack(side="left", padx=5)
        self.button_frame.pack(pady=10, padx=10, fill="x")

        # Students table
        logger.debug("Creating table_frame in StudentsTab")
        self.table_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        columns = ("Adm No", "Name", "Form", "Stream", "Required", "Brought", "Remaining", "Status", "Excess")
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c))
            self.tree.column(col, width=100)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ctk.CTkScrollbar(self.table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_student)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_data()
        self.main_frame.update_idletasks()
        logger.info("StudentsTab GUI initialized")


    def open_add_student_form(self):
        """Open the add student form."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open add student form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Add Student",
            form_class=AddStudentForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_update_student_form(self):
        """Open the update student form with selected student data."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open update student form failed: Permission denied")
            return
        selected = self.tree.selection()
        selected_student = None
        if selected:
            selected_student = self.tree.item(selected[0])['values']
        self.main_window.open_form_window(
            title="Update Student",
            form_class=UpdateStudentForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            selected_student=selected_student,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_bulk_delete_form(self):
        """Open the bulk delete students form."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open bulk delete form failed: Permission denied")
            return
        def callback(existing_students):
            self.deleted_students.extend(existing_students)
            self.refresh_data()
        self.main_window.open_form_window(
            title="Bulk Delete Students",
            form_class=BulkDeleteForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            callback=callback,
            log_feedback=self.main_window.log_feedback
        )

    def open_promote_student_form(self):
        """Open the promote student form with selected student data."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open promote student form failed: Permission denied")
            return
        selected = self.tree.selection()
        selected_student = None
        if selected:
            selected_student = self.tree.item(selected[0])['values']
        self.main_window.open_form_window(
            title="Promote Student",
            form_class=PromoteStudentForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            selected_student=selected_student,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_bulk_promote_form(self):
        """Open the bulk promote students form."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Open bulk promote form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Bulk Promote Students",
            form_class=BulkPromoteForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_settings_form(self):
        """Open the settings form for ream requirements."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Open settings form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Ream Requirements Settings",
            form_class=SettingsForm,
            student_mgr=self.student_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def refresh_data(self):
        """Load or refresh student data after login."""
        if not self.username or not self.role:
            self.main_window.log_feedback("Cannot load students: No user logged in")
            return
        if self.role not in {'admin', 'staff', 'viewer'}:
            self.main_window.log_feedback("Cannot load students: Admin, Staff, or Viewer role required")
            return

        try:
            students = self.student_mgr.fetch_all_students(self.username, self.role)
            self.tree.delete(*self.tree.get_children())

            for s in students:
                remaining = s['remaining_to_bring']
                excess = max(0, -remaining)
                status = s['status']

                # Color tag
                tag = ""
                if status == "Ahead":
                    tag = "ahead"
                elif status == "Behind":
                    tag = "behind"
                elif status == "On Track":
                    tag = "ontrack"

                self.tree.insert("", "end", values=(
                    s['admission_no'], s['name'], s['form'], s['stream'] or '',
                    s['total_required'], s['total_brought'], remaining, status, excess
                ), tags=(tag,))

            # Apply colors
            self.tree.tag_configure("ahead", background="#E6F7E6", foreground="#2D862D")
            self.tree.tag_configure("behind", background="#FDEBEB", foreground="#A61C1C")
            self.tree.tag_configure("ontrack", background="#FFF8E1", foreground="#F57C00")

            self.main_window.log_feedback(f"Loaded {len(students)} student records")
            logger.info(f"Loaded {len(students)} records for {self.username}")
        except Exception as e:
            self.main_window.log_feedback(f"Error loading students: {e}")
            logger.error(f"Load error: {e}")
            show_error(self.main_window, f"Error loading students: {e}")


    def on_select_student(self, event):
        """Populate form with selected student's data."""
        selected = self.tree.selection()
        if not selected:
            return
        item = self.tree.item(selected[0])['values']
        keys = ['admission_no', 'name', 'form', 'stream', 'total_required',
                'total_brought', 'remaining_to_bring', 'status', 'excess']
        for i, key in enumerate(keys):
            if key not in self.entries:
                continue
            widget = self.entries[key]
            widget.delete(0, "end")
            value = str(item[i]) if i < len(item) else ""
            if key == "excess":
                value = str(max(0, -int(item[6]))) if len(item) > 6 and item[6] else "0"
            widget.insert(0, value)
            if key in {"remaining_to_bring", "status", "excess"}:
                color = "#2D862D" if key == "excess" and int(value) > 0 else "#FFFFFF"
                widget.configure(text_color=color)
        self.main_window.log_feedback(f"Selected: {item[0]}")
        logger.info(f"Selected student: {item[0]}")

    def sort_column(self, col: str):
        """Sort the table by the specified column."""
        try:
            data = [(self.tree.set(item, col), item) for item in self.tree.get_children()]
            if self.sort_column_name == col:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_reverse = False
                self.sort_column_name = col

            def convert(value):
                try:
                    if col in ["Required", "Brought", "Remaining", "Excess"]:
                        return int(value)
                    return value.lower()
                except:
                    return value

            data.sort(key=lambda x: convert(x[0]), reverse=self.sort_reverse)

            for idx, (val, item) in enumerate(data):
                self.tree.move(item, "", idx)

            # Update headers
            for c in self.tree["columns"]:
                self.tree.heading(c, text=c)
            arrow = " descending" if self.sort_reverse else " ascending"
            self.tree.heading(col, text=col + arrow)

            self.main_window.log_feedback(f"Sorted by {col} {arrow}")
            logger.info(f"Sorted by {col} {arrow} by {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Sort error: {e}")

    def delete_student(self):
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied")
            return

        try:
            # Try form first
            admission_no = self.entries['admission_no'].get().strip()
            if not admission_no:
                # Fallback: selected row
                selected = self.tree.selection()
                if not selected:
                    show_error(self.main_window, "Select a student or enter Admission No")
                    return
                admission_no = str(self.tree.item(selected[0])['values'][0])

            if not messagebox.askyesno("Confirm", f"Delete student {admission_no}?", parent=self.main_window):
                return

            student = self.student_mgr.get_student_by_admission(admission_no, self.username)
            if not student:
                show_error(self.main_window, f"Student {admission_no} not found")
                return

            self.student_mgr.delete_student(admission_no, self.username)
            self.deleted_students.append(student)
            show_info(self.main_window, "Student deleted")
            self.main_window.log_feedback(f"Deleted: {admission_no}")
            logger.info(f"Deleted student {admission_no}")

            self.refresh_data()
            self.clear_form()

        except Exception as e:
            fallback = admission_no if 'admission_no' in locals() else "unknown"
            show_error(self.main_window, f"Error: {str(e)}")
            logger.error(f"Delete error: {e}")



    def undo_delete(self):
        """Undo the last deletion(s)."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Undo delete failed: Permission denied")
            return
        if not self.deleted_students:
            show_error(self.main_window, "No deletions to undo")
            self.main_window.log_feedback("Undo delete failed: No deletions to undo")
            return
        try:
            self.progress_bar.set(0)
            self.progress_label.configure(text="Undoing deletion...")
            self.main_frame.update()

            total = len(self.deleted_students)
            for i, student in enumerate(self.deleted_students):
                self.student_mgr.add_student(
                    student['admission_no'], student['name'], student['form'],
                    student['stream'], student['total_required'], self.username
                )
                self.student_mgr.update_ream_status(student['student_id'], self.username)
                self.progress_bar.set((i + 1) / total)
                self.main_frame.update()
                time.sleep(0.05)  

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            self.deleted_students.clear()
            show_info(self.main_window, f"Restored {total} students")
            self.main_window.log_feedback(f"Restored {total} students")
            logger.info(f"Restored {total} students by {self.username}")
            self.refresh_data()
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error undoing deletion: {str(e)}")
            self.main_window.log_feedback(f"Error undoing deletion: {str(e)}")
            logger.error(f"Error undoing deletion by {self.username}: {str(e)}")

    def update_student_status(self):
        """Update ream status for a single student."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Update status failed: Permission denied")
            return
        try:
            admission_no = self.entries['admission_no'].get().strip()
            if not admission_no:
                show_error(self.main_window, "Admission No is required")
                self.main_window.log_feedback("Update status failed: Admission No required")
                return
            
            student = self.student_mgr.get_student_by_admission(admission_no, self.username)
            if not student:
                show_error(self.main_window, f"Student {admission_no} not found")
                self.main_window.log_feedback(f"Update status failed: Student {admission_no} not found")
                return
            
            self.student_mgr.update_ream_status(student['student_id'], self.username)
            show_info(self.main_window, f"Ream status updated for {admission_no}")
            self.main_window.log_feedback(f"Ream status updated for {admission_no}")
            logger.info(f"Ream status updated for {admission_no} by {self.username}")
            self.refresh_data()
        except Exception as e:
            show_error(self.main_window, f"Error updating status: {str(e)}")
            self.main_window.log_feedback(f"Error updating status for {admission_no}: {str(e)}")
            logger.error(f"Error updating status for {admission_no} by {self.username}: {str(e)}")

    def update_all_statuses(self):
        """Update ream status for all students."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Update all statuses failed: Permission denied")
            return
        try:
            if not messagebox.askyesno("Confirm Update", "Update ream status for all students?", parent=self.main_window):
                self.main_window.log_feedback("Update all statuses cancelled")
                logger.info(f"Update all statuses cancelled by {self.username}")
                return
            self.progress_bar.set(0)
            self.progress_label.configure(text="Updating all statuses...")
            self.main_frame.update()

            students = self.student_mgr.fetch_all_students(self.username, self.role)
            total = len(students)
            self.student_mgr.update_all_students_status(self.username)
            self.progress_bar.set(1.0)
            self.main_frame.update()
            time.sleep(0.1)  # Brief pause for visual feedback

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_info(self.main_window, "All student statuses updated successfully")
            self.main_window.log_feedback("All student statuses updated successfully")
            logger.info(f"All student statuses updated by {self.username}")
            self.refresh_data()
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error updating all statuses: {str(e)}")
            self.main_window.log_feedback(f"Error updating all statuses: {str(e)}")
            logger.error(f"Error updating all statuses by {self.username}: {str(e)}")

    def import_students(self):
        """Import students from an Excel file in a background thread with timeout."""
        if self.role not in {'admin', 'staff'}:
            show_error(self.main_window, "Permission denied: Admin or Staff role required")
            self.main_window.log_feedback("Import students failed: Permission denied")
            return
        try:
            file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
            if not file_path:
                self.main_window.log_feedback("Import students cancelled: No file selected")
                logger.info(f"Import students cancelled by {self.username}: No file selected")
                return

            def progress_callback(message: str):
                """Update GUI progress bar and label (thread-safe)."""
                self.main_window.after(0, lambda: (
                    self.progress_label.configure(text=message),
                    self.progress_bar.set(min(self.progress_bar.get() + 0.1, 1.0))
                ))

            def run_import():
                cancel_event = Event()
                try:
                    # Start timeout
                    with cancellable_timeout(120, cancel_event) as cancel: 
                        self.main_window.after(0, lambda: (
                            self.progress_bar.set(0),
                            self.progress_label.configure(text="Importing students...")
                        ))

                        result = self.student_mgr.import_students_from_excel(
                            file_path, self.username,
                            progress_callback=progress_callback,
                            cancel_event=cancel
                        )

                        self.main_window.after(0, lambda: (
                            self.progress_bar.set(1.0),
                            self.progress_label.configure(text="")
                        ))

                        message = f"Imported {result['success_count']} students"
                        if result['errors']:
                            message += f"\nErrors:\n" + "\n".join(result['errors'][:10]) 
                            if len(result['errors']) > 10:
                                message += f"\n... and {len(result['errors']) - 10} more."

                        self.main_window.after(0, lambda: (
                            show_info(self.main_window, message),
                            self.main_window.log_feedback(message),
                            self.refresh_data()
                        ))
                        logger.info(f"{message} by {self.username}")

                except TimeoutError:
                    self.main_window.after(0, lambda: (
                        self.progress_bar.set(0),
                        self.progress_label.configure(text=""),
                        show_error(self.main_window, "Import timed out after 2 minutes. Try smaller batches."),
                        self.main_window.log_feedback("Import timed out after 2 minutes")
                    ))
                    logger.warning(f"Import timed out by {self.username}")
                except Exception as e:
                    self.main_window.after(0, lambda: (
                        self.progress_bar.set(0),
                        self.progress_label.configure(text=""),
                        show_error(self.main_window, f"Error importing: {str(e)}"),
                        self.main_window.log_feedback(f"Error importing: {str(e)}")
                    ))
                    logger.error(f"Import error by {self.username}: {str(e)}")

            # Start import in a background thread
            threading.Thread(target=run_import, daemon=True).start()
        except Exception as e:
            self.progress_bar.set(0)
            self.progress_label.configure(text="")
            show_error(self.main_window, f"Error initiating import: {str(e)}")
            self.main_window.log_feedback(f"Error initiating import: {str(e)}")
            logger.error(f"Error initiating import by {self.username}: {str(e)}")

    def export_students(self):
        """Export students to a CSV file."""
        try:
            file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
            if not file_path:
                self.main_window.log_feedback("Export students cancelled: No file selected")
                logger.info(f"Export students cancelled by {self.username}: No file selected")
                return
            self.progress_bar.set(0)
            self.progress_label.configure(text="Exporting students...")
            self.main_frame.update()

            self.student_mgr.export_students_to_csv(file_path, self.username)
            self.progress_bar.set(1.0)
            self.main_frame.update()
            time.sleep(0.1)  # Brief pause for visual feedback

            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_info(self.main_window, f"Students exported to {file_path}")
            self.main_window.log_feedback(f"Students exported to {file_path}")
            logger.info(f"Students exported to {file_path} by {self.username}")
        except Exception as e:
            self.progress_label.configure(text="")
            self.progress_bar.set(0)
            show_error(self.main_window, f"Error exporting students: {str(e)}")
            self.main_window.log_feedback(f"Error exporting students: {str(e)}")
            logger.error(f"Error exporting students by {self.username}: {str(e)}")

    def search_students(self):
        """Search students by keyword and field."""
        try:
            keyword = self.search_entry.get().strip()
            field = self.search_field.get()
            if not keyword or len(keyword) < 2:
                show_error(self.main_window, "Search keyword must be at least 2 characters")
                self.main_window.log_feedback("Search failed: Keyword too short")
                return

            self.tree.delete(*self.tree.get_children())
            students = self.student_mgr.search_students(keyword, self.username, field.lower() if field != "All" else None)
            for s in students:
                remaining = s['remaining_to_bring']
                excess = max(0, -remaining)
                status = s['status']
                tag = "ahead" if status == "Ahead" else "behind" if status == "Behind" else "ontrack"
                self.tree.insert("", "end", values=(
                    s['admission_no'], s['name'], s['form'], s['stream'] or '',
                    s['total_required'], s['total_brought'], remaining, status, excess
                ), tags=(tag,))
                
            self.main_window.log_feedback(f"Searched students by {field} with keyword '{keyword}', found {len(students)} results")
            logger.info(f"Searched students by {field} with keyword '{keyword}', found {len(students)} results by {self.username}")
        except Exception as e:
            show_error(self.main_window, f"Error searching students: {str(e)}")
            self.main_window.log_feedback(f"Error searching students: {str(e)}")
            logger.error(f"Error searching students by {self.username}: {str(e)}")

    def clear_form(self):
        """Clear the form fields."""
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            if key == "total_required":
                entry.delete(0, "end")
        self.main_window.log_feedback("Form cleared")
        logger.info(f"Form cleared by {self.username}")