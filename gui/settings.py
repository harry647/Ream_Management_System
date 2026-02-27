import customtkinter as ctk
from tkinter import messagebox
import sqlite3
import json
import logging
from datetime import datetime
import os
from modules.db_setup import get_logs_dir, get_config_dir

# Configure logging
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'settings.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, db_path, username, role, log_feedback_callback, icons, update_title_callback, update_theme_callback):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("520x700")  
        self.resizable(True, True)
        self.minsize(420, 550)
        self.db_path = db_path
        self.username = username
        self.role = role
        self.log_feedback = log_feedback_callback
        self.icons = icons
        self.update_title_callback = update_title_callback
        self.update_theme_callback = update_theme_callback
        self.theme_file = os.path.join(get_config_dir(), "theme.json")
        self.configure(fg_color="#1E1E1E")
        logger.info("Initializing SettingsWindow")

        # Center window
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self.grab_set()

        # === SCROLLABLE CANVAS ===
        self.canvas = ctk.CTkCanvas(self, bg="#1E1E1E", highlightthickness=0)
        self.scrollbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview)
        self.scrollable_frame = ctk.CTkFrame(self.canvas, fg_color="#1E1E1E")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=20)
        self.scrollbar.pack(side="right", fill="y", padx=(0, 20), pady=20)

        # === BIND MOUSE WHEEL TO CANVAS ONLY  ===
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)   # Windows/Mac
        self.canvas.bind("<Button-4>", self._on_mousewheel)     # Linux scroll up
        self.canvas.bind("<Button-5>", self._on_mousewheel)     # Linux scroll down

        # === MAIN CONTENT FRAME ===
        self.main_frame = ctk.CTkFrame(self.scrollable_frame, corner_radius=15, fg_color="#2B2B2B")
        self.main_frame.pack(pady=20, padx=25, fill="both", expand=False)

        # Title
        ctk.CTkLabel(self.main_frame, text="Application Settings", font=("Arial", 18, "bold"), text_color="#FFFFFF").pack(pady=10)

        # School Name
        ctk.CTkLabel(self.main_frame, text="School Name", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.school_name_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Enter school name", font=("Arial", 12), height=35)
        self.school_name_entry.pack(pady=5, padx=20, fill="x")
        self.school_name_entry.bind("<KeyRelease>", self.preview_school_name)

        # Current Term
        ctk.CTkLabel(self.main_frame, text="Current Term", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.current_term_combo = ctk.CTkComboBox(self.main_frame, values=["Term 1", "Term 2", "Term 3"], state="readonly", font=("Arial", 12), height=35)
        self.current_term_combo.pack(pady=5, padx=20, fill="x")

        # Term Year
        ctk.CTkLabel(self.main_frame, text="Term Year", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.term_year_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Enter year (e.g., 2025)", font=("Arial", 12), height=35)
        self.term_year_entry.pack(pady=5, padx=20, fill="x")

        # Minimum Stock Alert
        ctk.CTkLabel(self.main_frame, text="Minimum Stock Alert", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.min_stock_alert_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Enter minimum stock level", font=("Arial", 12), height=35)
        self.min_stock_alert_entry.pack(pady=5, padx=20, fill="x")

        # Total Reams Required
        ctk.CTkLabel(self.main_frame, text="Total Reams Required (Entire Academic Duration)", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.total_required_entry = ctk.CTkEntry(self.main_frame, placeholder_text="Enter total reams required", font=("Arial", 12), height=35)
        self.total_required_entry.pack(pady=5, padx=20, fill="x")

        # Date/Time Format
        ctk.CTkLabel(self.main_frame, text="Date/Time Format", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.datetime_format_combo = ctk.CTkComboBox(
            self.main_frame,
            values=[
                "%Y-%m-%d",
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%d-%b-%Y"
            ],
            state="readonly",
            font=("Arial", 12),
            height=35
        )
        self.datetime_format_combo.pack(pady=5, padx=20, fill="x")

        # Appearance Mode
        ctk.CTkLabel(self.main_frame, text="Appearance Mode", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.appearance_mode_combo = ctk.CTkComboBox(
            self.main_frame,
            values=["Light", "Dark", "System"],
            state="readonly",
            font=("Arial", 12),
            height=35
        )
        self.appearance_mode_combo.pack(pady=5, padx=20, fill="x")
        self.appearance_mode_combo.bind("<<ComboboxSelected>>", self.preview_theme)

        # Color Theme
        ctk.CTkLabel(self.main_frame, text="Color Theme", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(15, 2), anchor="w", padx=20)
        self.color_theme_combo = ctk.CTkComboBox(
            self.main_frame,
            values=["Blue", "Green", "Dark-Blue"],
            state="readonly",
            font=("Arial", 12),
            height=35
        )
        self.color_theme_combo.pack(pady=5, padx=20, fill="x")
        self.color_theme_combo.bind("<<ComboboxSelected>>", self.preview_theme)

        # Reams Required Per Form
        ctk.CTkLabel(self.main_frame, text="Reams Required Per Form", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=(20, 5), anchor="w", padx=20)
        self.reams_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B")
        self.reams_frame.pack(pady=5, padx=20, fill="x")
        self.ream_entries = {}
        forms = ["Form 1", "Form 2", "Form 3", "Form 4", "Grade 10", "Grade 11", "Grade 12"]
        for form in forms:
            frame = ctk.CTkFrame(self.reams_frame, fg_color="#2B2B2B")
            frame.pack(pady=2, fill="x")
            ctk.CTkLabel(frame, text=form, font=("Arial", 12), text_color="#A0AEC0", width=100).pack(side="left", padx=5)
            entry = ctk.CTkEntry(frame, placeholder_text=f"Reams for {form}", font=("Arial", 12), height=30)
            entry.pack(side="left", fill="x", expand=True, padx=5)
            self.ream_entries[form] = entry

        # Buttons (Fixed at bottom)
        button_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="#1E1E1E")
        button_frame.pack(pady=20, padx=25, fill="x")

        save_button = ctk.CTkButton(
            button_frame,
            text="Save",
            image=self.icons.get('save', None),
            compound="left",
            command=self.save_settings,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        save_button.pack(side="left", padx=8, fill="x", expand=True)

        reset_button = ctk.CTkButton(
            button_frame,
            text="Reset to Defaults",
            image=self.icons.get('refresh', None),
            compound="left",
            command=self.reset_to_defaults,
            fg_color="#D97706",
            hover_color="#B45309",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        reset_button.pack(side="left", padx=8, fill="x", expand=True)

        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            image=self.icons.get('cancel', None),
            compound="left",
            command=self.destroy,
            fg_color="#C53030",
            hover_color="#9B2A2A",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        cancel_button.pack(side="left", padx=8, fill="x", expand=True)

        # Load settings
        self.after(100, self.load_settings) 

        # Keyboard bindings
        self.bind("<Return>", lambda e: self.save_settings())
        self.bind("<Escape>", lambda e: self.destroy())

        logger.info("SettingsWindow with scroll initialized")

    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling."""
        if self.canvas.winfo_exists() == 0:
            return
        try:
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except:
            pass

        def destroy(self):
            """Safely destroy and unbind."""
            try:
                self.canvas.unbind("<MouseWheel>")
                self.canvas.unbind("<Button-4>")
                self.canvas.unbind("<Button-5>")
            except:
                pass
            super().destroy()

    def load_settings(self):
        """Load current settings from the database and theme.json."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM settings ORDER BY setting_id DESC LIMIT 1")
            settings = cursor.fetchone()
            if settings:
                self.school_name_entry.insert(0, settings['school_name'])
                self.current_term_combo.set(settings['current_term'])
                self.term_year_entry.insert(0, str(settings['term_year']))
                self.min_stock_alert_entry.insert(0, str(settings['min_stock_alert']))
                self.total_required_entry.insert(0, str(settings['total_required']))
                self.datetime_format_combo.set(settings['datetime_format'])
                ream_required = json.loads(settings['ream_required_per_form'])
                for form, entry in self.ream_entries.items():
                    entry.insert(0, str(ream_required.get(form, 0)))
                self.update_title_callback(settings['school_name'])
            else:
                self.log_feedback("No settings found, using defaults")
                logger.warning("No settings found in database")
            conn.close()

            try:
                with open(self.theme_file, "r") as f:
                    theme = json.load(f)
                self.appearance_mode_combo.set(theme.get("appearance_mode", "dark").capitalize())
                self.color_theme_combo.set(theme.get("color_theme", "blue").capitalize())
            except FileNotFoundError:
                self.appearance_mode_combo.set("Dark")
                self.color_theme_combo.set("Blue")
                logger.warning("theme.json not found, defaulting to Dark/Blue")
        except Exception as e:
            self.log_feedback(f"Error loading settings: {str(e)}")
            logger.error(f"Error loading settings: {str(e)}")
            messagebox.showerror("Error", f"Failed to load settings: {str(e)}", parent=self)

    

    def preview_school_name(self, event=None):
        """Preview the school name by updating the main window title."""
        school_name = self.school_name_entry.get().strip()
        if school_name:
            self.update_title_callback(school_name)
        else:
            self.update_title_callback("Ream Management System")

    def preview_theme(self, event=None):
        """Preview the theme by applying it to the main window."""
        appearance_mode = self.appearance_mode_combo.get().lower()
        color_theme = self.color_theme_combo.get().lower()
        self.update_theme_callback(appearance_mode, color_theme)
        self.log_feedback(f"Previewing {appearance_mode}/{color_theme} theme")
        logger.debug(f"Previewing {appearance_mode}/{color_theme} theme")

    def save_settings(self):
        """Save settings to the database and theme.json."""
        try:
            # Validate inputs
            school_name = self.school_name_entry.get().strip()
            if not school_name:
                raise ValueError("School name cannot be empty")
            
            term_year = self.term_year_entry.get().strip()
            if not term_year.isdigit() or int(term_year) < 2000:
                raise ValueError("Term year must be a valid year (e.g., 2025)")
            term_year = int(term_year)
            
            min_stock_alert = self.min_stock_alert_entry.get().strip()
            if not min_stock_alert.isdigit() or int(min_stock_alert) < 0:
                raise ValueError("Minimum stock alert must be a non-negative number")
            min_stock_alert = int(min_stock_alert)
            
            total_required = self.total_required_entry.get().strip()
            if not total_required.isdigit() or int(total_required) < 0:
                raise ValueError("Total reams required must be a non-negative number")
            total_required = int(total_required)
            
            ream_required = {}
            for form, entry in self.ream_entries.items():
                value = entry.get().strip()
                if not value.isdigit() or int(value) < 0:
                    raise ValueError(f"Reams required for {form} must be a non-negative number")
                ream_required[form] = int(value)
            ream_required_json = json.dumps(ream_required)
            
            datetime_format = self.datetime_format_combo.get()
            if not datetime_format:
                raise ValueError("Date/Time format cannot be empty")

            appearance_mode = self.appearance_mode_combo.get().lower()
            if appearance_mode not in ["light", "dark", "system"]:
                raise ValueError("Invalid appearance mode selected")
            
            color_theme = self.color_theme_combo.get().lower()
            if color_theme not in ["blue", "green", "dark-blue"]:
                raise ValueError("Invalid color theme selected")

            # Update database
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE settings
                SET school_name = ?, current_term = ?, term_year = ?, min_stock_alert = ?,
                    ream_required_per_form = ?, total_required = ?, datetime_format = ?, updated_at = ?
                WHERE setting_id = (SELECT MAX(setting_id) FROM settings)
            """, (
                school_name,
                self.current_term_combo.get(),
                term_year,
                min_stock_alert,
                ream_required_json,
                total_required,
                datetime_format,
                datetime.now().strftime("%Y-%m-%d")
            ))
            
            # Log to audit_log
            cursor.execute("""
                INSERT INTO audit_log (table_name, operation, record_id, user, details)
                VALUES (?, ?, ?, ?, ?)
            """, (
                'settings',
                'UPDATE',
                cursor.execute("SELECT MAX(setting_id) FROM settings").fetchone()[0],
                self.username,
                f"Updated settings: school_name={school_name}, term={self.current_term_combo.get()}, year={term_year}, "
                f"min_stock={min_stock_alert}, total_required={total_required}, "
                f"ream_required_per_form={ream_required_json}, datetime_format={datetime_format}, "
                f"appearance_mode={appearance_mode}, color_theme={color_theme}"
            ))
            conn.commit()
            conn.close()
            
            # Save theme to theme.json
            os.makedirs("config", exist_ok=True)
            with open(self.theme_file, "w") as f:
                json.dump({"appearance_mode": appearance_mode, "color_theme": color_theme}, f)
            
            # Apply theme and update title
            self.update_theme_callback(appearance_mode, color_theme)
            self.update_title_callback(school_name)
            
            self.log_feedback("Settings saved successfully")
            logger.info(f"Settings updated by {self.username}")
            messagebox.showinfo("Success", "Settings saved successfully", parent=self)
            self.destroy()
            
        except Exception as e:
            self.log_feedback(f"Error saving settings: {str(e)}")
            logger.error(f"Error saving settings: {str(e)}")
            messagebox.showerror("Error", f"Failed to save settings: {str(e)}", parent=self)

    def reset_to_defaults(self):
        """Reset settings to default values."""
        if messagebox.askyesno("Reset Settings", "Are you sure you want to reset settings to defaults?", parent=self):
            try:
                default_settings = {
                    'school_name': 'Bar Union Secondary',
                    'current_term': 'Term 1',
                    'term_year': datetime.now().year,
                    'min_stock_alert': 10,
                    'total_required': 8,
                    'ream_required_per_form': {
                        'Form 1': 2, 'Form 2': 2, 'Form 3': 2, 'Form 4': 2,
                        'Grade 10': 2, 'Grade 11': 2, 'Grade 12': 2
                    },
                    'datetime_format': '%Y-%m-%d',
                    'appearance_mode': 'dark',
                    'color_theme': 'blue'
                }
                
                # Update database
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE settings
                    SET school_name = ?, current_term = ?, term_year = ?, min_stock_alert = ?,
                        ream_required_per_form = ?, total_required = ?, datetime_format = ?, updated_at = ?
                    WHERE setting_id = (SELECT MAX(setting_id) FROM settings)
                """, (
                    default_settings['school_name'],
                    default_settings['current_term'],
                    default_settings['term_year'],
                    default_settings['min_stock_alert'],
                    json.dumps(default_settings['ream_required_per_form']),
                    default_settings['total_required'],
                    default_settings['datetime_format'],
                    datetime.now().strftime("%Y-%m-%d")
                ))
                
                # Log to audit_log
                cursor.execute("""
                    INSERT INTO audit_log (table_name, operation, record_id, user, details)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    'settings',
                    'UPDATE',
                    cursor.execute("SELECT MAX(setting_id) FROM settings").fetchone()[0],
                    self.username,
                    "Reset settings to defaults"
                ))
                
                conn.commit()
                conn.close()
                
                # Save default theme to theme.json
                os.makedirs("config", exist_ok=True)
                with open(self.theme_file, "w") as f:
                    json.dump({
                        "appearance_mode": default_settings['appearance_mode'],
                        "color_theme": default_settings['color_theme']
                    }, f)
                
                # Update UI
                self.school_name_entry.delete(0, "end")
                self.school_name_entry.insert(0, default_settings['school_name'])
                self.current_term_combo.set(default_settings['current_term'])
                self.term_year_entry.delete(0, "end")
                self.term_year_entry.insert(0, str(default_settings['term_year']))
                self.min_stock_alert_entry.delete(0, "end")
                self.min_stock_alert_entry.insert(0, str(default_settings['min_stock_alert']))
                self.total_required_entry.delete(0, "end")
                self.total_required_entry.insert(0, str(default_settings['total_required']))
                self.datetime_format_combo.set(default_settings['datetime_format'])
                self.appearance_mode_combo.set(default_settings['appearance_mode'].capitalize())
                self.color_theme_combo.set(default_settings['color_theme'].capitalize())
                for form, entry in self.ream_entries.items():
                    entry.delete(0, "end")
                    entry.insert(0, str(default_settings['ream_required_per_form'].get(form, 0)))
                
                # Apply default theme and update title
                self.update_theme_callback(default_settings['appearance_mode'], default_settings['color_theme'])
                self.update_title_callback(default_settings['school_name'])
                
                self.log_feedback("Settings reset to defaults")
                logger.info(f"Settings reset to defaults by {self.username}")
                messagebox.showinfo("Success", "Settings reset to defaults", parent=self)
                
            except Exception as e:
                self.log_feedback(f"Error resetting settings: {str(e)}")
                logger.error(f"Error resetting settings: {str(e)}")
                messagebox.showerror("Error", f"Failed to reset settings: {str(e)}", parent=self)