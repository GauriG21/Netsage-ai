"""
main.py
=======
Purpose:
  The **entry point** for NetSage AI.
  Orchestrates the ENTIRE troubleshooting workflow end-to-end:

    Packet Tracer Case (from cases.csv)
        ↓
    Rule Checker  +  AI Diagnosis (mock)
        ↓
    Compare Findings
        ↓
    MANDATORY Human Review  (Accepted / Edited / Rejected)
        ↓
    Recommended Fix  →  saved to results/
        ↓
    (Human applies fix in Packet Tracer manually)
        ↓
    Verification notes recorded in review log

How to run:
  From the project root:
      python src/main.py

  It will ask you to pick a case from cases.csv interactively.
  OR pass a case_id on the command line:
      python src/main.py C001

  OR use --demo to auto-pick the first case and auto-accept (for quick testing,
  review is still logged but decision is pre-selected).
"""

import os
import sys
import argparse

# Allow imports from the same src/ directory when running `python src/main.py`
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from utils import (
    print_header,
    print_info,
    print_success,
    print_warning,
    print_error,
    read_csv,
    get_timestamp_for_filename,
    save_text_result,
    Colors,
)
from rule_checker import run_rule_checker
from ai_diagnosis import call_ai
from comparator import compare_findings, print_comparison
from human_review import run_human_review, findings_to_text


# ============================================================
# File Paths (resolved relative to this project)
# ============================================================

CASES_CSV = os.path.join(PROJECT_ROOT, "data", "cases.csv")
REVIEW_LOG_CSV = os.path.join(PROJECT_ROOT, "data", "review_log.csv")
PROMPT_MD = os.path.join(PROJECT_ROOT, "prompts", "diagnose_prompt.md")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")


# ============================================================
# Case Selection
# ============================================================

def list_cases(cases):
    """Print a menu of available cases."""
    print("\nAvailable cases:")
    for i, case in enumerate(cases, 1):
        cid = case.get("case_id", f"?-{i}")
        title = case.get("symptoms", "(no symptoms)")[:60]
        print(f"  {i:>2}. [{cid}] {title}...")
    print(f"   0. Exit")


def pick_case_interactive(cases):
    """Let the user choose a case by number."""
    while True:
        list_cases(cases)
        raw = input("\nEnter case number to analyze: ").strip()
        if raw == "0":
            print_info("Goodbye.")
            return None
        if not raw.isdigit():
            print_warning("Please enter a number.")
            continue
        idx = int(raw) - 1
        if 0 <= idx < len(cases):
            return cases[idx]
        print_warning("Case number out of range.")


def find_case_by_id(cases, case_id):
    """Look up a case by its case_id string."""
    for c in cases:
        if c.get("case_id", "").lower() == case_id.lower():
            return c
    return None


# ============================================================
# Final Report Builder
# ============================================================

