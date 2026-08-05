
import customtkinter as ctk
from tkinter import ttk, messagebox
from modules.user_manager import UserManager
from gui.utils import show_error, show_info, validate_not_empty, validate_username, validate_password
from modules.db_setup import get_logs_dir
import logging
import os
from typing import Dict, Optional, Callable, Any
import threading

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'user_tab.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helper – run UI code on the main thread
# ----------------------------------------------------------------------
def _ui(callback: Callable[[], Any]) -> None:
    """Wrapper that guarantees `callback` runs on the Tk main thread."""
    def _inner(*args, **kwargs):
        try:
            callback(*args, **kwargs)
        except Exception as exc:
            logger.exception("Unexpected UI callback error")
            show_error(None, f"Unexpected error: {exc}")
    return _inner


# ----------------------------------------------------------------------
# CREATE USER FORM
# ----------------------------------------------------------------------
class CreateUserForm(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        user_mgr: UserManager,
        username: str,
        icons: dict,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self.title("Create User")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")

        self.user_mgr = user_mgr
        self.username = username
        self.icons = icons
        self.callback = callback
        self.log_feedback = log_feedback or (lambda _: None)

        logger.info(f"Initializing CreateUserForm for user {username}")

        # ------------------------------------------------------------------
        # Form layout
        # ------------------------------------------------------------------
        form_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.entries: Dict[str, ctk.CTkBaseClass] = {}
        fields = [
            ("Username", "username", ctk.CTkEntry, {}),
            ("Password", "password", ctk.CTkEntry, {"show": "*"}),
            ("Role", "role", ctk.CTkComboBox, {"values": list(user_mgr.valid_roles)}),
            ("Status", "status", ctk.CTkComboBox, {"values": list(user_mgr.valid_statuses)}),
            ("Remarks", "remarks", ctk.CTkEntry, {}),
        ]

        for label, key, widget_type, kwargs in fields:
            row = ctk.CTkFrame(form_frame, fg_color="#2B2B2B")
            ctk.CTkLabel(row, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            widget = widget_type(row, font=("Arial", 12), height=35, **kwargs)
            widget.pack(side="left", fill="x", expand=True, padx=5)
            self.entries[key] = widget
            row.pack(fill="x", pady=5)

        # ------------------------------------------------------------------
        # Buttons
        # ------------------------------------------------------------------
        btn_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        self.submit_btn = ctk.CTkButton(
            btn_frame,
            text="Submit",
            image=self.icons["save"],
            compound="left",
            command=self._trigger_submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.submit_btn.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            image=self.icons["cancel"],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        ).pack(side="left", padx=5)

        btn_frame.pack(pady=10)

        # ------------------------------------------------------------------
        # Keyboard shortcuts
        # ------------------------------------------------------------------
        self.bind("<Return>", lambda e: self._trigger_submit())
        self.bind("<Escape>", lambda e: self.destroy())

    # ----------------------------------------------------------------------
    def _trigger_submit(self) -> None:
        if self.submit_btn.cget("state") != "disabled":
            self.submit()

    # ----------------------------------------------------------------------
    def submit(self) -> None:
        """Run the create-user operation in a background thread."""
        def _work():
            try:
                username = self.entries["username"].get().strip()
                password = self.entries["password"].get().strip()
                role = self.entries["role"].get()
                status = self.entries["status"].get()
                remarks = self.entries["remarks"].get().strip() or None

                # ----- validation -------------------------------------------------
                if not validate_not_empty(username, "Username", self.log_feedback):
                    self.after(0, lambda: show_error(self, "Username is required"))
                    return
                if not validate_username(username, self.user_mgr.db_name, self.log_feedback):
                    self.after(0, lambda: show_error(self, "Invalid or duplicate username"))
                    return
                if not validate_not_empty(password, "Password", self.log_feedback):
                    self.after(0, lambda: show_error(self, "Password is required"))
                    return
                if not validate_password(password, self.log_feedback):
                    self.after(0, lambda: show_error(self, "Password must be 8+ characters with letters, numbers, and special characters"))
                    return
                if role not in self.user_mgr.valid_roles:
                    self.after(0, lambda: show_error(self, f"Role must be one of {self.user_mgr.valid_roles}"))
                    return
                if status not in self.user_mgr.valid_statuses:
                    self.after(0, lambda: show_error(self, f"Status must be one of {self.user_mgr.valid_statuses}"))
                    return

                # ----- DB call ----------------------------------------------------
                self.user_mgr.create_user(username, password, role, status, creator=self.username)

                # ----- success ----------------------------------------------------
                self.after(
                    0,
                    lambda: [
                        show_info(self, f"User {username} created successfully"),
                        self.log_feedback(f"User {username} created successfully"),
                        logger.info(f"User {username} created by {self.username}"),
                        (self.callback() if self.callback else None),
                        self.destroy(),
                    ],
                )
            except Exception as exc:
                msg = f"Error creating user: {exc}"
                self.after(
                    0,
                    lambda: [
                        show_error(self, msg),
                        self.log_feedback(f"Error creating user {username}: {exc}"),
                        logger.error(f"Error creating user {username} by {self.username}: {exc}"),
                    ],
                )
            finally:
                # ----- ALWAYS re-enable the button --------------------------------
                self.after(0, lambda: self.submit_btn.configure(state="normal", text="Submit"))

        self.submit_btn.configure(state="disabled", text="Creating...")
        threading.Thread(target=_work, daemon=True).start()


# ----------------------------------------------------------------------
# RESET PASSWORD FORM
# ----------------------------------------------------------------------
class ResetPasswordForm(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        user_mgr: UserManager,
        username: str,
        icons: dict,
        selected_user: Optional[tuple] = None,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self.title("Reset Password")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")

        self.user_mgr = user_mgr
        self.username = username
        self.icons = icons
        self.selected_user = selected_user
        self.callback = callback
        self.log_feedback = log_feedback or (lambda _: None)

        logger.info(f"Initializing ResetPasswordForm for user {username}")

        # ------------------------------------------------------------------
        # Layout
        # ------------------------------------------------------------------
        form = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form.pack(pady=10, padx=10, fill="both", expand=True)

        # Username
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Username:", text_color="#FFFFFF").pack(side="left")
        self.username_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        if selected_user:
            self.username_entry.insert(0, selected_user[1])
            self.username_entry.configure(state="disabled")
        self.username_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # New password
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="New Password:", text_color="#FFFFFF").pack(side="left")
        self.password_entry = ctk.CTkEntry(row, show="*", font=("Arial", 12), height=35)
        self.password_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Remarks
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Remarks:", text_color="#FFFFFF").pack(side="left")
        self.remarks_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        self.remarks_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        self.submit_btn = ctk.CTkButton(
            btn_frame,
            text="Submit",
            image=self.icons["save"],
            compound="left",
            command=self._trigger_submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.submit_btn.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            image=self.icons["cancel"],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        ).pack(side="left", padx=5)

        btn_frame.pack(pady=10)

        self.bind("<Return>", lambda e: self._trigger_submit())
        self.bind("<Escape>", lambda e: self.destroy())

    # ----------------------------------------------------------------------
    def _trigger_submit(self) -> None:
        if self.submit_btn.cget("state") != "disabled":
            self.submit()

    # ----------------------------------------------------------------------
    def submit(self) -> None:
        def _work():
            try:
                username = self.username_entry.get().strip()
                new_pw = self.password_entry.get().strip()
                remarks = self.remarks_entry.get().strip() or None

                if not validate_not_empty(username, "Username", self.log_feedback):
                    self.after(0, lambda: show_error(self, "Username is required"))
                    return
                if not validate_not_empty(new_pw, "Password", self.log_feedback):
                    self.after(0, lambda: show_error(self, "New password is required"))
                    return
                if not validate_password(new_pw, self.log_feedback):
                    self.after(0, lambda: show_error(self, "Password must be 8+ characters with letters, numbers, and special characters"))
                    return

                self.user_mgr.reset_password(username, new_pw, self.username, remarks)

                self.after(
                    0,
                    lambda: [
                        show_info(self, f"Password reset for {username}"),
                        self.log_feedback(f"Password reset for {username}"),
                        logger.info(f"Password reset for {username} by {self.username}"),
                        (self.callback() if self.callback else None),
                        self.destroy(),
                    ],
                )
            except Exception as exc:
                msg = f"Error resetting password: {exc}"
                self.after(
                    0,
                    lambda: [
                        show_error(self, msg),
                        self.log_feedback(f"Error resetting password for {username}: {exc}"),
                        logger.error(f"Error resetting password for {username} by {self.username}: {exc}"),
                    ],
                )
            finally:
                self.after(0, lambda: self.submit_btn.configure(state="normal", text="Submit"))

        self.submit_btn.configure(state="disabled", text="Resetting...")
        threading.Thread(target=_work, daemon=True).start()


# ----------------------------------------------------------------------
# UPDATE STATUS FORM
# ----------------------------------------------------------------------
class UpdateStatusForm(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        user_mgr: UserManager,
        username: str,
        icons: dict,
        selected_user: Optional[tuple] = None,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self.title("Update User Status")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")

        self.user_mgr = user_mgr
        self.username = username
        self.icons = icons
        self.selected_user = selected_user
        self.callback = callback
        self.log_feedback = log_feedback or (lambda _: None)

        logger.info(f"Initializing UpdateStatusForm for user {username}")

        # ------------------------------------------------------------------
        # Layout
        # ------------------------------------------------------------------
        form = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form.pack(pady=10, padx=10, fill="both", expand=True)

        # Username
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Username:", text_color="#FFFFFF").pack(side="left")
        self.username_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        if selected_user:
            self.username_entry.insert(0, selected_user[1])
            self.username_entry.configure(state="disabled")
        self.username_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Status
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Status:", text_color="#FFFFFF").pack(side="left")
        self.status_entry = ctk.CTkComboBox(
            row, values=list(self.user_mgr.valid_statuses), font=("Arial", 12), height=35
        )
        if selected_user:
            self.status_entry.set(selected_user[3])
        self.status_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Remarks
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Remarks:", text_color="#FFFFFF").pack(side="left")
        self.remarks_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        self.remarks_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        self.submit_btn = ctk.CTkButton(
            btn_frame,
            text="Submit",
            image=self.icons["save"],
            compound="left",
            command=self._trigger_submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.submit_btn.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            image=self.icons["cancel"],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        ).pack(side="left", padx=5)

        btn_frame.pack(pady=10)

        self.bind("<Return>", lambda e: self._trigger_submit())
        self.bind("<Escape>", lambda e: self.destroy())

    # ----------------------------------------------------------------------
    def _trigger_submit(self) -> None:
        if self.submit_btn.cget("state") != "disabled":
            self.submit()

    # ----------------------------------------------------------------------
    def submit(self) -> None:
        def _work():
            try:
                username = self.username_entry.get().strip()
                new_status = self.status_entry.get()
                remarks = self.remarks_entry.get().strip() or None

                if not validate_not_empty(username, "Username", self.log_feedback):
                    self.after(0, lambda: show_error(self, "Username is required"))
                    return
                if new_status not in self.user_mgr.valid_statuses:
                    self.after(0, lambda: show_error(self, f"Status must be one of {self.user_mgr.valid_statuses}"))
                    return
                if username == self.username:
                    self.after(0, lambda: show_error(self, "Cannot change your own status"))
                    return

                self.user_mgr.update_user_status(username, new_status, self.username, remarks)

                self.after(
                    0,
                    lambda: [
                        show_info(self, f"Status updated for {username} to {new_status}"),
                        self.log_feedback(f"Status updated for {username} to {new_status}"),
                        logger.info(f"Status updated for {username} to {new_status} by {self.username}"),
                        (self.callback() if self.callback else None),
                        self.destroy(),
                    ],
                )
            except Exception as exc:
                msg = f"Error updating status: {exc}"
                self.after(
                    0,
                    lambda: [
                        show_error(self, msg),
                        self.log_feedback(f"Error updating status for {username}: {exc}"),
                        logger.error(f"Error updating status for {username} by {self.username}: {exc}"),
                    ],
                )
            finally:
                self.after(0, lambda: self.submit_btn.configure(state="normal", text="Submit"))

        self.submit_btn.configure(state="disabled", text="Updating...")
        threading.Thread(target=_work, daemon=True).start()


# ----------------------------------------------------------------------
# DELETE USER FORM
# ----------------------------------------------------------------------
class DeleteUserForm(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        user_mgr: UserManager,
        username: str,
        icons: dict,
        selected_user: Optional[tuple] = None,
        callback: Optional[Callable[[], None]] = None,
        log_feedback: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)
        self.title("Delete User")
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")

        self.user_mgr = user_mgr
        self.username = username
        self.icons = icons
        self.selected_user = selected_user
        self.callback = callback
        self.log_feedback = log_feedback or (lambda _: None)

        logger.info(f"Initializing DeleteUserForm for user {username}")

        # ------------------------------------------------------------------
        # Layout
        # ------------------------------------------------------------------
        form = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        form.pack(pady=10, padx=10, fill="both", expand=True)

        # Username
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Username:", text_color="#FFFFFF").pack(side="left")
        self.username_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        if selected_user:
            self.username_entry.insert(0, selected_user[1])
            self.username_entry.configure(state="disabled")
        self.username_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Remarks
        row = ctk.CTkFrame(form, fg_color="#2B2B2B")
        ctk.CTkLabel(row, text="Remarks:", text_color="#FFFFFF").pack(side="left")
        self.remarks_entry = ctk.CTkEntry(row, font=("Arial", 12), height=35)
        self.remarks_entry.pack(side="left", fill="x", expand=True, padx=5)
        row.pack(fill="x", pady=5)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        self.submit_btn = ctk.CTkButton(
            btn_frame,
            text="Submit",
            image=self.icons["save"],
            compound="left",
            command=self._trigger_submit,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        )
        self.submit_btn.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            image=self.icons["cancel"],
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10,
        ).pack(side="left", padx=5)

        btn_frame.pack(pady=10)

        self.bind("<Return>", lambda e: self._trigger_submit())
        self.bind("<Escape>", lambda e: self.destroy())

    # ----------------------------------------------------------------------
    def _trigger_submit(self) -> None:
        if self.submit_btn.cget("state") != "disabled":
            self.submit()

    # ----------------------------------------------------------------------
    def submit(self) -> None:
        def _work():
            try:
                username = self.username_entry.get().strip()
                remarks = self.remarks_entry.get().strip() or None

                if not validate_not_empty(username, "Username", self.log_feedback):
                    self.after(0, lambda: show_error(self, "Username is required"))
                    return
                if username == self.username:
                    self.after(0, lambda: show_error(self, "Cannot delete your own account"))
                    return
                if not messagebox.askyesno("Confirm Delete", f"Delete user {username}?", parent=self):
                    self.after(0, lambda: self.log_feedback(f"Delete user {username} cancelled"))
                    logger.info(f"Delete user {username} cancelled by {self.username}")
                    return

                self.user_mgr.delete_user(username, self.username, remarks)

                self.after(
                    0,
                    lambda: [
                        show_info(self, f"User {username} deleted successfully"),
                        self.log_feedback(f"User {username} deleted successfully"),
                        logger.info(f"User {username} deleted by {self.username}"),
                        (self.callback() if self.callback else None),
                        self.destroy(),
                    ],
                )
            except Exception as exc:
                msg = f"Error deleting user: {exc}"
                self.after(
                    0,
                    lambda: [
                        show_error(self, msg),
                        self.log_feedback(f"Error deleting user {username}: {exc}"),
                        logger.error(f"Error deleting user {username} by {self.username}: {exc}"),
                    ],
                )
            finally:
                self.after(0, lambda: self.submit_btn.configure(state="normal", text="Submit"))

        self.submit_btn.configure(state="disabled", text="Deleting...")
        threading.Thread(target=_work, daemon=True).start()


# ----------------------------------------------------------------------
# USER TAB 
# ----------------------------------------------------------------------
class UserTab:
    def __init__(self, parent, db_name: str, username: Optional[str], role: Optional[str], main_window, icons):
        self.parent = parent
        self.db_name = db_name
        self.username = username
        self.role = role
        self.main_window = main_window
        self.icons = icons
        self.user_mgr = UserManager(db_name)
        self.sort_column_name = None
        self.sort_reverse = False
        self.tree = None
        self.user_entries = {}
        self.setup_gui()
        logger.info(f"Initialized UserTab with username={username}, role={role}")
        self.main_window.log_feedback("UserTab initialized; data will load after login")

    def setup_gui(self):
        """Set up the UserTab GUI."""
        self.main_frame = ctk.CTkFrame(self.parent, fg_color="#2B2B2B", corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.role and self.role != 'admin':
            ctk.CTkLabel(self.main_frame, text="Permission Denied: Admin role required to access User Management",
                         font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=20)
            self.main_window.log_feedback("Access denied: Admin role required")
            return

        # User form (for selection only)
        '''logger.debug("Creating user_form in UserTab")
        self.user_form = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.user_form, text="User Management", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=5)
        fields = [("Username", "username"), ("Password", "password"), ("Role", "role"), ("Status", "status"), ("Remarks", "remarks")]
        for label, key in fields:
            frame = ctk.CTkFrame(self.user_form, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=100, text_color="#FFFFFF").pack(side="left")
            if key == "role":
                self.user_entries[key] = ctk.CTkComboBox(frame, values=list(self.user_mgr.valid_roles), font=("Arial", 12), height=35)
            elif key == "status":
                self.user_entries[key] = ctk.CTkComboBox(frame, values=list(self.user_mgr.valid_statuses), font=("Arial", 12), height=35)
            else:
                self.user_entries[key] = ctk.CTkEntry(frame, show="*" if key == "password" else None, font=("Arial", 12), height=35)
            self.user_entries[key].pack(side="left", fill="x", expand=True)
            frame.pack(fill="x", pady=2)
            logger.debug(f"Added user field: {label}")
        self.user_form.pack(pady=10, padx=10, fill="x")'''

        # Buttons
        logger.debug("Creating button_frame in UserTab")
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkButton(
            self.button_frame,
            text="Create User",
            image=self.icons['add'],
            compound="left",
            command=self.open_create_user_form,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.button_frame,
            text="Reset Password",
            image=self.icons['edit'],
            compound="left",
            command=self.open_reset_password_form,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.button_frame,
            text="Update Status",
            image=self.icons['edit'],
            compound="left",
            command=self.open_update_status_form,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        ctk.CTkButton(
            self.button_frame,
            text="Delete User",
            image=self.icons['delete'],
            compound="left",
            command=self.open_delete_user_form,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        ).pack(side="left", padx=5)
        self.button_frame.pack(pady=10)

        # Users table
        logger.debug("Creating table_frame in UserTab")
        self.table_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        columns = ("User ID", "Username", "Role", "Status", "Created At", "Updated At")
        self.tree = ttk.Treeview(self.table_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c))
            self.tree.column(col, width=100)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ctk.CTkScrollbar(self.table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_user)
        self.table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_data()
        self.main_frame.update_idletasks()
        logger.info("UserTab GUI initialized")

    def open_create_user_form(self):
        """Open the create user form."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Open create user form failed: Permission denied")
            return
        self.main_window.open_form_window(
            title="Create User",
            form_class=CreateUserForm,
            user_mgr=self.user_mgr,
            username=self.username,
            icons=self.icons,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_reset_password_form(self):
        """Open the reset password form."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Open reset password form failed: Permission denied")
            return
        selected = self.tree.selection()
        selected_user = None
        if selected:
            selected_user = self.tree.item(selected[0])['values']
        self.main_window.open_form_window(
            title="Reset Password",
            form_class=ResetPasswordForm,
            user_mgr=self.user_mgr,
            username=self.username,
            icons=self.icons,
            selected_user=selected_user,
            callback=self.refresh_data, 
            log_feedback=self.main_window.log_feedback
        )

    def open_update_status_form(self):
        """Open the update status form."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Open update status form failed: Permission denied")
            return
        selected = self.tree.selection()
        selected_user = None
        if selected:
            selected_user = self.tree.item(selected[0])['values']
        self.main_window.open_form_window(
            title="Update User Status",
            form_class=UpdateStatusForm,
            user_mgr=self.user_mgr,
            username=self.username,
            icons=self.icons,
            selected_user=selected_user,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def open_delete_user_form(self):
        """Open the delete user form."""
        if self.role != 'admin':
            show_error(self.main_window, "Permission denied: Admin role required")
            self.main_window.log_feedback("Open delete user form failed: Permission denied")
            return
        selected = self.tree.selection()
        selected_user = None
        if selected:
            selected_user = self.tree.item(selected[0])['values']
        self.main_window.open_form_window(
            title="Delete User",
            form_class=DeleteUserForm,
            user_mgr=self.user_mgr,
            username=self.username,
            icons=self.icons,
            selected_user=selected_user,
            callback=self.refresh_data,
            log_feedback=self.main_window.log_feedback
        )

    def refresh_data(self):
        """Load or refresh user data after login."""
        if not self.username or not self.role:
            self.main_window.log_feedback("Cannot load users: No user logged in")
            logger.warning(f"Cannot load users: No user logged in")
            return
        if self.role != 'admin':
            self.main_window.log_feedback("Cannot load users: Admin role required")
            logger.warning(f"Cannot load users: Admin role required")
            return
        try:
            users = self.user_mgr.fetch_all_users(self.username, self.role)
            self.tree.delete(*self.tree.get_children())
            for user in users:
                self.tree.insert("", "end", values=(
                    user['user_id'], user['username'], user['role'], user['status'],
                    user['created_at'], user['updated_at'] or ''
                ))
            self.main_window.log_feedback(f"Loaded {len(users)} user records")
            logger.info(f"Loaded {len(users)} user records for user {self.username}")
        except Exception as e:
            self.main_window.log_feedback(f"Error loading users: {str(e)}")
            logger.error(f"Error loading users for user {self.username}: {str(e)}")
            show_error(self.main_window, f"Error loading users: {str(e)}")

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
                    return int(value) if col == "User ID" else value.lower()
                except (ValueError, AttributeError):
                    return value

            records.sort(key=lambda x: convert(x[0]), reverse=self.sort_reverse)

            for index, (value, item) in enumerate(records):
                self.tree.move(item, "", index)

            for column in self.tree["columns"]:
                self.tree.heading(column, text=column)
            arrow = " ↓" if not self.sort_reverse else " ↑"
            self.tree.heading(col, text=col + arrow)
            self.main_window.log_feedback(f"Sorted users table by {col} {'descending' if self.sort_reverse else 'ascending'}")
            logger.info(f"Sorted users table by {col} {'descending' if self.sort_reverse else 'ascending'} by user {self.username}")
        except Exception as e:
            self.main_window.log_feedback(f"Error sorting table by {col}: {str(e)}")
            logger.error(f"Error sorting table by {col} for user {self.username}: {str(e)}")
            show_error(self.main_window, f"Error sorting table: {str(e)}")

    def on_select_user(self, event):
        """Handle user selection in treeview - log selection for now."""
        selected = self.tree.selection()
        if not selected:
            return
        item = self.tree.item(selected[0])['values']
        user_id, username, role, status, created_at, updated_at = item
        
        # Check if user form entries exist (they may not if using popup forms only)
        if not self.user_entries:
            self.main_window.log_feedback(f"Selected user: {username} - Use Edit button to modify")
            logger.info(f"Selected user: {username} by user {self.username}")
            return
        
        self.user_entries['username'].delete(0, "end")
        self.user_entries['username'].insert(0, username)
        self.user_entries['password'].delete(0, "end")
        self.user_entries['role'].set(role)
        self.user_entries['status'].set(status)
        self.user_entries['remarks'].delete(0, "end")
        self.main_window.log_feedback(f"Selected user: {username}")
        logger.info(f"Selected user: {username} by user {self.username}")

    def clear_user_form(self):
        """Clear the user form fields."""
        # Check if user form entries exist (they may not if using popup forms only)
        if not self.user_entries:
            self.main_window.log_feedback("User form cleared - using popup forms")
            return
            
        for key in ['username', 'password', 'remarks']:
            self.user_entries[key].delete(0, "end")
        self.user_entries['role'].set('viewer')
        self.user_entries['status'].set('active')
        self.main_window.log_feedback("User form cleared")
        logger.info(f"User form cleared by user {self.username}")