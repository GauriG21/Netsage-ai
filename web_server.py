"""
web_server.py
=============
Lightweight local web UI server for NetSage AI demonstrations.
Uses ONLY the Python standard library (http.server + json).
Zero external dependencies — same philosophy as the rest of the project.

Endpoints:
  GET  /api/cases                  -> list of case IDs + names from cases.csv
  POST /api/diagnose               -> run full pipeline, return structured JSON
                                        body: {"case_id": "C005"}
  POST /api/review                 -> log a human-review decision (Accept/Edit/Reject)
                                        body: {"case_id":.., "decision":..,
                                               "reviewer_notes":.., "edited_findings_text":..}
  GET  /                           -> serves web/index.html and friends (web/ folder)

Usage:
  python web_server.py            (starts on http://127.0.0.1:8765)
  python web_server.py --port NNN (custom port)

The CLI workflow in src/main.py is completely untouched — this file is a
thin additional wrapper that calls the existing rule_checker / ai_diagnosis /
comparator / human_review modules through the same code paths.
"""

import argparse
import json
import os
import sys
import io
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

# Allow imports from src/ (same trick as main.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
PROJECT_ROOT = SCRIPT_DIR
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from utils import (
    read_csv,
    append_csv,
    get_timestamp,
    get_timestamp_for_filename,
    save_text_result,
)
from rule_checker import run_rule_checker
from ai_diagnosis import call_ai
from comparator import compare_findings
from human_review import (
    REVIEW_LOG_FIELDNAMES,
    findings_to_text,
    text_to_findings,
)


# ============================================================
# File Paths
# ============================================================
CASES_CSV = os.path.join(PROJECT_ROOT, "data", "cases.csv")
REVIEW_LOG_CSV = os.path.join(PROJECT_ROOT, "data", "review_log.csv")
PROMPT_MD = os.path.join(PROJECT_ROOT, "prompts", "diagnose_prompt.md")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
WEB_DIR = os.path.join(PROJECT_ROOT, "web")


# ============================================================
# Pipeline Runner (captures console output)
# ============================================================
def find_case_by_id(cases, case_id):
    for c in cases:
        if c.get("case_id", "").lower() == case_id.lower():
            return c
    return None


def run_pipeline_json(case_id):
    """
    Execute the 3 automated stages (Rule Checker -> AI -> Compare) and
    return a plain-JSON serialisable dict of the result.

    Does NOT commit any human-review decision or save the report — those
    are handled by the separate /api/review endpoint once the reviewer
    clicks Accept/Edit/Reject in the UI.
    """
    cases = read_csv(CASES_CSV)
    case = find_case_by_id(cases, case_id)
    if case is None:
        return None, "Unknown case_id"

    # Capture console logs from backend modules so the UI can replay them
    # in the "process" panel (gives a nice live-feel without streaming WS).
    log_buffer = io.StringIO()

    def run_stage(label, fn, *args, **kwargs):
        print(f"\n[{label}] Starting...", file=log_buffer)
        with contextlib.redirect_stdout(log_buffer):
            result = fn(*args, **kwargs)
        print(f"[{label}] Done.", file=log_buffer)
        return result

    rule_findings = run_stage(
        "Rule-Based Validation", run_rule_checker, case
    )
    ai_findings = run_stage(
        "AI Diagnosis", call_ai, case, prompt_file_path=PROMPT_MD, use_real_api=False
    )
    comparison_report = run_stage(
        "Compare Findings", compare_findings, rule_findings, ai_findings
    )

    merged = comparison_report.get("merged_findings", [])
    merged_text = findings_to_text(merged)

    return {
        "case_id": case.get("case_id"),
        "case_name": case.get("case_name", ""),
        "case_meta": {
            "symptom": case.get("symptom") or case.get("symptoms") or "",
            "topology": case.get("topology", ""),
            "expected_fault": case.get("expected_fault", ""),
            "osi_layer": case.get("osi_layer", ""),
            "concept_tag": case.get("concept_tag", ""),
            "severity": case.get("severity", ""),
            "show_command_evidence": case.get("show_command_evidence")
                                     or case.get("show_commands") or "",
        },
        "rule_findings": rule_findings,
        "ai_findings": ai_findings,
        "comparison": {
            "agreed_findings": comparison_report.get("agreed_findings", []),
            "rule_only_findings": comparison_report.get("rule_only_findings", []),
            "ai_only_findings": comparison_report.get("ai_only_findings", []),
            "agreement_ratio": comparison_report.get("agreement_ratio", 0),
            "confidence_summary": comparison_report.get("confidence_summary", ""),
        },
        "merged_findings": merged,
        "merged_findings_text": merged_text,
        "console_log": log_buffer.getvalue(),
    }, None


