"""
utils.py
========
Purpose:
  Shared helper functions used across the entire NetSage AI project.
  Includes file I/O (CSV), text formatting, timestamps, and console colors.

Why this file exists:
  We don't want to repeat the same helper code in every module.
  All reusable "utility" logic lives here so other files stay focused.
"""

import csv
import os
from datetime import datetime


# ============================================================
# Console Colors (for making output easier to read)
# These are ANSI escape codes. Works on Windows 10+, Linux, macOS.
# ============================================================

class Colors:
    """Simple color codes for terminal output."""
    GREEN = '\033[92m'    # Success / Agreement
    YELLOW = '\033[93m'   # Warning / Partial match
    RED = '\033[91m'      # Error / Disagreement
    CYAN = '\033[96m'     # Info / Headers
    BOLD = '\033[1m'
    RESET = '\033[0m'     # Always end with this to reset colors


def print_header(text):
    """Print a styled section header to the console."""
    line = "=" * 60
    print(f"\n{Colors.BOLD}{Colors.CYAN}{line}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{line}{Colors.RESET}\n")


def print_success(text):
    """Print a green success message."""
    print(f"{Colors.GREEN}[OK] {text}{Colors.RESET}")


def print_warning(text):
    """Print a yellow warning message."""
    print(f"{Colors.YELLOW}[WARN] {text}{Colors.RESET}")


def print_error(text):
    """Print a red error message."""
    print(f"{Colors.RED}[ERROR] {text}{Colors.RESET}")


def print_info(text):
    """Print a cyan info message."""
    print(f"{Colors.CYAN}[INFO] {text}{Colors.RESET}")


# ============================================================
# Timestamp Helpers
# ============================================================

def get_timestamp():
    """Return a human-readable timestamp string (e.g., '2026-08-29 14:30:00')."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_timestamp_for_filename():
    """Return a timestamp safe for use in filenames (no spaces or colons)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# CSV File Helpers
# ============================================================

def read_csv(file_path):
    """
    Read a CSV file and return a list of dictionaries.
    Each dictionary represents one row, with column names as keys.

    Args:
        file_path (str): Absolute or relative path to the CSV file.

    Returns:
        list[dict]: All rows from the CSV, or empty list if file not found.
    """
    rows = []
    if not os.path.exists(file_path):
        print_warning(f"CSV file not found: {file_path}")
        return rows

    # Mapping of common aliases (old column name -> canonical new column name).
    # This lets the project work even when cases.csv uses the 11 new columns
    # while existing code still references the original 5 shorter names.
    COLUMN_ALIASES = {
        "symptom":               "symptoms",
        "show_command_evidence": "show_commands",
        # Also allow reverse access: new code can use new names on old CSVs
        "symptoms":              "symptom",
        "show_commands":         "show_command_evidence",
    }

    try:
        with open(file_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                row = dict(row)
                # Populate BOTH names for aliased columns so old+new code works
                for old_name, new_name in COLUMN_ALIASES.items():
                    if old_name in headers and new_name not in row:
                        row[new_name] = row.get(old_name, "")
                    if new_name in headers and old_name not in row:
                        row[old_name] = row.get(new_name, "")
                rows.append(row)
        print_success(f"Loaded {len(rows)} rows from {os.path.basename(file_path)}")
    except Exception as e:
        print_error(f"Failed to read CSV {file_path}: {e}")

    return rows


def append_csv(file_path, row_dict, fieldnames):
    """
    Append a single row to a CSV file. Creates the file with headers if it doesn't exist.

    Args:
        file_path (str): Path to the CSV file.
        row_dict (dict): Data to write (keys must match fieldnames).
        fieldnames (list[str]): List of column names in order.
    """
    file_exists = os.path.exists(file_path)

    try:
        with open(file_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row_dict)
    except Exception as e:
        print_error(f"Failed to write to CSV {file_path}: {e}")


# ============================================================
# Text / Finding Helpers
# ============================================================

def finding(issue, severity, evidence, suggestion):
    """
    Create a standardized "finding" dictionary.
    Both rule_checker and ai_diagnosis use this format so comparator can compare them.

    Args:
        issue (str): Short description of the problem.
        severity (str): 'low', 'medium', or 'high'.
        evidence (str): What data/evidence points to this issue.
        suggestion (str): Recommended fix.

    Returns:
        dict: A consistent finding object.
    """
    return {
        "issue": issue,
        "severity": severity.lower(),
        "evidence": evidence,
        "suggestion": suggestion
    }


def severity_to_number(severity_str):
    """Convert severity string ('low'/'medium'/'high') to a number for easy comparison."""
    mapping = {"low": 1, "medium": 2, "high": 3}
    return mapping.get(severity_str.lower(), 0)


def save_text_result(file_path, content):
    """Save text content (like a final diagnosis report) to a file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_success(f"Report saved to: {file_path}")
    except Exception as e:
        print_error(f"Failed to save report {file_path}: {e}")
