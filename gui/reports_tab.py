import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox 
from tkinter import simpledialog
import tkinter as tk
from modules.report_manager import ReportManager
from modules.student_manager import StudentManager
from gui.utils import show_error, show_info
from reports.report_export import ReportExporter
from modules.db_setup import get_logs_dir
import os
import subprocess
import sys
from io import BytesIO
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Image as RLImage, Spacer, Paragraph, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
import logging
import re
from typing import List, Dict, Optional
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
import threading
from PIL import Image
from datetime import datetime
from tkcalendar import Calendar

# Platform-specific printing imports (Windows only)
if sys.platform == 'win32':
    try:
import win32print
import win32ui
HAS_WIN32_PRINTING = True
    except ImportError:
        HAS_WIN32_PRINTING = False
else:
    HAS_WIN32_PRINTING = False

# Configure logging
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'reports_tab.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ReportWindow(ctk.CTkToplevel):
    def __init__(self, parent, title: str, columns: List[str], data: List, report_type: str, report_mgr, username: Optional[str], role: Optional[str], icons, column_widths: Dict[str, int] = None, log_feedback=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x400")
        self.configure(fg_color="#1E1E1E")
        self.icons = icons
        self.log_feedback = log_feedback or (lambda x: None)
        self.report_type = report_type
        self.report_mgr = report_mgr
        self.username = username
        self.role = role
        self.data = data
        self.exporter = ReportExporter(report_mgr)
        logger.info(f"Initializing ReportWindow: {title}")

        # Table frame
        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col, command=lambda c=col: self.sort_table(tree, c))
            tree.column(col, width=column_widths.get(col, 100) if column_widths else 100)
        scrollbar = ctk.CTkScrollbar(table_frame, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        for row in data:
            if isinstance(row, dict):
                values = [row.get(col.lower().replace(" ", "_"), "") for col in columns]
            else:
                # row is a list/tuple in correct column order
                values = list(row)[:len(columns)]
            tree.insert("", "end", values=values)

        # Button frame
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        button_frame.pack(pady=10, padx=10, fill="x")

        # Download PDF button
        pdf_button = ctk.CTkButton(
            button_frame,
            text="Download as PDF",
            image=self.icons.get('export', None),
            compound="left",
            command=self.download_pdf,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        pdf_button.pack(side="left", padx=5, fill="x", expand=True)

        # Download Excel button
        excel_button = ctk.CTkButton(
            button_frame,
            text="Download as Excel",
            image=self.icons.get('export', None),
            compound="left",
            command=self.download_excel,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        excel_button.pack(side="left", padx=5, fill="x", expand=True)

        # Print Button
        print_icon = ctk.CTkImage(light_image=Image.open("icons/printer.png"), size=(16, 16))
        print_button = ctk.CTkButton(
            button_frame,
            text="Print",
            image=print_icon,
            compound="left",
            command=self.print_report,
            fg_color="#16A34A",
            hover_color="#15803D",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        print_button.pack(side="left", padx=5, fill="x", expand=True)

        # Close button
        close_button = ctk.CTkButton(
            button_frame,
            text="Close",
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
        close_button.pack(side="left", padx=5, fill="x", expand=True)
        logger.debug("Buttons added to ReportWindow")

        # Bind Enter and Escape keys to close
        self.bind("<Return>", lambda event: self.destroy())
        self.bind("<Escape>", lambda event: self.destroy())
        logger.debug(f"Populated ReportWindow with {len(data)} records")

    def download_pdf(self):
        """Download or preview the current report as a PDF."""
        if self.role not in {'staff', 'admin'}:
            show_error(self, "Permission denied: Staff or Admin role required")
            self.log_feedback("Download PDF failed: Permission denied")
            return
        try:
            success = self.exporter.export_to_pdf(
                self.report_type, "", self.username, self.role, data=self.data, preview=True, parent=self
            )
            if success is None:
                self.log_feedback("PDF preview displayed")
                logger.info(f"Previewed {self.report_type} report")
            elif success:
                self.log_feedback(f"Report exported to PDF")
                logger.info(f"Exported {self.report_type} report")
        except Exception as e:
            show_error(self, f"Error exporting to PDF: {e}")
            self.log_feedback(f"Error exporting to PDF: {e}")
            logger.error(f"Error exporting to PDF: {e}")

    def download_excel(self):
        """Download the current report as an Excel file."""
        if self.role not in {'staff', 'admin'}:
            show_error(self, "Permission denied: Staff or Admin role required")
            self.log_feedback("Download Excel failed: Permission denied")
            return
        try:
            file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
            if not file_path:
                self.log_feedback("Download Excel cancelled: No file selected")
                return
            self.exporter.export_to_excel(self.report_type, file_path, self.username, self.role, data=self.data)
            show_info(self, f"Report exported to {file_path}")
            self.log_feedback(f"Report exported to {file_path} as Excel")
            logger.info(f"Report {self.report_type} exported to Excel at {file_path}")
        except Exception as e:
            show_error(self, f"Error exporting to Excel: {e}")
            self.log_feedback(f"Error exporting to Excel: {e}")
            logger.error(f"Error exporting to Excel: {e}")

    def print_report(self):
        """Print the report directly to printer."""
        if self.role not in {'staff', 'admin'}:
            show_error(self, "Permission denied: Staff or Admin role required")
            self.log_feedback("Print failed: Permission denied")
            return

        try:
            # 1. Select printer
            printer_name = self._select_printer()
            if not printer_name:
                return

            # 2. Generate PDF in memory
            buffer = BytesIO()
            success = self.exporter.export_to_pdf(
                report_type=self.report_type,
                file_path=None,
                buffer=buffer,
                username=self.username,
                role=self.role,
                data=self.data,
                preview=False,
                parent=self
            )
            if not success:
                show_error(self, "Failed to generate report for printing")
                return

            buffer.seek(0)
            self._send_to_printer(buffer, printer_name)
            show_info(self, f"Report sent to printer: {printer_name}")
            self.log_feedback(f"Printed {self.report_type} to {printer_name}")

        except Exception as e:
            show_error(self, f"Print error: {e}")
            logger.error(f"Print error: {e}", exc_info=True)


    def _select_printer(self):
        """Show printer selection dialog."""
        try:
            if HAS_WIN32_PRINTING:
                # ----- Windows -----
                printers = [p[2] for p in win32print.EnumPrinters(2)]
                if not printers:
                    show_error(self, "No printers found")
                    return None

                printer = simpledialog.askstring(
                    "Select Printer",
                    "Available printers:\n" + "\n".join(printers) + "\n\nEnter printer name:",
                    parent=self
                )
                if printer and printer in printers:
                    return printer
                elif printer:
                    show_error(self, f"Printer '{printer}' not found")
                return None
            else:
                # ----- macOS / Linux -----
                result = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, check=True)
                printers = []
                for line in result.stdout.splitlines():
                    if "printer" in line.lower():
                        parts = line.split()
                        if len(parts) > 1:
                            printers.append(parts[1])
                if not printers:
                    show_error(self, "No printers found (lpstat)")
                    return None

                printer = simpledialog.askstring(
                    "Select Printer",
                    "Available printers:\n" + "\n".join(printers) + "\n\nEnter printer name:",
                    parent=self
                )
                return printer if printer in printers else None

        except Exception as e:
            logger.error(f"Printer detection failed: {e}")
            show_error(self, "Printer selection not available on this platform")
            return None

    def _send_to_printer(self, pdf_buffer: BytesIO, printer_name: str):
        """Send PDF buffer to printer using OS-native method."""
        temp_pdf_path = None
        try:
            # --- Windows: Use ShellExecute ---
            if sys.platform == 'win32' and HAS_WIN32_PRINTING:
                import tempfile
                import win32api

                # Save buffer to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(pdf_buffer.getvalue())
                    temp_pdf_path = tmp.name

                # Send to printer
                win32api.ShellExecute(
                    0,
                    "print",
                    temp_pdf_path,
                    f'/d:"{printer_name}"',
                    ".",
                    0
                )
                logger.info(f"PDF sent to printer via ShellExecute: {printer_name}")

            # --- macOS / Linux: Use lpr ---
            else:
                import subprocess
                proc = subprocess.Popen(
                    ["lpr", "-P", printer_name],
                    stdin=subprocess.PIPE
                )
                proc.communicate(pdf_buffer.getvalue())
                if proc.returncode != 0:
                    raise RuntimeError("lpr command failed")
                logger.info(f"PDF sent via lpr to: {printer_name}")

        except Exception as e:
            logger.error(f"Print failed: {e}")
            show_error(self, f"Failed to print: {e}")
        finally:
            # Clean up temp file
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except:
                    pass

    def sort_table(self, tree: ttk.Treeview, col: str):
        """Sort the given Treeview table by the specified column."""
        try:
            records = [(tree.set(item, col), item) for item in tree.get_children()]
            if hasattr(self, 'sort_column_name') and self.sort_column_name == col:
                self.sort_reverse = not getattr(self, 'sort_reverse', False)
            else:
                self.sort_reverse = False
                self.sort_column_name = col

            def convert(value):
                try:
                    return float(value.replace("%", "")) if col in ["Percentage", "Collection %"] else float(value) if col in ["Required", "Brought", "Remaining", "Surplus", "Total Students", "Total Brought", "Total Required", "Total Issued", "Total Entries", "Total Reams"] else value.lower()
                except (ValueError, AttributeError):
                    return value

            records.sort(key=lambda x: convert(x[0]), reverse=self.sort_reverse)

            for index, (value, item) in enumerate(records):
                tree.move(item, "", index)

            for column in tree["columns"]:
                tree.heading(column, text=column)
            arrow = " ↓" if not self.sort_reverse else " ↑"
            tree.heading(col, text=col + arrow)
            self.log_feedback(f"Sorted report table by {col} {'descending' if self.sort_reverse else 'ascending'}")
        except Exception as e:
            show_error(self, f"Error sorting table: {e}")
            self.log_feedback(f"Error sorting table by {col}: {e}")
            logger.error(f"Error sorting table by {col}: {e}")




class DashboardWindow(ctk.CTkToplevel):
    def __init__(self, parent, title: str, report_mgr, start_date: Optional[str],
                 end_date: Optional[str], username: str, role: str, icons,
                 log_feedback=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("950x720")
        self.configure(fg_color="#1E1E1E")
        self.report_mgr = report_mgr
        self.start_date = start_date
        self.end_date = end_date
        self.username = username
        self.role = role
        self.icons = icons
        self.log_feedback = log_feedback or (lambda x: None)
        self.exporter = ReportExporter(report_mgr)
        self.sort_column_name = None
        self.sort_reverse = False
        logger.info("Initializing DashboardWindow")

        # --------------------------------------------------------------
        # 1. SCROLLABLE CANVAS (entire window scrolls)
        # --------------------------------------------------------------
        canvas = ctk.CTkCanvas(self, highlightthickness=0, bg="#1E1E1E")
        canvas.pack(side="left", fill="both", expand=True)

        v_scroll = ctk.CTkScrollbar(self, command=canvas.yview, fg_color="#2B2B2B")
        v_scroll.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=v_scroll.set)

        inner_frame = ctk.CTkFrame(canvas, fg_color="#1E1E1E")
        inner_id = canvas.create_window((0, 0), window=inner_frame, anchor="nw")

        def _on_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(inner_id, width=event.width if event else self.winfo_width())
        inner_frame.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        # --------------------------------------------------------------
        # 2. HELPER: Section with Treeview + Scrollbar
        # --------------------------------------------------------------
        def create_section(parent, title_text, columns, widths):
            frame = ctk.CTkFrame(parent, fg_color="#2B2B2B", corner_radius=12)
            frame.pack(fill="x", padx=15, pady=10)

            ctk.CTkLabel(frame, text=title_text, font=("Arial", 15, "bold"),
                         text_color="#FFFFFF").pack(pady=(8, 4))

            tree = ttk.Treeview(frame, columns=columns, show="headings", height=6)
            for col, width in zip(columns, widths):
                tree.heading(col, text=col, command=lambda c=col: self.sort_table(tree, c))
                tree.column(col, width=width, anchor="center")
            tree.pack(side="left", fill="both", expand=True)

            sb = ctk.CTkScrollbar(frame, command=tree.yview, fg_color="#3A3A3A")
            sb.pack(side="right", fill="y")
            tree.configure(yscrollcommand=sb.set)
            return tree, frame

        # --------------------------------------------------------------
        # 3. OVERVIEW SECTION
        # --------------------------------------------------------------
        try:
            raw = self.report_mgr.overview(self.start_date, self.end_date, self.username, self.role)
            if isinstance(raw, tuple):
                keys = ['total_required', 'total_brought', 'remaining',
                        'collection_percentage', 'total_issued', 'total_stock']
                overview_data = dict(zip(keys, raw))
            else:
                overview_data = raw or {}
        except Exception as e:
            logger.error(f"Overview failed: {e}")
            overview_data = {}

        overview_records = [
            {"Metric": "Total Required", "Value": str(overview_data.get('total_required', 0))},
            {"Metric": "Total Brought",  "Value": str(overview_data.get('total_brought', 0))},
            {"Metric": "Remaining",      "Value": str(overview_data.get('remaining', 0))},
            {"Metric": "Collection %",   "Value": f"{overview_data.get('collection_percentage', 0):.2f}%"},
            {"Metric": "Total Issued",   "Value": str(overview_data.get('total_issued', 0))},
            {"Metric": "Total Stock",    "Value": str(overview_data.get('total_stock', 0))}
        ]

        overview_tree, overview_frame = create_section(
            inner_frame, "Overview", ("Metric", "Value"), [320, 180]
        )
        for rec in overview_records:
            overview_tree.insert("", "end", values=(rec["Metric"], rec["Value"]))

        # Export buttons
        btn_frame = ctk.CTkFrame(overview_frame, fg_color="#2B2B2B")
        ctk.CTkButton(btn_frame, text="PDF", image=self.icons.get('export'),
                      command=lambda: self.download_pdf("overview", overview_records),
                      fg_color="#2B6CB0", hover_color="#1E4E79", width=120).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Excel", image=self.icons.get('export'),
                      command=lambda: self.download_excel("overview", overview_records),
                      fg_color="#2B6CB0", hover_color="#1E4E79", width=120).pack(side="left", padx=5)
        btn_frame.pack(pady=6, fill="x")

        # --------------------------------------------------------------
        # 4. CLASS SUMMARY (Top 3)
        # --------------------------------------------------------------
        class_data = self.report_mgr.class_summary(self.username, self.role)[:3]
        class_tree, _ = create_section(
            inner_frame, "Class Summary (Top 3 Forms)",
            ("Form", "Students", "Brought", "Required", "Remaining", "%"),
            [100, 110, 110, 110, 110, 90]
        )
        for r in class_data:
            class_tree.insert("", "end", values=(
                r['form'], r['total_students'], r['total_brought'],
                r['total_required'], r['remaining'], f"{r['percentage']:.2f}%"
            ))

        # --------------------------------------------------------------
        # 5. TOP 5 DEFAULTERS
        # --------------------------------------------------------------
        defaulters_data = self.report_mgr.defaulters_report(
            self.start_date, self.end_date, None, None, self.username, self.role
        )[:5]
        def_tree, _ = create_section(
            inner_frame, "Top 5 Defaulters",
            ("Adm No", "Name", "Form", "Stream", "Remaining"),
            [100, 160, 80, 80, 100]
        )
        for r in defaulters_data:
            def_tree.insert("", "end", values=(
                r['admission_no'], r['name'], r['form'],
                r['stream'] or '—', r['remaining']
            ))

        # --------------------------------------------------------------
        # 6. ISSUED SUMMARY (Top 3 Depts)
        # --------------------------------------------------------------
        issued_data = self.report_mgr.issued_summary(
            self.start_date, self.end_date, None, self.username, self.role
        )[:3]
        issued_tree, _ = create_section(
            inner_frame, "Issued Summary (Top 3 Departments)",
            ("Department", "Total Issued"),
            [250, 130]
        )
        for r in issued_data:
            issued_tree.insert("", "end", values=(r['department'], r['total_issued']))

        # --------------------------------------------------------------
        # 7. CLOSE BUTTON
        # --------------------------------------------------------------
        close_btn = ctk.CTkButton(
            inner_frame, text="Close", image=self.icons.get('cancel'),
            command=self.destroy, fg_color="#C53030", hover_color="#9B2A2A",
            font=("Arial", 13, "bold"), height=40, corner_radius=10
        )
        close_btn.pack(pady=15)

        # Keyboard shortcuts
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self.destroy())

        # Final log
        self.log_feedback(
            f"Dashboard loaded: {len(class_data)} classes | "
            f"{len(defaulters_data)} defaulters | {len(issued_data)} depts"
        )

    # ------------------------------------------------------------------
    # SORTING
    # ------------------------------------------------------------------
    def sort_table(self, tree: ttk.Treeview, col: str):
        try:
            data = [(tree.set(item, col), item) for item in tree.get_children()]
            reverse = (self.sort_column_name == col) and not self.sort_reverse
            self.sort_column_name = col
            self.sort_reverse = reverse

            def convert(val):
                val = val.strip()
                if col in ["Percentage", "Collection %"]:
                    return float(val.rstrip('%'))
                try:
                    return float(val)
                except:
                    return val.lower()

            data.sort(key=lambda x: convert(x[0]), reverse=reverse)

            for idx, (_, item) in enumerate(data):
                tree.move(item, "", idx)

            # Reset headers
            for c in tree["columns"]:
                tree.heading(c, text=c)
            arrow = " (down)" if reverse else " (up)"
            tree.heading(col, text=col + arrow)

            self.log_feedback(f"Sorted by {col} {'desc' if reverse else 'asc'}")
        except Exception as e:
            logger.error(f"Sort error: {e}")

    # ------------------------------------------------------------------
    # EXPORT: PDF
    # ------------------------------------------------------------------
    def download_pdf(self, report_type: str, data: List[Dict]):
        if self.role not in {'staff', 'admin'}:
            self.log_feedback("PDF export: Access denied")
            return
        try:
            result = self.exporter.export_to_pdf(
                report_type, "", self.username, self.role,
                data=data, preview=True, parent=self
            )
            if result is None:
                self.log_feedback(f"PDF preview: {report_type}")
            else:
                self.log_feedback("PDF exported")
        except Exception as e:
            self.log_feedback(f"PDF error: {e}")
            logger.error(f"PDF export failed: {e}")

    # ------------------------------------------------------------------
    # EXPORT: EXCEL
    # ------------------------------------------------------------------
    def download_excel(self, report_type: str, data: List[Dict]):
        if self.role not in {'staff', 'admin'}:
            self.log_feedback("Excel export: Access denied")
            return
        try:
            path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                title="Save Excel Report"
            )
            if not path:
                return
            self.exporter.export_to_excel(report_type, path, self.username, self.role, data=data)
            self.log_feedback(f"Exported: {path}")
            logger.info(f"Excel exported: {path}")
        except Exception as e:
            self.log_feedback(f"Excel error: {e}")
            logger.error(f"Excel export failed: {e}")


class ChartWindow(ctk.CTkToplevel):
    def __init__(self, parent, title: str, records, icons, log_feedback=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("800x600")
        self.configure(fg_color="#1E1E1E")
        self.icons = icons
        self.records = records
        self.log_feedback = log_feedback or (lambda x: None)
        logger.info("Initializing ChartWindow")

        # Create matplotlib figure
        fig, ax = plt.subplots(figsize=(6, 4))
        status_counts = {'Complete': 0, 'On Track': 0, 'Behind': 0}
        for record in records:
            status = record.get('status', '')
            if status in status_counts:
                status_counts[status] += 1

        statuses = list(status_counts.keys())
        counts = list(status_counts.values())
        colors = ['#4CAF50', '#FFC107', '#F44336']  # Green, Yellow, Red
        ax.bar(statuses, counts, color=colors)
        ax.set_title("Student Ream Contribution Status")
        ax.set_xlabel("Status")
        ax.set_ylabel("Number of Students")
        for i, count in enumerate(counts):
            ax.text(i, count + 0.5, str(count), ha='center')

        chart_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#2B2B2B")
        chart_frame.pack(fill="both", expand=True, padx=10, pady=10)
        canvas = FigureCanvasTkAgg(fig, master=chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

        # Button frame
        button_frame = ctk.CTkFrame(self, fg_color="#2B2B2B")
        button_frame.pack(pady=10, padx=10, fill="x")

        # Download PDF button (for chart)
        pdf_button = ctk.CTkButton(
            button_frame,
            text="Download as PDF",
            image=self.icons.get('export', None),
            compound="left",
            command=self.download_pdf,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        pdf_button.pack(side="left", padx=5, fill="x", expand=True)

        # Download Excel button (for data behind chart)
        excel_button = ctk.CTkButton(
            button_frame,
            text="Download as Excel",
            image=self.icons.get('export', None),
            compound="left",
            command=self.download_excel,
            fg_color="#2B6CB0",
            hover_color="#1E4E79",
            text_color="#FFFFFF",
            font=("Arial", 12, "bold"),
            height=40,
            corner_radius=10
        )
        excel_button.pack(side="left", padx=5, fill="x", expand=True)

        # Close button
        close_button = ctk.CTkButton(
            button_frame,
            text="Close",
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
        close_button.pack(side="left", padx=5, fill="x", expand=True)
        logger.debug("Buttons added to ChartWindow")

        # Bind Enter and Escape keys to close
        self.bind("<Return>", lambda event: self.destroy())
        self.bind("<Escape>", lambda event: self.destroy())
        self.log_feedback(f"Displayed student ream status chart: Complete={status_counts['Complete']}, On Track={status_counts['On Track']}, Behind={status_counts['Behind']}")

    def download_pdf(self):
        """Download or preview the chart as a PDF with school header and footer."""
        try:
            temp_image_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            image_path = temp_image_file.name
            temp_image_file.close()

            fig, ax = plt.subplots(figsize=(6, 4))
            status_counts = {'Complete': 0, 'On Track': 0, 'Behind': 0}
            for record in self.records:
                status = record.get('status', '')
                if status in status_counts:
                    status_counts[status] += 1
            statuses = list(status_counts.keys())
            counts = list(status_counts.values())
            colors = ['#4CAF50', '#FFC107', '#F44336']
            ax.bar(statuses, counts, color=colors)
            ax.set_title("Student Ream Contribution Status")
            ax.set_xlabel("Status")
            ax.set_ylabel("Number of Students")
            for i, count in enumerate(counts):
                ax.text(i, count + 0.5, str(count), ha='center')
            fig.savefig(image_path, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)

            temp_pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            pdf_path = temp_pdf_file.name
            temp_pdf_file.close()

            doc = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                topMargin=self.exporter.config["pdf_formatting"]["page_margins"]["top"],
                bottomMargin=self.exporter.config["pdf_formatting"]["page_margins"]["bottom"] + 20,
                leftMargin=self.exporter.config["pdf_formatting"]["page_margins"]["left"],
                rightMargin=self.exporter.config["pdf_formatting"]["page_margins"]["right"]
            )
            elements = []

            styles = getSampleStyleSheet()
            header_config = self.exporter.config["pdf_formatting"]["report_headers"].get("chart", {"logo_position": "center", "text_alignment": "center", "logo_width": 1, "logo_height": 1})
            alignment_map = {"left": 0, "center": 1, "right": 2}
            styles.add(ParagraphStyle(
                name='Header',
                fontName=self.exporter.config["pdf_formatting"]["header_font"],
                fontSize=self.exporter.config["pdf_formatting"]["header_font_size"],
                textColor=HexColor(self.exporter.config["pdf_formatting"]["header_color"]),
                spaceAfter=10,
                alignment=alignment_map[header_config["text_alignment"]]
            ))
            styles.add(ParagraphStyle(
                name='Subheader',
                fontName=self.exporter.config["pdf_formatting"]["subheader_font"],
                fontSize=self.exporter.config["pdf_formatting"]["subheader_font_size"],
                textColor=HexColor(self.exporter.config["pdf_formatting"]["header_color"]),
                spaceAfter=5,
                alignment=alignment_map[header_config["text_alignment"]]
            ))

            logo_path = self.exporter.config["school"]["report_logos"].get("chart", self.exporter.config["school"]["logo_path"])
            if os.path.exists(logo_path):
                logo = RLImage(logo_path, width=2*inch, height=2*inch)
                logo.hAlign = header_config["logo_position"].upper()
                elements.append(logo)
            else:
                logger.warning(f"Logo file not found at {logo_path}")
                elements.append(Paragraph("Logo Not Available", styles['Subheader']))
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph(self.exporter.config["school"]["name"], styles['Header']))
            elements.append(Paragraph(self.exporter.config["school"]["p_o_box"], styles['Subheader']))
            elements.append(Paragraph(self.exporter.config["school"]["contact"], styles['Subheader']))
            elements.append(Paragraph(self.exporter.config["school"]["motto"], styles['Subheader']))
            elements.append(Paragraph(self.exporter.config["school"]["website"], styles['Subheader']))
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("Student Ream Contribution Status Chart", styles['Heading1']))
            elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Subheader']))
            elements.append(PageBreak())

            if os.path.exists(image_path):
                chart_image = RLImage(image_path, width=6*inch, height=4*inch)
                chart_image.hAlign = 'CENTER'
                elements.append(chart_image)
            else:
                logger.error(f"Chart image not found at {image_path}")
                elements.append(Paragraph("Chart Not Available", styles['Subheader']))

            doc.build(elements, onFirstPage=self.exporter.build_footer, onLaterPages=self.exporter.build_footer)

            if os.path.exists(image_path):
                os.remove(image_path)

            from reports.report_export import PDFPreviewWindow
            PDFPreviewWindow(self, pdf_path, "chart")
            logger.info("Previewed chart PDF")
        except Exception as e:
            if 'pdf_path' in locals() and os.path.exists(pdf_path):
                os.remove(pdf_path)
            if 'image_path' in locals() and os.path.exists(image_path):
                os.remove(image_path)
            show_error(self, f"Error exporting chart to PDF: {e}")
            self.log_feedback(f"Error exporting chart to PDF: {e}")
            logger.error(f"Error exporting chart to PDF: {e}")

    def download_excel(self):
        """Download the chart data as an Excel file."""
        try:
            file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
            if not file_path:
                self.log_feedback("Download Excel cancelled: No file selected")
                return
            status_counts = {'Complete': 0, 'On Track': 0, 'Behind': 0}
            for record in self.records:
                status = record.get('status', '')
                if status in status_counts:
                    status_counts[status] += 1
            df = pd.DataFrame({
                'Status': list(status_counts.keys()),
                'Count': list(status_counts.values())
            })
            df.to_excel(file_path, index=False)
            show_info(self, f"Chart data exported to {file_path}")
            self.log_feedback(f"Chart data exported to {file_path} as Excel")
            logger.info(f"Chart data exported to Excel at {file_path}")
        except Exception as e:
            show_error(self, f"Error exporting chart data to Excel: {e}")
            self.log_feedback(f"Error exporting chart data to Excel: {e}")
            logger.error(f"Error exporting chart data to Excel: {e}")


class ReportsTab:
    def __init__(self, parent, db_name: str, username: Optional[str], role: Optional[str],
                 main_window, icons, report_manager=None): 
        self.parent = parent
        self.db_name = db_name
        self.username = username
        self.role = role
        self.main_window = main_window
        self.icons = self._convert_icons(icons)
        
        # ---- USE THE PASSED-IN MANAGER ----
        self.report_mgr = report_manager
        if not self.report_mgr:
            raise ValueError("report_manager must be provided after login")
        
        self.student_mgr = StudentManager(db_name)
        self.exporter = ReportExporter(self.report_mgr)
        self.sort_column_name = None
        self.sort_reverse = False
        self._dashboard_open = False
        self.setup_gui()
        logger.info(f"Initializing ReportsTab with username={username}, role={role}")
        self.main_window.log_feedback("ReportsTab initialized; data will load after login")

    def _convert_icons(self, icons):
        converted_icons = {}
        for key, icon in icons.items():
            if isinstance(icon, Image.Image):
                converted_icons[key] = ctk.CTkImage(light_image=icon, dark_image=icon, size=(24, 24))
            else:
                converted_icons[key] = icon
        return converted_icons

    def setup_gui(self):
        self.main_frame = ctk.CTkFrame(self.parent, fg_color="#2B2B2B", corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        if self.role and self.role not in {'admin', 'staff', 'viewer'}:
            ctk.CTkLabel(self.main_frame, text="Permission Denied: Admin, Staff, or Viewer role required",
                         font=("Arial", 16, "bold"), text_color="#FFFFFF").pack(pady=20)
            self.main_window.log_feedback("Access denied: Admin, Staff, or Viewer role required")
            return

        # Filter form
        logger.debug("Creating filter_form in ReportsTab")
        self.filter_form = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        ctk.CTkLabel(self.filter_form, text="Report Filters", font=("Arial", 12, "bold"), text_color="#FFFFFF").pack(pady=5)
        self.filter_entries = {}
        fields = [
            ("Start Date (YYYY-MM-DD)", "start_date"),
            ("End Date (YYYY-MM-DD)", "end_date"),
            ("Form", "form"),
            ("Stream", "stream"),
            ("Department", "department"),
            ("Term", "term"),
            ("Report Type", "report_type")
        ]
        for label, key in fields:
            frame = ctk.CTkFrame(self.filter_form, fg_color="#2B2B2B")
            ctk.CTkLabel(frame, text=label, width=180, text_color="#FFFFFF", font=("Arial", 16)).pack(side="left")
            if key in ["form", "stream", "department", "term", "report_type"]:
                if key == "form":
                    self.filter_entries[key] = ctk.CTkComboBox(frame, values=[""] + list(self.report_mgr.valid_forms), font=("Arial", 12), height=35)
                elif key == "stream":
                    self.filter_entries[key] = ctk.CTkComboBox(frame, values=["", "None"] + self.student_mgr.get_streams(), font=("Arial", 12), height=35)
                elif key == "department":
                    self.filter_entries[key] = ctk.CTkComboBox(frame, values=[""] + list(self.report_mgr.valid_departments), font=("Arial", 12), height=35)
                elif key == "term":
                    self.filter_entries[key] = ctk.CTkComboBox(frame, values=[""] + list(self.report_mgr.valid_terms), font=("Arial", 12), height=35)
                elif key == "report_type":
                    self.filter_entries[key] = ctk.CTkComboBox(frame, values=[""] + [
                        "student_summary", "class_summary", "defaulters", "surplus",
                        "term_summary", "issued_summary", "overview", "stream_ream"
                    ], font=("Arial", 12), height=35)
                self.filter_entries[key].pack(side="left", fill="x", expand=True)
            else:
                self.filter_entries[key] = ctk.CTkEntry(frame, placeholder_text="YYYY-MM-DD", font=("Arial", 12), height=35)
                self.filter_entries[key].pack(side="left", fill="x", expand=True, padx=5)
                calendar_button = ctk.CTkButton(
                    frame,
                    text="Pick Date",
                    image=self.icons.get('calendar', None),
                    compound="left",
                    command=lambda k=key: self.show_calendar(self.filter_entries[k]),
                    fg_color="#2B6CB0",
                    hover_color="#1E4E79",
                    text_color="#FFFFFF",
                    font=("Arial", 12),
                    width=100,
                    height=35
                )
                calendar_button.pack(side="left", padx=5)
            frame.pack(fill="x", pady=2)
            logger.debug(f"Added filter: {label}")
        self.filter_form.pack(pady=10, padx=10, fill="x")

        # Action buttons
        logger.debug("Creating button_frame in ReportsTab")
        buttons = [
            ("Student Reams Summary", self.show_student_summary, 'report'),
            ("Class Reams Summary", self.show_class_summary, 'report'),
            ("Students Reams Defaulters", self.show_defaulters, 'report'),
            ("Student Ream Surplus", self.show_surplus, 'report'),
            ("Reams Term Summary", self.show_term_summary, 'report'),
            ("Reams Issued Summary", self.show_issued_summary, 'report'),
            ("Reams Overview", self.show_overview, 'report'),
            ("Reams Custom Report", self.show_custom_report, 'report'),
            ("Show Dashboard", self.show_dashboard, 'dashboard'),
            ("Stream Ream Report", self.show_stream_ream_report, 'report'),
            ("Status Chart", self.show_status_chart, 'chart'),
            ("Refresh", self.refresh_data, 'refresh')
        ]

        buttons_per_row = 4
        num_rows = (len(buttons) + buttons_per_row - 1) // buttons_per_row
        self.button_frame = ctk.CTkFrame(self.main_frame, fg_color="#2B2B2B", corner_radius=10)
        self.button_frame.pack(pady=10, padx=10, fill="x")

        for col in range(buttons_per_row):
            self.button_frame.grid_columnconfigure(col, weight=1, uniform="button_group")

        for idx, (text, command, icon_key) in enumerate(buttons):
            row = idx // buttons_per_row
            col = idx % buttons_per_row
            button = ctk.CTkButton(
                self.button_frame,
                text=text,
                image=self.icons.get(icon_key, None),
                compound="left",
                command=command,
                fg_color="#2B6CB0",
                hover_color="#1E4E79",
                text_color="#FFFFFF",
                font=("Arial", 14, "bold"),
                height=35,
                width=180,
                corner_radius=10
            )
            button.grid(row=row, column=col, padx=8, pady=6, sticky="ew")
            logger.debug(f"Button gridded: {text} at row {row}, col {col}")

        self.main_frame.update_idletasks()
        logger.info("ReportsTab GUI initialized")

    def update_user(self, username: Optional[str], role: Optional[str]):
        self.username = username
        self.role = role
        logger.info(f"ReportsTab user updated: {username} ({role})")
        self.main_window.log_feedback(f"ReportsTab authorized as {username} ({role})")

    def show_calendar(self, entry_widget):
        def set_date():
            selected_date = cal.get_date()
            entry_widget.delete(0, "end")
            entry_widget.insert(0, selected_date)
            top.destroy()
            logger.info(f"Selected date: {selected_date} for {entry_widget}")

        top = ctk.CTkToplevel(self.main_frame)
        top.title("Select Date")
        top.geometry("300x300")
        top.transient(self.main_frame)
        top.grab_set()
        cal = Calendar(top, selectmode="day", date_pattern="yyyy-mm-dd")
        cal.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkButton(top, text="Confirm", command=set_date).pack(pady=5)
        logger.info("Opened calendar widget")

    def validate_filters(self, start_date: Optional[str], end_date: Optional[str], form: Optional[str],
                        stream: Optional[str], department: Optional[str], term: Optional[str]) -> bool:
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        if start_date and not re.match(date_pattern, start_date):
            show_error(self.main_window, "Start date must be in YYYY-MM-DD format")
            self.main_window.log_feedback("Invalid filter: Invalid start date format")
            return False
        if end_date and not re.match(date_pattern, end_date):
            show_error(self.main_window, "End date must be in YYYY-MM-DD format")
            self.main_window.log_feedback("Invalid filter: Invalid end date format")
            return False
        if start_date and end_date and start_date > end_date:
            show_error(self.main_window, "Start date must be before or equal to end date")
            self.main_window.log_feedback("Invalid filter: Invalid date range")
            return False
        if form and form not in self.report_mgr.valid_forms:
            show_error(self.main_window, f"Form must be one of {self.report_mgr.valid_forms}")
            self.main_window.log_feedback("Invalid filter: Invalid form")
            return False
        if stream and stream != "None":
            valid_streams = self.student_mgr.get_streams()
            if stream not in valid_streams:
                show_error(self.main_window, f"Stream must be one of {valid_streams}")
                self.main_window.log_feedback(f"Invalid filter: Stream must be one of {valid_streams}")
                return False
        if department and department not in self.report_mgr.valid_departments:
            show_error(self.main_window, f"Department must be one of {self.report_mgr.valid_departments}")
            self.main_window.log_feedback("Invalid filter: Invalid department")
            return False
        if term and term not in self.report_mgr.valid_terms:
            show_error(self.main_window, f"Term must be one of {self.report_mgr.valid_terms}")
            self.main_window.log_feedback("Invalid filter: Invalid term")
            return False
        return True

    def get_filters(self):
        start_date = self.filter_entries['start_date'].get().strip() or None
        end_date = self.filter_entries['end_date'].get().strip() or None
        form = self.filter_entries['form'].get() or None
        stream = self.filter_entries['stream'].get() or None
        stream = None if stream == "None" else stream
        department = self.filter_entries['department'].get() or None
        term = self.filter_entries['term'].get() or None
        return start_date, end_date, form, stream, department, term

    def sort_table(self, tree: ttk.Treeview, col: str):
        try:
            records = [(tree.set(item, col), item) for item in tree.get_children()]
            if self.sort_column_name == col:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_reverse = False
                self.sort_column_name = col

            def convert(value):
                try:
                    return float(value.replace("%", "")) if col in ["Percentage", "Collection %"] else float(value) if col in ["Required", "Brought", "Remaining", "Surplus", "Total Students", "Total Brought", "Total Required", "Total Issued", "Total Entries", "Total Reams"] else value.lower()
                except (ValueError, AttributeError):
                    return value

            records.sort(key=lambda x: convert(x[0]), reverse=self.sort_reverse)

            for index, (value, item) in enumerate(records):
                tree.move(item, "", index)

            for column in tree["columns"]:
                tree.heading(column, text=column)
            arrow = " ↓" if not self.sort_reverse else " ↑"
            tree.heading(col, text=col + arrow)
            self.main_window.log_feedback(f"Sorted report table by {col} {'descending' if self.sort_reverse else 'ascending'}")
        except Exception as e:
            show_error(self.main_window, f"Error sorting table: {e}")
            self.main_window.log_feedback(f"Error sorting table by {col}: {e}")
            logger.error(f"Error sorting table by {col}: {e}")

    def show_report_window(self, title: str, columns: List[str], data: List, report_type: str, column_widths: Dict[str, int] = None):
        try:
            self.main_window.open_form_window(
                title=title,
                form_class=ReportWindow,
                columns=columns,
                data=data,
                report_type=report_type,
                report_mgr=self.report_mgr,
                username=self.username,
                role=self.role,
                icons=self.icons,
                column_widths=column_widths,
                log_feedback=self.main_window.log_feedback
            )
            self.main_window.log_feedback(f"Displayed {title} with {len(data)} records")
        except Exception as e:
            show_error(self.main_window, f"Error displaying {title}: {e}")
            self.main_window.log_feedback(f"Error displaying {title}: {e}")
            logger.error(f"Error displaying {title}: {e}")

    def show_student_summary(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Student summary failed: Permission denied")
            return
        try:
            start_date, end_date, form, stream, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, None, None):
                return
            records = self.report_mgr.student_summary(
                start_date, end_date, form, stream
            )
            columns = ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Remaining", "Status"]
            column_widths = {"Name": 150, "Admission No": 120}
            self.show_report_window("Student Summary Report", columns, records, "student_summary", column_widths)
            self.main_window.log_feedback(f"Generated student summary report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating student summary: {e}")
            self.main_window.log_feedback(f"Error generating student summary: {e}")
            logger.error(f"Error generating student summary: {e}")

    def show_class_summary(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Class summary failed: Permission denied")
            return
        try:
            records = self.report_mgr.class_summary()
            columns = ["Form", "Total Students", "Total Brought", "Total Required", "Remaining", "Percentage"]
            self.show_report_window("Class Summary Report", columns, records, "class_summary")
            self.main_window.log_feedback(f"Generated class summary report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating class summary: {e}")
            self.main_window.log_feedback(f"Error generating class summary: {e}")
            logger.error(f"Error generating class summary: {e}")

    def show_defaulters(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Defaulters report failed: Permission denied")
            return
        try:
            start_date, end_date, form, stream, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, None, None):
                return
            records = self.report_mgr.defaulters_report(
                start_date, end_date, form, stream
            )
            columns = ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Remaining"]
            column_widths = {"Name": 150, "Admission No": 120}
            self.show_report_window("Defaulters Report", columns, records, "defaulters", column_widths)
            self.main_window.log_feedback(f"Generated defaulters report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating defaulters report: {e}")
            self.main_window.log_feedback(f"Error generating defaulters report: {e}")
            logger.error(f"Error generating defaulters report: {e}")

    def show_surplus(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Surplus report failed: Permission denied")
            return
        try:
            start_date, end_date, form, stream, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, None, None):
                return
            records = self.report_mgr.surplus_report(
                start_date, end_date, form, stream
            )
            columns = ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Surplus"]
            column_widths = {"Name": 150, "Admission No": 120}
            self.show_report_window("Surplus Report", columns, records, "surplus", column_widths)
            self.main_window.log_feedback(f"Generated surplus report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating surplus report: {e}")
            self.main_window.log_feedback(f"Error generating surplus report: {e}")
            logger.error(f"Error generating surplus report: {e}")

    def show_term_summary(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Term summary failed: Permission denied")
            return
        try:
            start_date, end_date, _, _, _, term = self.get_filters()
            if not self.validate_filters(start_date, end_date, None, None, None, term):
                return
            records = self.report_mgr.term_summary(term, start_date, end_date)
            columns = ["Term", "Total Entries", "Total Reams"]
            self.show_report_window("Term Summary Report", columns, records, "term_summary")
            self.main_window.log_feedback(f"Generated term summary report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating term summary: {e}")
            self.main_window.log_feedback(f"Error generating term summary: {e}")
            logger.error(f"Error generating term summary: {e}")

    def show_issued_summary(self):
        if self.role not in {'viewer', 'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Viewer, Staff, or Admin role required")
            self.main_window.log_feedback("Issued summary failed: Permission denied")
            return
        try:
            start_date, end_date, _, _, department, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, None, None, department, None):
                return
            records = self.report_mgr.issued_summary(
                start_date, end_date, department
            )
            columns = ["Department", "Total Issued"]
            self.show_report_window("Issued Summary Report", columns, records, "issued_summary")
            self.main_window.log_feedback(f"Generated issued summary report with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating issued summary: {e}")
            self.main_window.log_feedback(f"Error generating issued summary: {e}")
            logger.error(f"Error generating issued summary: {e}")

    def show_overview(self):
        if self.role not in {'viewer', 'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Viewer, Staff, or Admin role required")
            self.main_window.log_feedback("Overview report failed: Permission denied")
            return
        try:
            start_date, end_date, _, _, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, None, None, None, None):
                return
            data = self.report_mgr.overview(start_date, end_date)
            records = [{
                "total_required": data["total_required"],
                "total_brought": data["total_brought"],
                "remaining": data["remaining"],
                "collection_percentage": f"{data['collection_percentage']:.2f}%",
                "total_issued": data["total_issued"],
                "total_stock": data["total_stock"]
            }]
            columns = ["Total Required", "Total Brought", "Remaining", "Collection %", "Total Issued", "Total Stock"]
            self.show_report_window("Overview Report", columns, records, "overview")
            self.main_window.log_feedback("Generated overview report")
        except Exception as e:
            show_error(self.main_window, f"Error generating overview: {e}")
            self.main_window.log_feedback(f"Error generating overview: {e}")
            logger.error(f"Error generating overview: {e}")

    def show_custom_report(self):
        if self.role not in {'viewer', 'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Viewer, Staff, or Admin role required")
            self.main_window.log_feedback("Custom report failed: Permission denied")
            return
        try:
            report_type = self.filter_entries['report_type'].get()
            if not report_type:
                show_error(self.main_window, "Report type is required for custom report")
                self.main_window.log_feedback("Custom report failed: Report type required")
                return
            start_date, end_date, form, stream, department, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, department, None):
                return
            report_configs = {
                "student_summary": {
                    "columns": ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Remaining", "Status"],
                    "widths": {"Name": 150, "Admission No": 120}
                },
                "class_summary": {
                    "columns": ["Form", "Total Students", "Total Brought", "Total Required", "Remaining", "Percentage"],
                    "widths": None
                },
                "defaulters": {
                    "columns": ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Remaining"],
                    "widths": {"Name": 150, "Admission No": 120}
                },
                "surplus": {
                    "columns": ["Admission No", "Name", "Form", "Stream", "Required", "Brought", "Surplus"],
                    "widths": {"Name": 150, "Admission No": 120}
                },
                "term_summary": {
                    "columns": ["Term", "Total Entries", "Total Reams"],
                    "widths": None
                },
                "issued_summary": {
                    "columns": ["Department", "Total Issued"],
                    "widths": None
                },
                "overview": {
                    "columns": ["Total Required", "Total Brought", "Remaining", "Collection %", "Total Issued", "Total Stock"],
                    "widths": None
                }
            }
            if report_type not in report_configs:
                show_error(self.main_window, "Invalid report type")
                self.main_window.log_feedback("Custom report failed: Invalid report type")
                return
            
            results = self.report_mgr.custom_report(
                [report_type], start_date, end_date, form, stream, department
            )
            records = results.get(report_type, [])
            config = report_configs[report_type]
            self.show_report_window(
                f"Custom Report: {report_type.replace('_', ' ').title()}",
                config["columns"], records, report_type, config["widths"]
            )
            self.main_window.log_feedback(f"Generated custom report ({report_type}) with {len(records)} records")
        except Exception as e:
            show_error(self.main_window, f"Error generating custom report: {e}")
            self.main_window.log_feedback(f"Error generating custom report: {e}")
            logger.error(f"Error generating custom report: {e}")

    def show_status_chart(self):
        if self.role not in {'viewer', 'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Viewer, Staff, or Admin role required")
            self.main_window.log_feedback("Status chart failed: Permission denied")
            return
        try:
            start_date, end_date, form, stream, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, None, None):
                return
            records = self.report_mgr.student_summary(
                start_date, end_date, form, stream
            )
            self.main_window.open_form_window(
                title="Student Ream Status Chart",
                form_class=ChartWindow,
                records=records,
                icons=self.icons,
                log_feedback=self.main_window.log_feedback
            )
            self.main_window.log_feedback("Displayed student ream status chart")
        except Exception as e:
            show_error(self.main_window, f"Error displaying status chart: {e}")
            self.main_window.log_feedback(f"Error displaying status chart: {e}")
            logger.error(f"Error displaying status chart: {e}")

    def show_dashboard(self):
        if self._dashboard_open:
            logger.debug("Skipped redundant dashboard open")
            return
        self._dashboard_open = True
        try:
            start_date, end_date, _, _, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, None, None, None, None):
                self._dashboard_open = False
                return
            self.main_window.open_form_window(
                title="Reports Dashboard",
                form_class=DashboardWindow,
                report_mgr=self.report_mgr,
                start_date=start_date,
                end_date=end_date,
                username=self.username,
                role=self.role,
                icons=self.icons,
                log_feedback=self.main_window.log_feedback
            )
            self.main_window.log_feedback("Displayed reports dashboard")
        except Exception as e:
            self._dashboard_open = False
            show_error(self.main_window, f"Error displaying dashboard: {e}")
            self.main_window.log_feedback(f"Error displaying dashboard: {e}")
            logger.error(f"Error displaying dashboard: {e}")

    def show_stream_ream_report(self):
        if self.role not in {'staff', 'admin'}:
            show_error(self.main_window, "Permission denied: Staff or Admin role required")
            self.main_window.log_feedback("Stream ream report failed: Permission denied")
            return

        try:
            start_date, end_date, form, stream, _, _ = self.get_filters()
            if not self.validate_filters(start_date, end_date, form, stream, None, None):
                return

            result = self.report_mgr.stream_ream_report(
                self.username, self.role, form, stream, start_date, end_date
            )

            students = result.get('students', [])
            summary  = result.get('summary', {})

            # Defined columns (display only)
            columns = ["Admission No", "Name", "Required", "Brought", "Remaining", "Status"]

            # Build data as list of lists (matching column order)
            data = []
            for s in students:
                data.append([
                    s['admission_no'],
                    s['name'],
                    str(s['required']),
                    str(s['brought']),
                    str(s['remaining']),
                    s['status']
                ])

            if summary:
                data.append([
                    f"** {summary['form']} {summary['stream']} **",
                    f"{summary['total_students']} students",
                    str(summary['total_required']),
                    str(summary['total_brought']),
                    str(summary['total_remaining']),
                    f"{summary['collection_percentage']:.2f}%"
                ])

            column_widths = {"Name": 180, "Admission No": 130}

            # Used show_report_window with list of lists
            self.show_report_window(
                title=f"Stream Ream Report – {form or ''} {stream or ''}",
                columns=columns,
                data=data,
                report_type="stream_ream",
                column_widths=column_widths
            )

            self.main_window.log_feedback(
                f"Generated Stream Ream Report – {len(students)} students, "
                f"{summary.get('collection_percentage', 0):.2f}% collection"
            )
        except Exception as e:
            show_error(self.main_window, f"Error generating Stream Ream Report: {e}")
            self.main_window.log_feedback(f"Error generating Stream Ream Report: {e}")
            logger.error(f"Error generating Stream Ream Report: {e}", exc_info=True)


    def _close_dashboard(self, window):
        self._dashboard_open = False
        window.destroy()
        logger.debug("Reports dashboard window closed")

    def refresh_data(self):
        logger.debug(f"Refreshing ReportsTab with username={self.username}, role={self.role}")
        for key in self.filter_entries:
            if isinstance(self.filter_entries[key], ctk.CTkEntry):
                self.filter_entries[key].delete(0, "end")
            else:
                self.filter_entries[key].set("")
        self.filter_entries['stream'].configure(values=["", "None"] + self.student_mgr.get_streams())
        self.main_window.log_feedback("Refreshed ReportsTab data")
        self.main_frame.update_idletasks()
        logger.info("Refreshed ReportsTab data")