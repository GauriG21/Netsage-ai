"""
comparator.py
=============
Purpose:
  Compare the findings from the Rule Checker and the AI Diagnosis module.
  Highlight agreements, disagreements, and merged recommendations.

Why this matters:
  - If BOTH rule checker and AI agree on an issue, confidence is HIGH.
  - If only ONE of them flags something, it's worth a closer look.
  - The human reviewer should see this comparison clearly.

Output:
  A "comparison report" dict that groups findings into:
    - agreed_findings (both sides flagged similar issues)
    - rule_only_findings (only rule checker found it)
    - ai_only_findings (only AI found it)
    - merged_findings (combined list, with extra notes)
    - confidence_summary (overall score/text)
"""

from utils import severity_to_number, print_info, Colors


# ============================================================
# Similarity Helper (simple keyword overlap)
# ============================================================

def _issue_similarity(finding_a, finding_b):
    """
    Very simple "similarity" check between two findings.
    Returns a number between 0.0 and 1.0 based on shared keywords.

    For v1, we keep this intentionally simple. Better similarity
    (using AI embeddings or fuzzy matching) can be added later.
    """
    words_a = set(finding_a["issue"].lower().split())
    words_b = set(finding_b["issue"].lower().split())

    if not words_a or not words_b:
        return 0.0

    common = words_a & words_b
    total = words_a | words_b
    jaccard = len(common) / len(total)

    # Boost score if severity is the same
    if finding_a.get("severity") == finding_b.get("severity"):
        jaccard = min(1.0, jaccard + 0.1)

    return jaccard


# ============================================================
# Core Comparison Logic
# ============================================================

def compare_findings(rule_findings, ai_findings, similarity_threshold=0.25):
    """
    Compare rule-based findings with AI-based findings.

    Args:
        rule_findings (list[dict]): Output from rule_checker.run_rule_checker()
        ai_findings   (list[dict]): Output from ai_diagnosis.call_ai()
        similarity_threshold (float): How similar two issues must be to count as "agreed".

    Returns:
        dict: A structured comparison report (see module docstring for keys).
    """
    print_info("Comparing Rule Checker vs AI Diagnosis findings...")

    agreed = []
    rule_only = []
    ai_only = []

    # Track which AI findings have already been matched to a rule finding
    ai_matched = [False] * len(ai_findings)

    for rf in rule_findings:
        best_match_idx = -1
        best_score = 0.0

        for i, af in enumerate(ai_findings):
            if ai_matched[i]:
                continue
            score = _issue_similarity(rf, af)
            if score > best_score:
                best_score = score
                best_match_idx = i

        if best_score >= similarity_threshold and best_match_idx >= 0:
            # Both agree!
            matched_ai = ai_findings[best_match_idx]
            ai_matched[best_match_idx] = True

            agreed.append({
                "rule_issue": rf["issue"],
                "ai_issue": matched_ai["issue"],
                "severity": rf["severity"],
                "similarity_score": round(best_score, 2),
                "combined_evidence": f"[RULE] {rf['evidence']} | [AI] {matched_ai['evidence']}",
                "combined_suggestion": rf["suggestion"]
                                      + ("\n" + matched_ai["suggestion"]
                                         if matched_ai["suggestion"] != rf["suggestion"] else ""),
                "confidence": "HIGH"
            })
        else:
            # Only the rule checker found this
            rule_only.append({
                "issue": rf["issue"],
                "severity": rf["severity"],
                "evidence": rf["evidence"],
                "suggestion": rf["suggestion"],
                "confidence": "MEDIUM (rule only)"
            })

    # Any remaining unmatched AI findings
    for i, af in enumerate(ai_findings):
        if not ai_matched[i]:
            ai_only.append({
                "issue": af["issue"],
                "severity": af["severity"],
                "evidence": af["evidence"],
                "suggestion": af["suggestion"],
                "confidence": "MEDIUM (AI only)"
            })

    # Build merged findings list (agreed first, then rule-only, then AI-only)
    merged = []
    for a in agreed:
        merged.append({
            "issue": a["rule_issue"] + " [AGREED]",
            "severity": a["severity"],
            "evidence": a["combined_evidence"],
            "suggestion": a["combined_suggestion"],
            "confidence": "HIGH",
            "group": "agreed"
        })
    for r in rule_only:
        merged.append({**r, "group": "rule_only"})
    for a in ai_only:
        merged.append({**a, "group": "ai_only"})

    # Overall confidence summary
    total_possible = len(rule_findings) + len(ai_findings)
    total_agreement = len(agreed) * 2  # each agreement covers 1 rule + 1 ai
    agreement_ratio = (total_agreement / total_possible) if total_possible > 0 else 0

    if agreement_ratio >= 0.7:
        overall = "HIGH CONFIDENCE - Rule checker and AI are mostly in agreement."
    elif agreement_ratio >= 0.3:
        overall = "MEDIUM CONFIDENCE - Some overlap; mixed findings need review."
    else:
        overall = "LOW CONFIDENCE - Rule checker and AI differ significantly; careful review needed."

    report = {
        "agreed_findings": agreed,
        "rule_only_findings": rule_only,
        "ai_only_findings": ai_only,
        "merged_findings": merged,
        "agreement_ratio": round(agreement_ratio, 2),
        "confidence_summary": overall
    }

    print_info(f"Comparison done: {len(agreed)} agreed, {len(rule_only)} rule-only, "
               f"{len(ai_only)} AI-only. Agreement ratio: {report['agreement_ratio']}")
    return report


# ============================================================
# Pretty Print the Comparison
# ============================================================

def print_comparison(report):
    """Print the comparison report to the console in a readable format."""
    print()
    print(f"{Colors.BOLD}{Colors.CYAN}======  COMPARISON REPORT  ======{Colors.RESET}")
    print(f"{Colors.BOLD}Summary: {report['confidence_summary']}{Colors.RESET}")
    print(f"  Agreement ratio: {report['agreement_ratio']}")
    print()

    if report["agreed_findings"]:
        print(f"{Colors.BOLD}{Colors.GREEN}--- Both Rule Checker + AI AGREE on these issues:{Colors.RESET}")
        for i, f in enumerate(report["agreed_findings"], 1):
            print(f"  {i}. [{f['severity'].upper()}] {f['rule_issue']}")
            print(f"     Evidence: {f['combined_evidence']}")
            print(f"     Suggestion: {f['combined_suggestion']}")
        print()

    if report["rule_only_findings"]:
        print(f"{Colors.BOLD}{Colors.YELLOW}--- Only RULE CHECKER found these:{Colors.RESET}")
        for i, f in enumerate(report["rule_only_findings"], 1):
            print(f"  {i}. [{f['severity'].upper()}] {f['issue']}")
            print(f"     Evidence: {f['evidence']}")
            print(f"     Suggestion: {f['suggestion']}")
        print()

    if report["ai_only_findings"]:
        print(f"{Colors.BOLD}{Colors.YELLOW}--- Only AI DIAGNOSIS found these:{Colors.RESET}")
        for i, f in enumerate(report["ai_only_findings"], 1):
            print(f"  {i}. [{f['severity'].upper()}] {f['issue']}")
            print(f"     Evidence: {f['evidence']}")
            print(f"     Suggestion: {f['suggestion']}")
        print()

    if not (report["agreed_findings"] or report["rule_only_findings"] or report["ai_only_findings"]):
        print("  (No findings from either source.)")
