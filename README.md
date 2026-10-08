# NetSage AI — Student Project

**Version 1.0 — Simple Python CLI with Mock AI**

> AI-assisted network troubleshooting system that combines:
> Cisco Packet Tracer evidence → Python rule-based validation + AI diagnosis →
> compared findings → **mandatory human review** → verified fix.

---

## ⚠️ Core Principle (Non-Negotiable)

**THE AI NEVER AUTOMATICALLY APPLIES A NETWORK FIX.**

Every diagnosis must pass through a human reviewer who explicitly chooses:

1. **ACCEPTED** → use the AI+Rule findings as-is
2. **EDITED** → human modifies the recommendation
3. **REJECTED** → throw it away, gather more evidence, try again

Only after a human decision is logged does the system produce a report.
The human then manually applies changes inside Cisco Packet Tracer.

---

## System Flow (v1)

```
Packet Tracer Case (cases.csv)
        │
        ▼
┌──────────────────────┐    ┌──────────────────────┐
│  Python Rule Checker │    │  AI Diagnosis (mock) │
│  (hard-coded rules)  │    │  (keyword heuristics)│
└──────────┬───────────┘    └──────────┬───────────┘
           │                           │
           └──────────────┬────────────┘
                          ▼
                  Comparator (agreements / disagreements)
                          │
                          ▼
              ┌───────────────────────┐
              │  MANDATORY Human      │
              │  Review (CLI prompts) │
              │  A / E / R choice     │
              └───────────┬───────────┘
                          │
                          ▼
                  Recommended Fix saved to results/
                          │
                          ▼
            Human applies fix in Packet Tracer
                          │
                          ▼
                  Manual verification
```

---

## Project Structure

```
NetSage-AI/
│
├── src/                         # Core logic (all the Python)
│   ├── main.py                  # Entry point — runs the full workflow
│   ├── rule_checker.py          # Python rule-based validation
│   ├── ai_diagnosis.py          # AI diagnosis (mock in v1)
│   ├── comparator.py            # Compares rule vs AI findings
│   ├── human_review.py          # Mandatory Accepted/Edited/Rejected step
│   └── utils.py                 # Shared helpers (CSV, colors, timestamps)
│
├── data/
│   ├── cases.csv                # Your input: troubleshooting scenarios
│   └── review_log.csv           # Appended: every human review decision
│
├── prompts/
│   └── diagnose_prompt.md       # AI prompt template (used in v2+)
│
├── packet_tracer/               # Put your .pkt files and evidence notes here
│   └── README.md
│
├── results/                     # Saved reports after human review
│   └── README.md
│
├── requirements.txt             # Python dependencies (empty for v1)
└── README.md                    # This file
```

---

## Quick Start

### 1. Requirements

- **Python 3.8+** (comes with `csv`, `os`, `datetime` — all we need in v1)
- No pip installs required in Version 1!

### 2. Run the program

From the project root folder:

```bash
python src/main.py
```

You'll see a menu of cases from `data/cases.csv`. Pick a case number.

**Useful flags:**

```bash
# Run a specific case directly:
python src/main.py C001

# Demo mode — auto-accepts the review (great for quick testing without typing):
python src/main.py C002 --demo
```

### 3. Add your own case

Open `data/cases.csv` in Excel / VS Code / a text editor.
Add a new row with:
- `case_id` — unique label like `C006`
- `symptoms` — what's broken
- `topology` — brief description of the network
- `show_commands` — output from relevant Cisco commands (use `\n` for newlines if pasting raw)
- `expected_fix` — optional hint for learning/verification

---

## How to Verify after Diagnosis

1. After the human review step, open the report created in `results/case_<id>_..._report.txt`
2. Open the matching Packet Tracer `.pkt` scenario (save your `.pkt` files in the `packet_tracer/` folder)
3. Apply each suggested fix command by command
4. Verify connectivity:
   - Ping between the affected devices
   - Check interface status with `show ip interface brief`
   - Confirm the original symptoms are gone
5. (Optional) Re-run NetSage AI with post-fix evidence and confirm no issues found

---

## Roadmap for v2+

- [ ] **Real AI API integration** (OpenAI / Claude) in `ai_diagnosis.py` — swap the mock for an actual LLM call using the prompt template from `prompts/diagnose_prompt.md`
- [ ] **Direct Packet Tracer integration** (import .pkt or automate evidence collection)
- [ ] **Web-based UI** instead of CLI
- [ ] **Automatic post-fix verification** (re-run checker after fix is applied)
- [ ] **Custom rule editor** for non-Python users to add rules without coding
- [ ] **Stats dashboard** (agreement rates, accuracy, most common faults)

---

## Student Notes

- The **rule_checker.py** file is where you can add more rules as you learn new
  networking concepts! Each rule is a simple Python function.
- The **ai_diagnosis.py** file uses simple keyword matching in v1. In v2 you can
  swap in a real API without touching any other file.
- The **human_review.py** always logs every decision — this is your accountability
  trail. No changes happen silently.
