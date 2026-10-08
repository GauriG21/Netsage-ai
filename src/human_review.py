"""
human_review.py
===============
Purpose:
  Implement the MANDATORY human review step.
  The system NEVER automatically applies a fix — a human MUST choose one of:
    1. ACCEPTED  — Use the diagnosis/fix as-is
    2. EDITED    — Human modified the diagnosis/fix
    3. REJECTED  — Human throws away this diagnosis entirely

Also logs every review decision to data/review_log.csv for accountability and learning.
"""

import os
import sys
from utils import (
    get_timestamp,
    append_csv,
    print_header,
    print_success,
    print_warning,
    print_error,
    Colors,
)


# CSV columns for the review log
REVIEW_LOG_FIELDNAMES = [
    "timestamp",
    "case_id",
    "decision",          # ACCEPTED / EDITED / REJECTED
    "original_findings_summary",
    "final_findings_summary",
    "reviewer_notes",
]


# ============================================================
# Helpers to render findings to text (for editing and logging)
# ============================================================

def findings_to_text(merged_findings):
    """Convert merged findings list into a plain text block that the user can read/edit."""
    lines = []
    for i, f in enumerate(merged_findings, 1):
        conf = f.get("confidence", "?")
        sev = f.get("severity", "?").upper()
        group = f.get("group", "?")
        lines.append(f"--- Finding #{i} [{sev}] [confidence:{conf}] [group:{group}] ---")
        lines.append(f"Issue:      {f.get('issue', '')}")
        lines.append(f"Evidence:   {f.get('evidence', '')}")
        lines.append(f"Suggestion: {f.get('suggestion', '')}")
        lines.append("")
    return "\n".join(lines)


def text_to_findings(text_block):
    """
    Reverse of findings_to_text.
    Accepts a text block and tries to parse it back into findings.
    For v1, this is intentionally simple and accepts manual edits by the user.
    Returns a list of findings dicts.
    """
    findings = []
    current = {}
    for raw_line in text_block.split("\n"):
        line = raw_line.rstrip()
        if line.startswith("--- Finding #"):
            # start of a new finding - save previous if exists
            if current:
                findings.append(current)
            # try to pull severity label
            sev = "low"
            if "[HIGH]" in line:
                sev = "high"
            elif "[MEDIUM]" in line:
                sev = "medium"
            current = {"severity": sev}
        elif line.startswith("Issue:"):
            current["issue"] = line[len("Issue:"):].strip()
        elif line.startswith("Evidence:"):
            current["evidence"] = line[len("Evidence:"):].strip()
        elif line.startswith("Suggestion:"):
            current["suggestion"] = line[len("Suggestion:"):].strip()

    if current:
        findings.append(current)
    return findings


# ============================================================
# Console Input Helpers
# ============================================================

def _ask_choice(prompt, valid_choices):
    """Keep asking until the user picks one of valid_choices (case-insensitive)."""
    while True:
        raw = input(prompt).strip().upper()
        if raw in valid_choices:
            return raw
        print_warning(f"Invalid choice. Please enter one of: {', '.join(valid_choices)}")


def _ask_text(prompt, allow_empty=True, multiline=False):
    """Ask the user for free-form text input."""
    if multiline:
        print(prompt)
        print("  (Type your text. Enter '---END---' on its own line when finished.)")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "---END---":
                break
            lines.append(line)
        text = "\n".join(lines).strip()
    else:
        text = input(prompt).strip()

    if not text and not allow_empty:
        print_warning("Input cannot be empty. Please try again.")
        return _ask_text(prompt, allow_empty, multiline)
    return text


# ============================================================
# Main Review Entry Point
# ============================================================

def run_human_review(case_id, comparison_report, review_log_path):
    """
    Walk the human reviewer through the mandatory review process.

    Args:
        case_id (str): The case being reviewed.
        comparison_report (dict): Output from comparator.compare_findings().
        review_log_path (str): Path to review_log.csv.

    Returns:
        dict: Final review outcome with keys:
            - decision (ACCEPTED/EDITED/REJECTED)
            - final_findings (possibly-edited list of findings)
            - reviewer_notes (str)
    """
    print_header("MANDATORY HUMAN REVIEW STEP")
    print(f"Case ID: {case_id}")
    print("As the human reviewer, you must decide the final outcome.")
    print("  Rules: AI NEVER applies a fix automatically. YOU are in charge.\n")

    merged = comparison_report.get("merged_findings", [])
    original_text = findings_to_text(merged)

    print(f"{Colors.BOLD}Proposed findings from the system:{Colors.RESET}")
    print("-" * 60)
    print(original_text)
    print("-" * 60)
    print()

    # Step 1: Show choices
    print("Please choose one:")
    print(f"  {Colors.BOLD}[A]{Colors.RESET}ccepted  - Use these findings exactly as shown")
    print(f"  {Colors.BOLD}[E]{Colors.RESET}dited    - You want to modify the findings")
    print(f"  {Colors.BOLD}[R]{Colors.RESET}ejected  - Reject these findings entirely")
    print()

    choice = _ask_choice("Your choice (A/E/R): ", {"A", "E", "R"})

    decision = None
    final_findings = list(merged)
    final_text = original_text
    reviewer_notes = ""

    if choice == "A":
        decision = "ACCEPTED"
        print_success("You have ACCEPTED the proposed findings.")
        reviewer_notes = _ask_text("Optional reviewer notes (press Enter to skip): ", allow_empty=True)

    elif choice == "E":
        decision = "EDITED"
        print_warning("You have chosen to EDIT the findings.")
        print("\nHere is the current findings text. You may rewrite it freely.")
        print("Hint: copy, edit, and paste back. Keep the 'Issue:/Evidence:/Suggestion:' lines.\n")
        print(original_text)
        print()

        edited_text = _ask_text("Paste/write edited findings below: ", allow_empty=False, multiline=True)
        final_text = edited_text if edited_text.strip() else original_text
        final_findings = text_to_findings(final_text)

        if not final_findings:
            print_warning("Could not parse edited text into structured findings; using original text as-is.")
            final_findings = list(merged)
            final_text = original_text

        reviewer_notes = _ask_text("Short note explaining your edits (required): ", allow_empty=False)
        print_success("Edited findings recorded.")

    elif choice == "R":
        decision = "REJECTED"
        print_error("You have REJECTED the proposed findings.")
        final_findings = []
        final_text = ""
        reviewer_notes = _ask_text(
            "Reason for rejection (required - helps improve the system): ",
            allow_empty=False
        )

    # Step 2: Write to review log
    log_entry = {
        "timestamp": get_timestamp(),
        "case_id": case_id,
        "decision": decision,
        "original_findings_summary": original_text[:2000],
        "final_findings_summary": final_text[:2000],
        "reviewer_notes": reviewer_notes[:1000],
    }
    append_csv(review_log_path, log_entry, REVIEW_LOG_FIELDNAMES)
    print_success(f"Review decision logged to: {os.path.basename(review_log_path)}")

    return {
        "decision": decision,
        "final_findings": final_findings,
        "reviewer_notes": reviewer_notes,
        "timestamp": log_entry["timestamp"],
    }