def build_final_report(case, comparison_report, review_outcome):
    """Create a human-readable text report saved to results/."""
    lines = []
    lines.append("=" * 70)
    lines.append("NetSage AI - TROUBLESHOOTING REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {review_outcome.get('timestamp', '?')}")
    lines.append(f"Case ID:   {case.get('case_id', '?')}")
    lines.append(f"Decision:  {review_outcome.get('decision', '?')}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("CASE INPUT")
    lines.append("-" * 70)
    lines.append(f"Symptoms:  {case.get('symptoms', '')}")
    lines.append(f"Topology:  {case.get('topology', '')}")
    lines.append(f"Evidence (show commands):")
    for ev_line in case.get("show_commands", "").splitlines() or ["(none)"]:
        lines.append(f"  {ev_line}")
    if case.get("expected_fix"):
        lines.append(f"\n(Student-provided expected fix hint): {case['expected_fix']}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("COMPARISON SUMMARY")
    lines.append("-" * 70)
    lines.append(comparison_report.get("confidence_summary", "?"))
    lines.append(f"Agreement ratio: {comparison_report.get('agreement_ratio', '?')}")
    lines.append(f"Agreed findings:  {len(comparison_report.get('agreed_findings', []))}")
    lines.append(f"Rule-only:        {len(comparison_report.get('rule_only_findings', []))}")
    lines.append(f"AI-only:          {len(comparison_report.get('ai_only_findings', []))}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("FINAL FINDINGS (after human review)")
    lines.append("-" * 70)
    final = review_outcome.get("final_findings", [])
    if final:
        lines.append(findings_to_text(final))
    else:
        lines.append("(Findings were rejected by the reviewer.)")
    lines.append("")

    notes = review_outcome.get("reviewer_notes")
    if notes:
        lines.append("-" * 70)
        lines.append("REVIEWER NOTES")
        lines.append("-" * 70)
        lines.append(notes)
        lines.append("")

    lines.append("-" * 70)
    lines.append("NEXT STEPS FOR HUMAN")
    lines.append("-" * 70)
    if review_outcome["decision"] == "REJECTED":
        lines.append("1. Start the diagnosis again with more detailed evidence.")
        lines.append("2. Add additional 'show' command output to cases.csv for this case.")
        lines.append("3. Consider adding a new rule to rule_checker.py for this scenario.")
    else:
        lines.append("1. Open the corresponding .pkt file in Cisco Packet Tracer.")
        lines.append("2. Apply the recommended fix(es) above step by step.")
        lines.append("3. Verify: ping between affected devices, test connectivity.")
        lines.append("4. (Optional) Re-run NetSage AI with post-fix evidence to confirm resolution.")
    lines.append("")
    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    return "\n".join(lines)


# ============================================================
# Workflow Orchestration
# ============================================================

def run_workflow(case, demo_auto_accept=False):
    """
    Execute the full NetSage AI pipeline for a single case.
    If demo_auto_accept=True, skips interactive review and auto-accepts.
    """
    case_id = case.get("case_id", "unknown")

    print_header(f"STARTING DIAGNOSIS FOR CASE {case_id}")

    # ---- Step 1: Python Rule Checker ----
    print_header("Step 1/4: Rule-Based Validation (Python)")
    rule_findings = run_rule_checker(case)

    # ---- Step 2: AI Diagnosis ----
    print_header("Step 2/4: AI Diagnosis (Mock v1)")
    ai_findings = call_ai(case, prompt_file_path=PROMPT_MD, use_real_api=False)

    # ---- Step 3: Compare Findings ----
    print_header("Step 3/4: Compare Rule Checker vs AI")
    comparison_report = compare_findings(rule_findings, ai_findings)
    print_comparison(comparison_report)

    # ---- Step 4: Mandatory Human Review ----
    print_header("Step 4/4: Mandatory Human Review")
    if demo_auto_accept:
        print_warning("DEMO MODE: Auto-accepting findings (review still logged).")
        from human_review import REVIEW_LOG_FIELDNAMES
        from utils import get_timestamp, append_csv
        merged = comparison_report.get("merged_findings", [])
        ts = get_timestamp()
        log_entry = {
            "timestamp": ts,
            "case_id": case_id,
            "decision": "ACCEPTED",
            "original_findings_summary": findings_to_text(merged)[:2000],
            "final_findings_summary": findings_to_text(merged)[:2000],
            "reviewer_notes": "[DEMO MODE] Auto-accepted for testing purposes.",
        }
        append_csv(REVIEW_LOG_CSV, log_entry, REVIEW_LOG_FIELDNAMES)
        review_outcome = {
            "decision": "ACCEPTED",
            "final_findings": merged,
            "reviewer_notes": log_entry["reviewer_notes"],
            "timestamp": ts,
        }
    else:
        review_outcome = run_human_review(case_id, comparison_report, REVIEW_LOG_CSV)

    # ---- Step 5: Save Final Report ----
    print_header("Generating Final Report")
    report_text = build_final_report(case, comparison_report, review_outcome)
    report_filename = f"case_{case_id}_{get_timestamp_for_filename()}_report.txt"
    report_path = os.path.join(RESULTS_DIR, report_filename)
    save_text_result(report_path, report_text)

    # ---- Final Outcome ----
    print_header("WORKFLOW COMPLETE")
    decision = review_outcome["decision"]
    if decision == "ACCEPTED":
        print_success("Recommended fix has been ACCEPTED. Report saved above.")
        print_info("-> Open the report in results/ and apply the fix in Packet Tracer.")
    elif decision == "EDITED":
        print_success("Findings were EDITED by the reviewer. Report saved above.")
        print_info("-> Apply the EDITED fix in Packet Tracer.")
    else:
        print_warning("Findings were REJECTED. No fix recommended.")
        print_info("-> Refine the case evidence in cases.csv and re-run, or add new rules.")

    return review_outcome


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="NetSage AI - AI-assisted network troubleshooting (v1, mock AI)."
    )
    parser.add_argument(
        "case_id",
        nargs="?",
        default=None,
        help="Case ID from data/cases.csv (e.g., C001). If omitted, shows interactive menu."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo mode: auto-accept findings without interactive review (for testing)."
    )
    args = parser.parse_args()

    # Banner
    print(f"\n{Colors.BOLD}{Colors.CYAN}"
          r"  _   _      _   ____                     _    ___ " + "\n"
          r" | \ | | ___| |_/ ___|  __ _  __ _  ___  | |  |_ _|" + "\n"
          r" |  \| |/ _ \ __\___ \ / _` |/ _` |/ _ \ | |   | | " + "\n"
          r" | |\  |  __/ |_ ___) | (_| | (_| |  __/ | |___| | " + "\n"
          r" |_| \_|\___|\__|____/ \__,_|\__, |\___| |_____|___|" + "\n"
          r"                             |___/                   "
          f"{Colors.RESET}\n")
    print_info("Version 1 - No external dependencies. Mock AI enabled.")

    # Load cases
    cases = read_csv(CASES_CSV)
    if not cases:
        print_error(f"No cases loaded from {CASES_CSV}. Exiting.")
        print_info("Add at least one row to data/cases.csv before running.")
        sys.exit(1)

    # Decide which case to analyze
    if args.case_id:
        case = find_case_by_id(cases, args.case_id)
        if not case:
            print_error(f"Case '{args.case_id}' not found in cases.csv.")
            sys.exit(2)
    else:
        case = pick_case_interactive(cases)
        if case is None:
            sys.exit(0)

    # Run the pipeline
    run_workflow(case, demo_auto_accept=args.demo)


if __name__ == "__main__":
    main()
