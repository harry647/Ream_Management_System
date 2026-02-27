from tkinter import messagebox, Misc
import re
import os
import sys 
from datetime import datetime
from typing import Optional, Callable, Set
from modules.user_manager import UserManager
import logging

# Configure logging with UTF-8 encoding
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/utils.log', encoding='utf-8'),  # UTF-8
        logging.StreamHandler(sys.stdout)  # Console
    ]
)
logger = logging.getLogger(__name__)


def show_error(parent: Misc, message: str, log_callback: Optional[Callable[[str], None]] = None) -> None:
    """Show an error dialog and optionally log the message.

    Args:
        parent: The parent Tkinter widget (e.g., Tk, Toplevel, or customtkinter widget).
        message: The error message to display.
        log_callback: Optional callback to log the message to a feedback log.
    """
    messagebox.showerror("Error", message, parent=parent)
    if log_callback:
        log_callback(f"Error: {message}")
    logger.error(message)

def show_info(parent: Misc, message: str, title: str = "Information", log_callback: Optional[Callable[[str], None]] = None) -> None:
    """Show an info dialog with customizable title and optional logging.
    Args:
        parent: The parent Tkinter widget.
        message: The info message to display.
        title: Dialog title (default: "Information").
        log_callback: Optional callback to log the message.
    """
    messagebox.showinfo(title, message, parent=parent)
    if log_callback:
        log_callback(f"Info: {message}")
    logger.info(message)

def validate_date(date_str: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate date format (YYYY-MM-DD).

    Args:
        date_str: The date string to validate.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid or empty, False otherwise.
    """
    if not date_str:
        return True
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        if log_callback:
            log_callback("Validation failed: Invalid date format (use YYYY-MM-DD)")
        logger.warning(f"Invalid date format: {date_str}")
        return False
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        if log_callback:
            log_callback("Validation failed: Invalid date")
        logger.warning(f"Invalid date: {date_str}")
        return False

def validate_form(form: str, valid_forms: Set[str] = {'Form 1', 'Form 2', 'Form 3', 'Form 4', 'Grade 10', 'Grade 11', 'Grade 12'},
                 log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate form.

    Args:
        form: The form to validate.
        valid_forms: Set of valid form names.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid or empty, False otherwise.
    """
    if not form or form in valid_forms:
        return True
    if log_callback:
        log_callback(f"Validation failed: Invalid form: {form}")
    logger.warning(f"Invalid form: {form}")
    return False


def validate_term(term: str, valid_terms: Set[str] = {'Term 1', 'Term 2', 'Term 3'},
                 log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate term.

    Args:
        term: The term to validate.
        valid_terms: Set of valid term names.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid, False otherwise.
    """
    if term in valid_terms:
        return True
    if log_callback:
        log_callback(f"Validation failed: Invalid term: {term}")
    logger.warning(f"Invalid term: {term}")
    return False

def validate_department(department: str, valid_departments: Set[str] = {'Mathematics', 'Sciences', 'Languages', 'Humanities', 'Technical', 'Library', 'Administration', 'Exams', 'Store'},
                       log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate department.

    Args:
        department: The department to validate.
        valid_departments: Set of valid department names.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid or empty, False otherwise.
    """
    if not department or department in valid_departments:
        return True
    if log_callback:
        log_callback(f"Validation failed: Invalid department: {department}")
    logger.warning(f"Invalid department: {department}")
    return False

def validate_positive_int(value: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate positive integer."""
    try:
        num = int(value)
        if num > 0:
            return True
        if log_callback:
            log_callback(f"Validation failed: Value must be a positive integer: {value}")
        logger.warning(f"Invalid positive integer: {value}")
        return False
    except ValueError:
        if log_callback:
            log_callback(f"Validation failed: Value must be a positive integer: {value}")
        logger.warning(f"Invalid positive integer: {value}")
        return False  

def validate_not_empty(value: str, field_name: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate that a field is not empty.

    Args:
        value: The value to validate.
        field_name: Name of the field for error messages.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if not empty, False otherwise.
    """
    if value.strip():
        return True
    if log_callback:
        log_callback(f"Validation failed: {field_name} is required")
    logger.warning(f"{field_name} is required")
    return False

def validate_username(username: str, db_name: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate username: 3-20 alphanumeric characters with underscores, and unique.

    Args:
        username: The username to validate.
        db_name: Path to the database for uniqueness check.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid and unique, False otherwise.
    """
    if not validate_not_empty(username, "Username", log_callback):
        return False
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
        if log_callback:
            log_callback("Validation failed: Username must be 3-20 alphanumeric characters with underscores")
        logger.warning(f"Invalid username format: {username}")
        return False
    try:
        user_mgr = UserManager(db_name)
        if user_mgr.user_exists(username):
            if log_callback:
                log_callback(f"Validation failed: Username already exists: {username}")
            logger.warning(f"Username already exists: {username}")
            return False
        return True
    except Exception as e:
        if log_callback:
            log_callback(f"Validation failed: Error checking username: {str(e)}")
        logger.error(f"Error checking username {username}: {str(e)}")
        return False

def validate_password(password: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """Validate password: 6-50 characters, with at least one letter and one digit.

    Args:
        password: The password to validate.
        log_callback: Optional callback to log validation errors.

    Returns:
        bool: True if valid, False otherwise.
    """
    pattern = r'^(?=.*[a-zA-Z])(?=.*\d)[a-zA-Z\d]{6,50}$'
    if re.match(pattern, password):
        return True
    if log_callback:
        log_callback("Validation failed: Password must be 6-50 characters with at least one letter and one digit")
    logger.warning(f"Invalid password format")
    return False