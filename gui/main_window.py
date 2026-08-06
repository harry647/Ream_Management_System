import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter.ttk import Style
from PIL import Image
from gui.students_tab import StudentsTab
from gui.reams_tab import ReamsTab
from gui.issues_tab import IssuesTab
from gui.reports_tab import ReportsTab
from gui.user_tab import UserTab
from gui.settings import SettingsWindow
from modules.user_manager import UserManager
from modules.report_manager import ReportManager
from gui.utils import show_error, show_info
from modules.db_setup import get_logs_dir, get_config_dir, get_database_path, get_bundle_dir
import logging
import json
import os
import sqlite3
from datetime import datetime
import time

# Configure logging
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'main_window.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LoginWindow(ctk.CTkToplevel):
    def __init__(self, parent, callback, user_mgr):
        super().__init__(parent)
        self.title("Ream Management System - Login")
        self.geometry("900x750")
        self.resizable(True, True)
        self.minsize(350, 350)
        self.callback = callback
        self.user_mgr = user_mgr
        logger.info("Initializing LoginWindow")

        # Load remembered user
        self.remembered_user = self.load_remembered_user()

        # Center window
        self.configure(fg_color="#1E1E1E")
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self.grab_set()

        # Main frame
        frame = ctk.CTkFrame(self, corner_radius=15, fg_color="#2B2B2B")
        frame.pack(pady=20, padx=20, fill="both", expand=True)

        # Title
        ctk.CTkLabel(frame, text="Ream Management System", font=("Arial", 24, "bold"), text_color="#FFFFFF").pack(pady=10)
        ctk.CTkLabel(frame, text="Please log in to continue", font=("Arial", 14), text_color="#A0AEC0").pack(pady=5)

        # Username
        ctk.CTkLabel(frame, text="Username", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(10, 2))
        self.username_entry = ctk.CTkEntry(frame, placeholder_text="Enter username", font=("Arial", 12), height=35)
        self.username_entry.pack(pady=5, padx=20, fill="x")

        # Password
        ctk.CTkLabel(frame, text="Password", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(10, 2))
        self.password_entry = ctk.CTkEntry(frame, placeholder_text="Enter password", show="*", font=("Arial", 12), height=35)
        self.password_entry.pack(pady=5, padx=20, fill="x")

        # Show Password
        self.show_password_var = ctk.BooleanVar(value=False)
        self.show_password_check = ctk.CTkCheckBox(
            frame, text="Show Password", variable=self.show_password_var,
            command=self.toggle_password_visibility, font=("Arial", 10), text_color="#FFFFFF"
        )
        self.show_password_check.pack(pady=5)

        # Role
        ctk.CTkLabel(frame, text="Role", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(10, 2))
        self.role_entry = ctk.CTkComboBox(frame, values=["viewer", "staff", "admin"], state="readonly", font=("Arial", 12), height=35)
        self.role_entry.pack(pady=5, padx=20, fill="x")

        # Remember Me
        self.remember_var = ctk.BooleanVar(value=False)
        self.remember_check = ctk.CTkCheckBox(
            frame, text="Remember Me", variable=self.remember_var,
            font=("Arial", 10), text_color="#FFFFFF"
        )
        self.remember_check.pack(pady=5)

        # Login button
        login_icon = ctk.CTkImage(light_image=Image.open(os.path.join(get_bundle_dir(), "icons", "login.png")), size=(16, 16))
        self.login_button = ctk.CTkButton(
            frame, text="Login", image=login_icon, compound="left",
            command=self.authenticate, fg_color="#2B6CB0", hover_color="#1E4E79",
            text_color="#FFFFFF", font=("Arial", 12, "bold"), height=40, corner_radius=10
        )
        self.login_button.pack(pady=20, padx=20, fill="x")

        # Bind Enter
        self.bind("<Return>", lambda e: self.authenticate())

        # Tab navigation
        self.username_entry.focus_set()
        self.username_entry.bind("<Tab>", lambda e: self.password_entry.focus_set())
        self.password_entry.bind("<Tab>", lambda e: self.role_entry.focus_set())
        self.role_entry.bind("<Tab>", lambda e: self.show_password_check.focus_set())
        self.show_password_check.bind("<Tab>", lambda e: self.remember_check.focus_set())
        self.remember_check.bind("<Tab>", lambda e: self.login_button.focus_set())
        self.login_button.bind("<Tab>", lambda e: self.username_entry.focus_set())

        # Auto-fill if remembered
        if self.remembered_user:
            self.username_entry.insert(0, self.remembered_user['username'])
            self.role_entry.set(self.remembered_user['role'])
            self.remember_var.set(True)
            self.password_entry.focus_set()
            logger.info(f"Auto-filled login for {self.remembered_user['username']}")

        logger.info("LoginWindow UI initialized")


    def load_remembered_user(self):
        """Load remembered username and role from config/last_user.json"""
        config_dir = get_config_dir()
        config_path = os.path.join(config_dir, "last_user.json")
        if not os.path.exists(config_path):
            return None
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                return data if data.get("remember", False) else None
        except Exception as e:
            logger.error(f"Failed to load remembered user: {e}")
            return None

    def save_remembered_user(self, username, role):
        """Save username and role if Remember Me is checked"""
        if not self.remember_var.get():

            # Clear file if unchecked
            config_dir = get_config_dir()
            config_path = os.path.join(config_dir, "last_user.json")
            if os.path.exists(config_path):
                os.remove(config_path)
            return

        data = {
            "username": username,
            "role": role,
            "remember": True
        }
        config_dir = get_config_dir()
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "last_user.json")
        with open(config_path, "w") as f:
            json.dump(data, f)
        logger.info(f"Remembered user: {username} ({role})")

    def toggle_password_visibility(self):
        """Toggle password visibility."""
        if self.show_password_var.get():
            self.password_entry.configure(show="")
        else:
            self.password_entry.configure(show="*")
        logger.info("Toggled password visibility")

    def authenticate(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        role = self.role_entry.get()
        try:
            user_data = self.user_mgr.authenticate_user(username, password)
            if not user_data:
                error_msg = "Invalid username or password"
                show_error(self, error_msg, self.master.log_feedback)
                logger.warning(f"Login failed for {username}: {error_msg}")
                self.master.log_feedback(f"Login failed for {username}: {error_msg}")
                return
            if user_data['status'] != 'active':
                error_msg = f"User {username} is inactive"
                show_error(self, error_msg, self.master.log_feedback)
                logger.warning(error_msg)
                self.master.log_feedback(error_msg)
                return
            if user_data['role'] != role:
                error_msg = f"User {username} does not have {role} role"
                show_error(self, error_msg, self.master.log_feedback)
                logger.warning(error_msg)
                self.master.log_feedback(error_msg)

            # Save if Remember Me checked
            self.save_remembered_user(username, role)

            logger.info(f"User {username} logged in successfully with role {role}")
            self.master.log_feedback(f"User {username} logged in successfully with role {role}")
            self.callback(username, role, password) 
            self.destroy()
        except Exception as e:
            error_msg = f"Login error: {str(e)}"
            show_error(self, error_msg, self.master.log_feedback)
            logger.error(f"Login error for {username}: {str(e)}")
            self.master.log_feedback(error_msg)

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ream Management System")
        self.geometry("1280x720")
        self.resizable(True, True)
        self.minsize(1000, 600)
        self.configure(fg_color="#1E1E1E")
        logger.info("Initializing MainWindow")

        # Load theme preference
        config_dir = get_config_dir()
        self.theme_file = os.path.join(config_dir, "theme.json")
        try:
            with open(self.theme_file, "r") as f:
                theme = json.load(f)
                appearance_mode = theme.get("appearance_mode", "dark")
                color_theme = theme.get("color_theme", "blue")
        except FileNotFoundError:
            appearance_mode = "dark"
            color_theme = "blue"
        ctk.set_appearance_mode(appearance_mode)
        ctk.set_default_color_theme(color_theme)
        logger.info(f"Set theme: {appearance_mode}/{color_theme}")

        # Ensure directories exist
        logs_dir = get_logs_dir()
        config_dir = get_config_dir()
        os.makedirs(logs_dir, exist_ok=True)
        os.makedirs(config_dir, exist_ok=True)

        self.username = None
        self.role = None
        self.db_name = get_database_path()
        self.current_button_index = 0
        self.user_mgr = UserManager(self.db_name)

        # Load icons
        bundle_dir = get_bundle_dir()
        self.icons = {
            'students': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "students.png")), size=(16, 16)),
            'reams': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "reams.png")), size=(16, 16)),
            'issues': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "issues.png")), size=(16, 16)),
            'reports': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "report.png")), size=(16, 16)),
            'users': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "users.png")), size=(16, 16)),
            'theme_toggle': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "theme_toggle.png")), size=(16, 16)),
            'exit': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "exit.png")), size=(16, 16)),
            'logout': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "logout.png")), size=(16, 16)),
            'login': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "login.png")), size=(16, 16)),
            'add': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "add.png")), size=(16, 16)),
            'edit': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "edit.png")), size=(16, 16)),
            'delete': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "delete.png")), size=(16, 16)),
            'save': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "save.png")), size=(16, 16)),
            'cancel': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "cancel.png")), size=(16, 16)),
            'report': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "report.png")), size=(16, 16)),
            'export': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "export.png")), size=(16, 16)),
            'dashboard': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "dashboard.png")), size=(16, 16)),
            'chart': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "chart.png")), size=(16, 16)),
            'refresh': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "refresh.png")), size=(16, 16)),
            'search': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "search.png")), size=(16, 16)),
            'settings': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "settings.png")), size=(16, 16)),
            'calendar': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "calendar.png")), size=(16, 16)),
            'help': ctk.CTkImage(light_image=Image.open(os.path.join(bundle_dir, "icons", "help.png")), size=(16, 16))
        }

        # Styling for Treeview
        style = Style()
        style.configure("Treeview", font=("Arial", 11), rowheight=30, background="#2B2B2B", foreground="#FFFFFF", fieldbackground="#2B2B2B")
        style.configure("Treeview.Heading", font=("Arial", 11, "bold"), background="#1E4E79", foreground="#FFFFFF")
        style.map("Treeview", background=[('selected', '#4A5568')])

        # Main layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top bar
        self.top_bar = ctk.CTkFrame(self, height=60, fg_color="#2B2B2B", corner_radius=0)
        self.top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.top_bar.grid_columnconfigure(1, weight=1)
        self.title_label = ctk.CTkLabel(self.top_bar, text="Ream Management System", font=("Arial", 18, "bold"), text_color="#FFFFFF")
        self.title_label.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # Date and time frame
        self.datetime_frame = ctk.CTkFrame(self.top_bar, fg_color="#2B2B2B")
        self.datetime_frame.grid(row=0, column=1, padx=(0, 20), pady=10, sticky="e")
        self.date_label = ctk.CTkLabel(self.datetime_frame, text="", font=("Arial", 12), text_color="#A0AEC0")
        self.date_label.pack(side="left", padx=(0, 10))
        self.day_label = ctk.CTkLabel(self.datetime_frame, text="", font=("Arial", 12), text_color="#A0AEC0")
        self.day_label.pack(side="left", padx=(0, 10))
        self.time_label = ctk.CTkLabel(self.datetime_frame, text="", font=("Arial", 12), text_color="#A0AEC0")
        self.time_label.pack(side="left")
        self.datetime_format = self.load_datetime_format() 
        self.update_datetime()  

        self.user_info_label = ctk.CTkLabel(self.top_bar, text="User: None", font=("Arial", 12), text_color="#A0AEC0")
        self.user_info_label.grid(row=0, column=2, padx=(0, 10), pady=10, sticky="e")
        self.logout_button = ctk.CTkButton(
            self.top_bar,
            text="Logout",
            image=self.icons['logout'],
            compound="left",
            command=self.logout,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12),
            width=120,
            height=30,
            corner_radius=8
        )
        self.logout_button.grid(row=0, column=3, padx=10, pady=10)
        self.logout_button.bind("<Enter>", lambda e: self.show_tooltip(e, "Log out of the application"))
        self.logout_button.bind("<Leave>", lambda e: self.hide_tooltip())

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, fg_color="#2B2B2B", corner_radius=10)
        self.sidebar.grid(row=1, column=0, sticky="nsw", padx=10, pady=(0, 10))
        self.sidebar.grid_propagate(False)
        ctk.CTkLabel(self.sidebar, text="Navigation", font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=(10, 5))
        self.nav_buttons = []
        tabs = [
            ("Students", 'students'),
            ("Reams", 'reams'),
            ("Issues", 'issues'),
            ("Reports", 'reports'),
            ("Users", 'users')
        ]
        for tab, icon_key in tabs:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {tab}",
                image=self.icons[icon_key],
                compound="left",
                command=lambda t=tab: self.show_tab(t),
                fg_color="transparent",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                anchor="w",
                font=("Arial", 13),
                height=40,
                corner_radius=8
            )
            btn.pack(pady=5, padx=10, fill="x")
            btn.bind("<Enter>", lambda e, t=tab: self.show_tooltip(e, f"Switch to {t} tab"))
            btn.bind("<Leave>", lambda e: self.hide_tooltip())
            self.nav_buttons.append((tab, btn))
        self.theme_button = ctk.CTkButton(
            self.sidebar,
            text="  Toggle Theme",
            image=self.icons['theme_toggle'],
            compound="left",
            command=self.toggle_theme,
            fg_color="transparent",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            anchor="w",
            font=("Arial", 13),
            height=40,
            corner_radius=8
        )
        self.theme_button.pack(pady=5, padx=10, fill="x")
        self.theme_button.bind("<Enter>", lambda e: self.show_tooltip(e, "Toggle light/dark theme"))
        self.theme_button.bind("<Leave>", lambda e: self.hide_tooltip())
        self.nav_buttons.append(("Toggle Theme", self.theme_button))

        # Settings button
        self.settings_button = ctk.CTkButton(
            self.sidebar,
            text="  Settings",
            image=self.icons['settings'],
            compound="left",
            command=self.open_settings,
            fg_color="transparent",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            anchor="w",
            font=("Arial", 13),
            height=40,
            corner_radius=8
        )
        self.settings_button.pack(pady=5, padx=10, fill="x")
        self.settings_button.bind("<Enter>", lambda e: self.show_tooltip(e, "Open application settings"))
        self.settings_button.bind("<Leave>", lambda e: self.hide_tooltip())
        self.nav_buttons.append(("Settings", self.settings_button))

        # Help button
        self.help_button = ctk.CTkButton(
            self.sidebar,
            text=" Help Guide",
            image=self.icons['help'],
            compound="left",
            command=self.open_help,
            fg_color="transparent",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            anchor="w",
            font=("Arial", 13),
            height=40,
            corner_radius=8
        )
        self.help_button.pack(pady=5, padx=10, fill="x")
        self.help_button.bind("<Enter>", lambda e: self.show_tooltip(e, "Open help guide"))
        self.help_button.bind("<Leave>", lambda e: self.hide_tooltip())
        self.nav_buttons.append(("Help Guide", self.help_button))

        # exit button
        self.exit_button = ctk.CTkButton(
            self.sidebar,
            text="  Exit",
            image=self.icons['exit'],
            compound="left",
            command=self.quit_app,
            fg_color="transparent",
            hover_color="#C53030",
            text_color="#FFFFFF",
            anchor="w",
            font=("Arial", 13),
            height=40,
            corner_radius=8
        )
        self.exit_button.pack(pady=5, padx=10, fill="x")
        self.exit_button.bind("<Enter>", lambda e: self.show_tooltip(e, "Exit application"))
        self.exit_button.bind("<Leave>", lambda e: self.hide_tooltip())
        self.nav_buttons.append(("Exit", self.exit_button))

        # Content area
        self.content_frame = ctk.CTkFrame(self, fg_color="#1E1E1E", corner_radius=10)
        self.content_frame.grid(row=1, column=1, sticky="nsew", padx=10, pady=(0, 10))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(1, weight=1)

        # Stock overview
        self.stock_frame = ctk.CTkFrame(self.content_frame, fg_color="#2B2B2B", corner_radius=10)
        self.stock_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.stock_label = ctk.CTkLabel(self.stock_frame, text="Stock Overview: Loading...", font=("Arial", 12, "bold"), text_color="#FFFFFF", wraplength=1000)
        self.stock_label.pack(pady=10, padx=10)

        # Tabview
        self.tabview = ctk.CTkTabview(self.content_frame, fg_color="#2B2B2B", segmented_button_selected_color="#2B6CB0", segmented_button_unselected_color="#2B2B2B", text_color="#FFFFFF", segmented_button_selected_hover_color="#1E4E79")
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        # Status bar
        self.status_bar = ctk.CTkFrame(self, height=30, fg_color="#2B2B2B", corner_radius=0)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.status_label = ctk.CTkLabel(self.status_bar, text="Ready", font=("Arial", 10), text_color="#A0AEC0")
        self.status_label.pack(side="left", padx=10)
        self.feedback_log = ctk.CTkTextbox(self.status_bar, height=30, state="disabled", font=("Arial", 10), fg_color="#2B2B2B", text_color="#FFFFFF")
        self.feedback_log.pack(side="right", fill="x", expand=True, padx=10)

        # Tooltip label
        self.tooltip_label = ctk.CTkLabel(self, text="", font=("Arial", 10), fg_color="#4A5568", text_color="#FFFFFF", corner_radius=8)
        self.tooltip_label.place_forget()

        # Initialize tab placeholders
        self.tabs = {}
        self.tab_frames = {}
        tab_names = ["Students", "Reams", "Issues", "Reports", "Users"]
        for tab_name in tab_names:
            self.tabview.add(tab_name)
            scroll_frame = ctk.CTkScrollableFrame(self.tabview.tab(tab_name), fg_color="#2B2B2B")
            scroll_frame.pack(fill="both", expand=True)
            self.tab_frames[tab_name] = scroll_frame
            self.tabs[tab_name] = None
            logger.info(f"Added placeholder tab with scrollable frame: {tab_name}")

        # Keyboard bindings
        self.bind("<Up>", self.navigate_up)
        self.bind("<Down>", self.navigate_down)
        self.bind("<Left>", self.navigate_left)
        self.bind("<Right>", self.navigate_right)
        self.bind("<Return>", self.activate_button)
        self.bind("<Tab>", self.navigate_tab)

        # Show login window
        self.login_window = LoginWindow(self, self.on_login, self.user_mgr)
        self.withdraw()
        logger.info("LoginWindow shown, MainWindow withdrawn")

        # Auto-login if remembered and password can be prompted
        if self.login_window.remembered_user:
            self.after(500, self.try_auto_login)


    def try_auto_login(self):
        """Auto-login if Remember Me was checked and user exists"""
        remembered = self.login_window.remembered_user
        if not remembered:
            return

        username = remembered['username']
        role = remembered['role']

        # Prompt for password
        password = simpledialog.askstring(
            "Password Required", f"Enter password for {username}:", show="*", parent=self.login_window
        )
        if not password:
            return

        # Try login
        try:
            user_data = self.user_mgr.authenticate_user(username, password)
            if user_data and user_data['role'] == role and user_data['status'] == 'active':
                self.login_window.destroy()
                self.on_login(username, role, password)
                self.log_feedback(f"Auto-login successful for {username}")
                logger.info(f"Auto-login: {username}")
            else:
                messagebox.showerror("Auto-Login Failed", "Invalid password or role mismatch", parent=self)
        except Exception as e:
            messagebox.showerror("Error", f"Auto-login failed: {e}", parent=self)

    def animate_tab(self, tab_name):
        """Animate tab content fade-in."""
        if tab_name in self.tab_frames:
            scroll_frame = self.tab_frames[tab_name]
            scroll_frame.configure(fg_color="#2B2B2B")
            scroll_frame.pack_forget()
            scroll_frame.pack(fill="both", expand=True)
            logger.info(f"Started fade-in animation for {tab_name}")

    def show_tooltip(self, event, text):
        """Show tooltip near the mouse cursor with adjusted positioning."""
        self.tooltip_label.configure(text=text)
        x = self.winfo_pointerx() + 15
        y = self.winfo_pointery() + 15
        max_x = self.winfo_screenwidth() - 200
        max_y = self.winfo_screenheight() - 50
        x = min(x, max_x)
        y = min(y, max_y)
        self.tooltip_label.place(x=x, y=y)
        logger.debug(f"Showing tooltip: {text} at ({x}, {y})")

    def hide_tooltip(self):
        """Hide tooltip."""
        self.tooltip_label.place_forget()
        logger.debug("Tooltip hidden")

    def log_feedback(self, message: str):
        """Log feedback to the status bar and logger."""
        self.status_label.configure(text=message)
        self.feedback_log.configure(state="normal")
        self.feedback_log.insert("end", f"{message}\n")
        self.feedback_log.configure(state="disabled")
        self.feedback_log.see("end")
        logger.info(message)

    def navigate_up(self, event):
        """Navigate to the previous sidebar button."""
        if self.current_button_index > 0:
            self.current_button_index -= 1
            self.update_button_focus()
            self.log_feedback(f"Navigated to {self.nav_buttons[self.current_button_index][0]} via Up key")

    def navigate_down(self, event):
        """Navigate to the next sidebar button."""
        if self.current_button_index < len(self.nav_buttons) - 1:
            self.current_button_index += 1
            self.update_button_focus()
            self.log_feedback(f"Navigated to {self.nav_buttons[self.current_button_index][0]} via Down key")

    def update_button_focus(self):
        """Update focus and highlight for the current sidebar button."""
        for index, (name, btn) in enumerate(self.nav_buttons):
            if index == self.current_button_index:
                btn.focus_set()
                btn.configure(fg_color="#1E4E79", text_color="#FFFFFF")
            else:
                btn.configure(fg_color="transparent", text_color="#A0AEC0")
        logger.debug(f"Updated button focus to index {self.current_button_index}")

    def navigate_left(self, event):
        """Switch to the previous tab."""
        tabs = [name for name, tab in self.tabs.items() if tab is not None]
        current_tab = self.tabview.get()
        current_index = tabs.index(current_tab) if current_tab in tabs else 0
        if current_index > 0:
            new_tab = tabs[current_index - 1]
            self.show_tab(new_tab)
            self.log_feedback(f"Switched to {new_tab} tab via Left key")

    def navigate_right(self, event):
        """Switch to the next tab."""
        tabs = [name for name, tab in self.tabs.items() if tab is not None]
        current_tab = self.tabview.get()
        current_index = tabs.index(current_tab) if current_tab in tabs else 0
        if current_index < len(tabs) - 1:
            new_tab = tabs[current_index + 1]
            self.show_tab(new_tab)
            self.log_feedback(f"Switched to {new_tab} tab via Right key")

    def activate_button(self, event):
        """Activate the currently focused sidebar button."""
        if 0 <= self.current_button_index < len(self.nav_buttons):
            name, btn = self.nav_buttons[self.current_button_index]
            btn.invoke()
            self.log_feedback(f"Activated {name} via Enter key")

    def navigate_tab(self, event):
        """Cycle focus between sidebar and tabview content."""
        current_focus = self.focus_get()
        if current_focus in [btn for _, btn in self.nav_buttons]:
            current_tab = self.tabview.get()
            if current_tab in self.tabs and self.tabs[current_tab] is not None:
                focusable = self.tab_frames[current_tab].winfo_children()
                for widget in focusable:
                    if isinstance(widget, (ctk.CTkEntry, ctk.CTkComboBox, ctk.CTkButton)):
                        widget.focus_set()
                        self.log_feedback(f"Focused on {current_tab} tab content via Tab key")
                        return
        else:
            self.nav_buttons[self.current_button_index][1].focus_set()
            self.log_feedback(f"Focused on {self.nav_buttons[self.current_button_index][0]} button via Tab key")

    def load_datetime_format(self):
        """Load the datetime format from the settings table, with fallback if table is missing."""
        default_format = '%Y-%m-%d | %A | %I:%M:%S %p'
        try:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
            if cursor.fetchone() is None:
                logger.warning("Settings table does not exist, using default datetime format")
                return default_format
            cursor.execute("SELECT datetime_format FROM settings ORDER BY setting_id DESC LIMIT 1")
            result = cursor.fetchone()
            conn.close()
            return result['datetime_format'] if result and result['datetime_format'] else default_format
        except Exception as e:
            logger.error(f"Error loading datetime format: {str(e)}")
            self.log_feedback(f"Error loading datetime format: {str(e)}")
            return default_format

    def update_datetime(self):
        """Update the date, day, and time labels."""
        try:
            current_time = datetime.now()
            format_parts = self.datetime_format.split(' | ')
            date_format = format_parts[0] if len(format_parts) > 0 else '%Y-%m-%d'
            day_format = format_parts[1] if len(format_parts) > 1 else '%A'
            time_format = format_parts[2] if len(format_parts) > 2 else '%I:%M:%S %p'

            date_str = current_time.strftime(date_format)
            day_str = current_time.strftime(day_format)
            time_str = current_time.strftime(time_format)

            self.date_label.configure(text=f"Date: {date_str}")
            self.day_label.configure(text=f"Day: {day_str}")
            self.time_label.configure(text=f"Time: {time_str}")

            self.after(1000, self.update_datetime)
            logger.debug("Updated date and time display")
        except Exception as e:
            self.log_feedback(f"Error updating datetime: {str(e)}")
            logger.error(f"Error updating datetime: {str(e)}")

    def update_title(self, school_name):
        """Update the main window title and top bar label with the school name."""
        new_title = f"{school_name} - Ream Management System"
        self.title(new_title)
        self.title_label.configure(text=new_title)
        logger.debug(f"Updated window title to: {new_title}")

    def open_settings(self):
        """Open the settings window."""
        try:
            settings_window = SettingsWindow(
                self,
                self.db_name,
                self.username,
                self.role,
                self.log_feedback,
                self.icons,
                self.update_title,
                self.update_theme
            )
            self.log_feedback("Settings window opened")
            logger.info(f"Settings window opened by {self.username}")
        except Exception as e:
            self.log_feedback(f"Error opening settings: {str(e)}")
            logger.error(f"Error opening settings: {str(e)}")
            messagebox.showerror("Error", f"Failed to open settings: {str(e)}", parent=self)


    def open_help(self):
        """Open help.txt from bundled resources or project root."""
        # Try to find help.txt in bundled resources first (frozen mode)
        # then fall back to project root (development mode)
        bundle_dir = get_bundle_dir()
        help_path = os.path.join(bundle_dir, "help.txt")
        
        # If not in bundle, try project root
        if not os.path.exists(help_path):
            project_root = os.path.dirname(os.path.dirname(__file__))
            help_path = os.path.join(project_root, "help.txt")

        if not os.path.exists(help_path):
            messagebox.showerror(
                "Help Not Found",
                "help.txt is missing in project root:\n" + project_root,
                parent=self
            )
            logger.error(f"help.txt not found at: {help_path}")
            return

        try:
            if os.name == 'nt':  # Windows
                os.startfile(help_path)
            elif sys.platform == 'darwin':  # macOS
                subprocess.call(('open', help_path))
            else:  # Linux
                subprocess.call(('xdg-open', help_path))
            logger.info(f"Opened help.txt: {help_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open help: {e}", parent=self)
            logger.error(f"Failed to open help.txt: {e}")
            
    def on_login(self, username, role, password=None):
        """Handle successful login and initialize tab content."""
        # --------------------------------------------------------------
        # 1. Store login data – these are needed for EVERYTHING later
        # --------------------------------------------------------------
        self.username = username
        self.role     = role

        self.deiconify()
        self.lift()
        self.grab_set()
        logger.debug("MainWindow lifted and focus set after login")
        self.log_feedback(f"Welcome, {username} ({role})")
        self.user_info_label.configure(text=f"{username} ({role})")

        # --------------------------------------------------------------
        # 2. Keep the clock running
        # --------------------------------------------------------------
        self.update_datetime()

        # --------------------------------------------------------------
        # 3. **ONE** ReportManager – created **once** and **set** once
        # --------------------------------------------------------------
        if not hasattr(self, 'report_manager') or self.report_manager is None:
            self.report_manager = ReportManager(self.db_name)
            logger.info("ReportManager created after login")

        if password is not None:
            self.report_manager.set_current_user(username, password)
            logger.info(f"ReportManager session set for {username} using password")
        else:
            pw_hash = self.user_mgr.get_password_hash(username)
            self.report_manager.set_current_user(username, pw_hash)
        logger.info(f"ReportManager session set for {username} using hash fallback")
        logger.info(f"ReportManager session set for {username}")

        # --------------------------------------------------------------
        # 4. Initialise every tab – pass the SAME report_manager instance
        # --------------------------------------------------------------
        try:
            for tab_name in self.tabs:
                scroll_frame = self.tab_frames[tab_name]
                try:
                    if tab_name == "Students":
                        self.tabs[tab_name] = StudentsTab(
                            scroll_frame, self.db_name, username, role, self, self.icons)
                    elif tab_name == "Reams":
                        self.tabs[tab_name] = ReamsTab(
                            scroll_frame, self.db_name, username, role, self, self.icons)
                    elif tab_name == "Issues":
                        self.tabs[tab_name] = IssuesTab(
                            scroll_frame, self.db_name, username, role, self, self.icons)
                    elif tab_name == "Reports":
                        self.tabs[tab_name] = ReportsTab(
                            scroll_frame, self.db_name, username, role, self, self.icons,
                            report_manager=self.report_manager)
                    elif tab_name == "Users":
                        self.tabs[tab_name] = UserTab(
                            scroll_frame, self.db_name, username, role, self, self.icons)

                    logger.info(f"Initialized {tab_name} tab with username={username}, role={role}")

                    # keep each tab in sync
                    if hasattr(self.tabs[tab_name], 'update_user'):
                        self.tabs[tab_name].update_user(username, role)

                    if hasattr(self.tabs[tab_name], 'refresh_data'):
                        self.tabs[tab_name].refresh_data()
                        self.log_feedback(f"Refreshed data for {tab_name} tab")
                        self.update_idletasks()
                except Exception as e:
                    error_msg = f"Failed to initialize {tab_name} tab: {str(e)}"
                    self.log_feedback(error_msg)
                    logger.error(error_msg)
                    continue

            if any(self.tabs[tab_name] is None for tab_name in self.tabs):
                messagebox.showwarning(
                    "Warning",
                    "Some tabs failed to initialize. Some functionality may be limited.",
                    parent=self)
        except Exception as e:
            error_msg = f"Critical error initializing tabs: {str(e)}"
            self.log_feedback(error_msg)
            logger.error(error_msg)
            messagebox.showerror("Error", error_msg, parent=self)
            self.quit()

        # --------------------------------------------------------------
        # 5. Navigation focus
        # --------------------------------------------------------------
        self.nav_buttons[0][1].focus_set()
        self.current_button_index = 0
        self.update_button_focus()

        # --------------------------------------------------------------
        # 6. **UPDATE STOCK OVERVIEW NOW** – username/role are ready
        # --------------------------------------------------------------
        self.update_stock_overview()          # immediate call
        self.after(200, self.update_stock_overview)   # safety retry
        self.show_tab("Students")
        logger.info("MainWindow deiconified and initialized after login")

    def logout(self):
        """Log out the user and return to login screen."""
        if messagebox.askyesno("Logout", "Are you sure you want to log out?", parent=self):
            self.log_feedback(f"User {self.username} logged out")
            logger.info(f"User {self.username} logged out")
            self.username = None
            self.role = None
            self.user_info_label.configure(text="User: None")
            for tab_name in self.tabs:
                self.tabs[tab_name] = None
                self.tab_frames[tab_name].pack_forget()
                self.tab_frames[tab_name] = ctk.CTkScrollableFrame(self.tabview.tab(tab_name), fg_color="#2B2B2B")
                self.tab_frames[tab_name].pack(fill="both", expand=True)
            self.withdraw()
            self.login_window = LoginWindow(self, self.on_login, self.user_mgr)
            self.log_feedback("Logged out, showing login window")

    def update_theme(self, appearance_mode, color_theme):
        """Update the application theme and save to theme.json."""
        try:
            ctk.set_appearance_mode(appearance_mode)
            ctk.set_default_color_theme(color_theme)
            os.makedirs(get_config_dir(), exist_ok=True)
            with open(self.theme_file, "w") as f:
                json.dump({"appearance_mode": appearance_mode, "color_theme": color_theme}, f)
            for tab_name in self.tabs:
                if self.tabs[tab_name] and hasattr(self.tabs[tab_name], 'refresh_data'):
                    self.tabs[tab_name].refresh_data()
            self.log_feedback(f"Switched to {appearance_mode}/{color_theme} theme")
            logger.info(f"Switched to {appearance_mode}/{color_theme} theme")
        except Exception as e:
            self.log_feedback(f"Error updating theme: {str(e)}")
            logger.error(f"Error updating theme: {str(e)}")

    def toggle_theme(self):
        """Toggle between appearance modes while keeping the current color theme."""
        try:
            with open(self.theme_file, "r") as f:
                theme = json.load(f)
                current_mode = theme.get("appearance_mode", "dark")
                color_theme = theme.get("color_theme", "blue")
            new_mode = {"dark": "light", "light": "system", "system": "dark"}.get(current_mode, "dark")
            self.update_theme(new_mode, color_theme)
        except FileNotFoundError:
            self.update_theme("light", "blue")

    def update_stock_overview(self):
        """Update stock overview display – retries until login data is ready."""
        # ---- 1. Wait for login data ----
        if not getattr(self, 'username', None) or not getattr(self, 'role', None):
            self.stock_label.configure(text="Stock Overview: Logging in…")
            self.after(200, self.update_stock_overview)   # try again
            return

        # ---- 2. Wait for ReportManager ----
        if not hasattr(self, 'report_manager') or self.report_manager is None:
            self.stock_label.configure(text="Stock Overview: Initializing…")
            self.after(200, self.update_stock_overview)
            return

        # ---- 3. Call ReportManager  ----
        try:
            stock_data    = self.report_manager.stock_summary()
            overview_data = self.report_manager.overview()

            # Safe extraction
            total_brought   = stock_data.get('total_brought', 0)
            total_issued    = stock_data.get('total_issued', 0)
            current_balance = stock_data.get('current_balance', 0)
            last_updated    = stock_data.get('last_updated', 'N/A')

            total_required      = overview_data.get('total_required', 0)
            total_brought_stu   = overview_data.get('total_brought', 0)
            collection_pct      = overview_data.get('collection_percentage', 0.0)

            text = (
                f"Total Brought: {total_brought} | "
                f"Total Issued: {total_issued} | "
                f"Current Balance: {current_balance} | "
                f"Last Updated: {last_updated} | "
                f"Required: {total_required} | "
                f"Brought: {total_brought_stu} | "
                f"Collection: {collection_pct:.2f}%"
            )
            self.stock_label.configure(text=text)
            self.log_feedback("Updated stock overview")
        except Exception as e:
            error_msg = f"Error updating stock overview: {e}"
            self.stock_label.configure(text="Stock Overview: Error")
            self.log_feedback(error_msg)
            logger.error(error_msg)
        

    def show_tab(self, tab_name):
        """Show the selected tab with animation."""
        if tab_name in self.tabs:
            self.tabview.set(tab_name)
            for index, (name, btn) in enumerate(self.nav_buttons):
                if name == tab_name:
                    self.current_button_index = index
                    self.update_button_focus()
            self.tabview._segmented_button.configure(fg_color="#2B6CB0")
            self.after(100, lambda: self.tabview._segmented_button.configure(fg_color="#1E4E79"))
            self.animate_tab(tab_name)
            if hasattr(self.tabs[tab_name], 'refresh_data'):
                try:
                    self.tabs[tab_name].refresh_data()
                    self.log_feedback(f"Refreshed data for {tab_name} tab")
                    self.update_idletasks()
                except Exception as e:
                    error_msg = f"Failed to refresh {tab_name} tab: {str(e)}"
                    self.log_feedback(error_msg)
                    logger.error(error_msg)
            self.log_feedback(f"Switched to {tab_name} tab")
        else:
            error_msg = f"Cannot switch to tab {tab_name}: Tab not initialized"
            self.log_feedback(error_msg)
            logger.warning(error_msg)

    def quit_app(self):
        """Exit the application with confirmation."""
        if messagebox.askyesno("Exit", "Are you sure you want to exit?", parent=self):
            self.log_feedback(f"User {self.username} exited application")
            logger.info(f"User {self.username} exited application")
            self.quit()

    def open_form_window(self, title: str, form_class, *args, **kwargs):
        """Open a form window with support for *args and **kwargs, backward compatible."""
        try:
            # Try: form_class(parent, *args, **kwargs)
            form_window = form_class(self, *args, **kwargs)
        except TypeError as e:
            # Fallback 1: some forms expect title as 2nd arg
            if "title" in str(e).lower():
                try:
                    form_window = form_class(self, title, *args, **kwargs)
                except Exception as e2:
                    logger.error(f"Failed to open {title}: {e2}")
                    raise
            # Fallback 2: try **kwargs only (current behavior)
            else:
                try:
                    form_window = form_class(self, **kwargs)
                except Exception as e3:
                    logger.error(f"Failed to open {title}: {e3}")
                    raise
        except Exception as e:
            logger.error(f"Unexpected error opening {title}: {e}")
            raise

        # --- Common setup ---
        form_window.title(title)
        form_window.geometry("900x750")
        form_window.configure(fg_color="#1E1E1E")
        form_window.lift()
        form_window.grab_set()

        # Center window
        form_window.update_idletasks()
        width = form_window.winfo_width()
        height = form_window.winfo_height()
        x = (form_window.winfo_screenwidth() // 2) - (width // 2)
        y = (form_window.winfo_screenheight() // 2) - (height // 2)
        form_window.geometry(f"{width}x{height}+{x}+{y}")

        logger.info(f"Opened form window: {title}")
        return form_window

if __name__ == "__main__":
    try:
        app = MainWindow()
        app.mainloop()
    except Exception as e:
        logger.error(f"Application failed to start: {str(e)}")
        raise