def log_review_and_save(case_id, decision, reviewer_notes, edited_findings_text):
    """
    Log the human-review decision to review_log.csv and, for
    Accept/Edit, build+save a final report file to results/.

    Returns (success: bool, message: str, report_filename: str or None).
    """
    cases = read_csv(CASES_CSV)
    case = find_case_by_id(cases, case_id)
    if case is None:
        return False, "Unknown case_id", None

    # Re-run pipeline first so the report reflects the actual findings.
    # Cheap and guarantees consistency.
    pipeline, err = run_pipeline_json(case_id)
    if err:
        return False, err, None

    merged = pipeline["merged_findings"]
    original_text = findings_to_text(merged)

    decision_upper = decision.upper()
    if decision_upper not in {"ACCEPTED", "EDITED", "REJECTED"}:
        return False, "decision must be one of ACCEPTED / EDITED / REJECTED", None

    final_findings = list(merged)
    final_text = original_text

    if decision_upper == "EDITED":
        if edited_findings_text and edited_findings_text.strip():
            parsed = text_to_findings(edited_findings_text)
            if parsed:
                final_findings = parsed
                final_text = edited_findings_text
    elif decision_upper == "REJECTED":
        final_findings = []
        final_text = ""

    reviewer_notes = (reviewer_notes or "").strip()
    if decision_upper == "EDITED" and not reviewer_notes:
        reviewer_notes = "(Edited via web UI — reviewer did not add notes.)"
    if decision_upper == "REJECTED" and not reviewer_notes:
        reviewer_notes = "(Rejected via web UI — reviewer did not provide reason.)"

    # Write log entry (same schema as CLI path)
    ts = get_timestamp()
    log_entry = {
        "timestamp": ts,
        "case_id": case_id,
        "decision": decision_upper,
        "original_findings_summary": original_text[:2000],
        "final_findings_summary": final_text[:2000],
        "reviewer_notes": reviewer_notes[:1000],
    }
    append_csv(REVIEW_LOG_CSV, log_entry, REVIEW_LOG_FIELDNAMES)

    # Build and save a final text report for Accept / Edit only.
    report_filename = None
    if decision_upper in {"ACCEPTED", "EDITED"}:
        lines = []
        lines.append("=" * 70)
        lines.append("NetSage AI - TROUBLESHOOTING REPORT (WEB UI)")
        lines.append("=" * 70)
        lines.append(f"Generated: {ts}")
        lines.append(f"Case ID:   {case.get('case_id', '?')}")
        lines.append(f"Decision:  {decision_upper}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("CASE INPUT")
        lines.append("-" * 70)
        lines.append(f"Symptoms:  {pipeline['case_meta']['symptom']}")
        lines.append(f"Topology:  {pipeline['case_meta']['topology']}")
        lines.append(f"Evidence (show commands excerpt):")
        for ev_line in (pipeline['case_meta']['show_command_evidence'][:3000]).splitlines() or ["(none)"]:
            lines.append(f"  {ev_line}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("COMPARISON SUMMARY")
        lines.append("-" * 70)
        comp = pipeline["comparison"]
        lines.append(comp["confidence_summary"])
        lines.append(f"Agreement ratio: {comp['agreement_ratio']}")
        lines.append(f"Agreed findings:  {len(comp['agreed_findings'])}")
        lines.append(f"Rule-only:        {len(comp['rule_only_findings'])}")
        lines.append(f"AI-only:          {len(comp['ai_only_findings'])}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("FINAL FINDINGS (after human review)")
        lines.append("-" * 70)
        if final_findings:
            lines.append(findings_to_text(final_findings))
        else:
            lines.append("(Findings were rejected by the reviewer.)")
        lines.append("")
        if reviewer_notes:
            lines.append("-" * 70)
            lines.append("REVIEWER NOTES")
            lines.append("-" * 70)
            lines.append(reviewer_notes)
            lines.append("")
        lines.append("-" * 70)
        lines.append("NEXT STEPS FOR HUMAN")
        lines.append("-" * 70)
        if decision_upper == "REJECTED":
            lines.append("1. Start the diagnosis again with more detailed evidence.")
            lines.append("2. Add additional 'show' command output to cases.csv.")
            lines.append("3. Consider adding a new rule to rule_checker.py.")
        else:
            lines.append("1. Open the .pkt file in Cisco Packet Tracer.")
            lines.append("2. Apply the recommended fix(es) step by step.")
            lines.append("3. Verify: ping between affected devices.")
        lines.append("")
        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        report_text = "\n".join(lines)
        report_filename = f"case_{case_id}_{get_timestamp_for_filename()}_web_report.txt"
        report_path = os.path.join(RESULTS_DIR, report_filename)
        save_text_result(report_path, report_text)

    return True, f"Review decision {decision_upper} logged.", report_filename


# ============================================================
# HTTP Handler
# ============================================================
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}


class NetSageWebHandler(BaseHTTPRequestHandler):
    server_version = "NetSageAIDemo/1.0"

    def log_message(self, fmt, *args):
        # Quieter logs than default BaseHTTPRequestHandler.
        sys.stderr.write("[WEB] %s - %s\n" % (self.address_string(), fmt % args))

    # ---------- helpers ----------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid JSON body: {e}")

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- API routes ---
        if path == "/api/cases":
            return self._handle_get_cases()
        if path.startswith("/api/"):
            return self._send_json({"error": "Unknown GET endpoint"}, status=404)

        # --- Static files (web/ folder) ---
        if path == "/" or path == "":
            rel_path = "index.html"
        else:
            rel_path = path.lstrip("/")
            # Prevent path traversal
            rel_path = unquote(rel_path).replace("\\", "/")
            if ".." in rel_path.split("/"):
                return self._send_json({"error": "Forbidden"}, status=403)

        full = os.path.join(WEB_DIR, rel_path)
        if not os.path.exists(full) or not os.path.isfile(full):
            # Friendly fallback: serve index.html instead of 404 for SPA-ish deep links
            full_index = os.path.join(WEB_DIR, "index.html")
            if os.path.exists(full_index) and "." not in rel_path.split("/")[-1]:
                full = full_index
            else:
                return self._send_json({"error": "Not found: " + path}, status=404)

        ext = os.path.splitext(full)[1].lower()
        ctype = MIME_TYPES.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
        except Exception as e:
            return self._send_json({"error": f"Could not read file: {e}"}, status=500)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=400)

        if path == "/api/diagnose":
            return self._handle_post_diagnose(body)
        if path == "/api/review":
            return self._handle_post_review(body)
        return self._send_json({"error": "Unknown POST endpoint"}, status=404)

    # ---------- handlers ----------
    def _handle_get_cases(self):
        cases = read_csv(CASES_CSV)
        # Only surface cases that are "demonstration-ready" per project docs.
        demo_case_ids = {"C001", "C002", "C004", "C005"}
        out = []
        for c in cases:
            cid = c.get("case_id", "")
            entry = {
                "case_id": cid,
                "case_name": c.get("case_name", ""),
                "symptom": c.get("symptom") or c.get("symptoms") or "",
                "topology": c.get("topology", ""),
                "expected_fault": c.get("expected_fault", ""),
                "osi_layer": c.get("osi_layer", ""),
                "concept_tag": c.get("concept_tag", ""),
                "severity": c.get("severity", ""),
                "demo_ready": cid in demo_case_ids,
            }
            out.append(entry)
        self._send_json({"cases": out})

    def _handle_post_diagnose(self, body):
        case_id = (body.get("case_id") or "").strip()
        if not case_id:
            return self._send_json({"error": "case_id required"}, status=400)
        result, err = run_pipeline_json(case_id)
        if err:
            return self._send_json({"error": err}, status=404)
        self._send_json({"ok": True, "data": result})

    def _handle_post_review(self, body):
        case_id = (body.get("case_id") or "").strip()
        decision = (body.get("decision") or "").strip()
        notes = body.get("reviewer_notes") or ""
        edited = body.get("edited_findings_text") or None
        if not case_id or not decision:
            return self._send_json(
                {"error": "case_id and decision required"}, status=400
            )
        ok, msg, report = log_review_and_save(case_id, decision, notes, edited)
        status = 200 if ok else 400
        self._send_json({
            "ok": ok,
            "message": msg,
            "report_filename": report,
            "decision": decision.upper() if ok else None,
        }, status=status)


# ============================================================
# Entry point
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="NetSage AI — local web UI server (stdlib only)."
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1, not exposed)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Bind port (default: 8765)")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), NetSageWebHandler)
    print()
    print("=" * 62)
    print("  NetSage AI — Web UI Server")
    print("=" * 62)
    print(f"  URL:       http://{args.host}:{args.port}/")
    print(f"  Cases:     from {os.path.relpath(CASES_CSV, PROJECT_ROOT)}")
    print(f"  Reports:   saved to {os.path.relpath(RESULTS_DIR, PROJECT_ROOT)}/")
    print(f"  Backend:   reuses src/rule_checker.py, src/ai_diagnosis.py,")
    print(f"             src/comparator.py, src/human_review.py (unchanged).")
    print(f"  CLI:       python src/main.py C001 --demo continues to work.")
    print("=" * 62)
    print("  Press Ctrl+C to stop.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Server stopped by user.")
        server.server_close()


if __name__ == "__main__":
    main()
