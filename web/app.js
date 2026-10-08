/* ============================================================
   NetSage AI — Web UI controller (vanilla JS, no frameworks)
   Talks to the local Python API served by web_server.py.
   ============================================================ */

(function () {
  "use strict";

  // ---------- element references ----------
  const $ = (id) => document.getElementById(id);
  const caseSelect    = $("caseSelect");
  const metaName      = $("metaName");
  const metaLayer     = $("metaLayer");
  const metaConcept   = $("metaConcept");
  const metaSeverity  = $("metaSeverity");
  const caseSymptomWrap = $("caseSymptomWrap");
  const caseSymptom   = $("caseSymptom");
  const runBtn        = $("runBtn");

  const processSection = $("processSection");
  const stages = {
    rule:    document.querySelector('.stage[data-stage="rule"]'),
    ai:      document.querySelector('.stage[data-stage="ai"]'),
    compare: document.querySelector('.stage[data-stage="compare"]'),
    review:  document.querySelector('.stage[data-stage="review"]'),
  };

  const resultsSection = $("resultsSection");
  const ruleFindingsEl = $("ruleFindings");
  const aiFindingsEl   = $("aiFindings");
  const agreementPct   = $("agreementPct");
  const agreementBar   = $("agreementBar");
  const confidenceBadge = $("confidenceBadge");
  const confidenceSummary = $("confidenceSummary");
  const countAgreed = $("countAgreed");
  const countRule   = $("countRule");
  const countAi     = $("countAi");
  const agreedFindings = $("agreedFindings");
  const ruleOnlyEl   = $("ruleOnly");
  const aiOnlyEl     = $("aiOnly");

  const reviewCard    = $("reviewCard");
  const reviewEditBlock = $("reviewEditBlock");
  const editedFindings = $("editedFindings");
  const reviewerNotes = $("reviewerNotes");
  const notesLabel    = $("notesLabel");
  const btnAccept     = $("btnAccept");
  const btnEdit       = $("btnEdit");
  const btnReject     = $("btnReject");
  const btnCancelEdit = $("btnCancelEdit");
  const reviewMessage = $("reviewMessage");

  // ---------- state ----------
  let cases = [];
  let currentData = null;   // last diagnose response
  let editingMode = false;  // has user clicked the Edit button to modify findings?

  // ---------- helpers ----------
  const api = async (path, options = {}) => {
    const res = await fetch(path, {
      headers: { "Accept": "application/json" },
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch (e) { throw new Error(`Non-JSON response: ${text.slice(0, 200)}`); }
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  };

  const escapeHtml = (s) => {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  const severityClass = (sev) =>
    (sev || "").toLowerCase() === "high"   ? "high"
    : (sev || "").toLowerCase() === "medium" ? "medium"
    : "low";

  // ---------- finding rendering ----------
  function renderFinding(f, opts = {}) {
    const sev = severityClass(f.severity);
    const issue = escapeHtml(f.issue || "(no issue)");
    const evidence = escapeHtml(f.evidence || "");
    const suggestion = escapeHtml(f.suggestion || "");
    const issueExtra = opts.extraIssue ?
      `<div class="finding-extra" style="font-size:12px;color:var(--fg-muted);margin-top:3px;">${escapeHtml(opts.extraIssue)}</div>` : "";
    return `
      <div class="finding">
        <div class="finding-head">
          <h4 class="finding-title">${issue}${issueExtra}</h4>
          <span class="severity ${sev}">${escapeHtml(f.severity || "low")}</span>
        </div>
        ${evidence ? `
          <div class="finding-field">
            <span class="finding-field-label">Evidence</span>
            <p class="finding-evidence">${evidence}</p>
          </div>` : ""}
        ${suggestion ? `
          <div class="finding-field">
            <span class="finding-field-label">Recommended Fix</span>
            <p class="finding-suggestion">${suggestion}</p>
          </div>` : ""}
      </div>
    `;
  }

  function renderAgreedFinding(a) {
    const sev = severityClass(a.severity);
    const issue = escapeHtml(a.rule_issue || "");
    const evidence = escapeHtml(a.combined_evidence || "");
    const suggestion = escapeHtml(a.combined_suggestion || "");
    const sim = a.similarity_score != null
      ? `<div class="finding-extra" style="font-size:12px;color:var(--fg-muted);margin-top:3px;">Similarity: ${escapeHtml(String(a.similarity_score))} · Confidence: HIGH</div>`
      : "";
    return `
      <div class="finding">
        <div class="finding-head">
          <h4 class="finding-title">${issue}${sim}</h4>
          <span class="severity ${sev}">${escapeHtml(a.severity || "high")}</span>
        </div>
        ${evidence ? `
          <div class="finding-field">
            <span class="finding-field-label">Combined Evidence (Rule + AI)</span>
            <p class="finding-evidence">${evidence}</p>
          </div>` : ""}
        ${suggestion ? `
          <div class="finding-field">
            <span class="finding-field-label">Recommended Fix</span>
            <p class="finding-suggestion">${suggestion}</p>
          </div>` : ""}
      </div>
    `;
  }

  function renderList(el, items, renderFn) {
    if (!items || items.length === 0) {
      el.innerHTML = `<div class="empty-state">No findings.</div>`;
      return;
    }
    el.innerHTML = items.map(renderFn).join("");
  }

  // ---------- stage animations ----------
  function setStageStatus(key, status, state /* ready|running|done|awaiting */) {
    const el = stages[key];
    if (!el) return;
    el.classList.remove("running", "done");
    if (state === "running") el.classList.add("running");
    else if (state === "done") el.classList.add("done");
    const s = el.querySelector("[data-status]");
    if (s) s.textContent = status;
  }
  function resetStages() {
    Object.keys(stages).forEach((k) => {
      setStageStatus(k, "Ready", "ready");
    });
    setStageStatus("review", "Awaiting", "ready");
  }

  async function runDiagnosisAnimated(caseId) {
    resetStages();
    processSection.hidden = false;
    resultsSection.hidden = true;
    reviewMessage.hidden = true;
    reviewEditBlock.hidden = true;
    btnCancelEdit.hidden = true;
    editingMode = false;

    // Tight visual sequencing: stage 1 then 2 then 3, with small delays
    // so the presenter can point to each box in a demo.
    setStageStatus("rule", "Running rule engine...", "running");
    await new Promise((r) => setTimeout(r, 350));
    setStageStatus("ai", "Running Mock AI diagnosis...", "running");
    await new Promise((r) => setTimeout(r, 350));
    setStageStatus("compare", "Comparing findings...", "running");

    // Call the real backend (same modules used by CLI)
    const resp = await api("/api/diagnose", {
      method: "POST",
      body: { case_id: caseId },
    });
    currentData = resp.data;

    setStageStatus("rule", "Complete", "done");
    setStageStatus("ai", "Complete", "done");
    setStageStatus("compare", "Complete", "done");
    setStageStatus("review", "Awaiting your decision", "ready");

    renderResults(currentData);
    resultsSection.hidden = false;
    reviewCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- results rendering ----------
  function renderResults(d) {
    // Rule findings
    renderList(ruleFindingsEl, d.rule_findings, (f) => renderFinding(f));
    // AI findings
    renderList(aiFindingsEl, d.ai_findings, (f) => renderFinding(f));

    // Comparison summary
    const ratio = d.comparison.agreement_ratio || 0;
    const pct = Math.round(Number(ratio) * 100);
    agreementPct.textContent = pct;
    agreementBar.style.width = pct + "%";

    const summary = d.comparison.confidence_summary || "";
    let level = "low";
    if (/HIGH/.test(summary)) level = "high";
    else if (/MEDIUM/.test(summary)) level = "medium";
    confidenceBadge.textContent = (level || "low").toUpperCase();
    confidenceBadge.className = "confidence-badge " + level;
    confidenceSummary.textContent = summary;

    countAgreed.textContent = d.comparison.agreed_findings.length;
    countRule.textContent   = d.comparison.rule_only_findings.length;
    countAi.textContent     = d.comparison.ai_only_findings.length;

    // Agreed findings
    renderList(agreedFindings, d.comparison.agreed_findings, renderAgreedFinding);

    // Rule-only and AI-only (same structure as plain findings)
    renderList(ruleOnlyEl, d.comparison.rule_only_findings,
      (f) => renderFinding(f, { extraIssue: `Confidence: ${f.confidence || "MEDIUM (rule only)"}` }));
    renderList(aiOnlyEl, d.comparison.ai_only_findings,
      (f) => renderFinding(f, { extraIssue: `Confidence: ${f.confidence || "MEDIUM (AI only)"}` }));

    // Populate editable findings textarea with the merged version
    editedFindings.value = d.merged_findings_text || "";
    reviewerNotes.value = "";
    notesLabel.textContent = "Reviewer notes (optional for Accept)";
  }

  // ---------- case selection ----------
  function renderCaseOptions(list) {
    caseSelect.innerHTML = "";
    // Surface demo-ready cases first
    const demo = list.filter((c) => c.demo_ready);
    const other = list.filter((c) => !c.demo_ready);
    const ordered = demo.concat(other);

    for (const c of ordered) {
      const opt = document.createElement("option");
      opt.value = c.case_id;
      opt.textContent = `${c.case_id} — ${c.case_name || "(no name)"}`;
      caseSelect.appendChild(opt);
    }
    refreshCaseMeta();
  }

  function refreshCaseMeta() {
    const cid = caseSelect.value;
    const c = cases.find((x) => x.case_id === cid);
    if (!c) {
      metaName.textContent = "—";
      metaLayer.textContent = "—";
      metaConcept.textContent = "—";
      metaSeverity.textContent = "—";
      metaSeverity.className = "sev";
      caseSymptomWrap.hidden = true;
      return;
    }
    metaName.textContent    = c.case_name || "—";
    metaLayer.textContent   = c.osi_layer || "—";
    metaConcept.textContent = c.concept_tag || "—";
    const sev = (c.severity || "").toLowerCase();
    metaSeverity.textContent = sev ? sev.toUpperCase() : "—";
    metaSeverity.className = "sev " + (sev || "");
    const symptom = c.symptom || "";
    if (symptom) {
      caseSymptom.textContent = symptom;
      caseSymptomWrap.hidden = false;
    } else {
      caseSymptomWrap.hidden = true;
    }
  }

  // ---------- human review actions ----------
  function showReviewMessage(kind, html) {
    reviewMessage.className = "review-message " + kind;
    reviewMessage.innerHTML = html;
    reviewMessage.hidden = false;
  }

  function setReviewButtons(locked) {
    for (const b of [btnAccept, btnEdit, btnReject]) b.disabled = !!locked;
  }

  function enterEditMode() {
    editingMode = true;
    reviewEditBlock.hidden = false;
    btnCancelEdit.hidden = false;
    notesLabel.textContent = "Reviewer notes (REQUIRED for Edit)";
    showReviewMessage("info",
      "Edit the proposed findings in the text box above. When ready, click <strong>Accept</strong> to submit the edited version.");
    editedFindings.focus();
  }

  function cancelEditMode() {
    editingMode = false;
    reviewEditBlock.hidden = true;
    btnCancelEdit.hidden = true;
    // restore the original merged text
    if (currentData) editedFindings.value = currentData.merged_findings_text || "";
    notesLabel.textContent = "Reviewer notes (optional for Accept)";
    reviewMessage.hidden = true;
  }

  async function submitDecision(decision) {
    if (!currentData) {
      showReviewMessage("error", "No diagnosis loaded — click <strong>Run Diagnosis</strong> first.");
      return;
    }
    const caseId = currentData.case_id;
    const notes = reviewerNotes.value.trim();
    let edited = null;

    if (decision === "EDITED") {
      // For Edit, submit the current textarea content as edited findings.
      edited = editedFindings.value;
      if (!edited || !edited.trim()) {
        showReviewMessage("error",
          "Findings text cannot be empty for Edit. Type your changes or click Cancel.");
        return;
      }
      if (!notes) {
        showReviewMessage("error", "Reviewer notes are required when editing findings.");
        return;
      }
    }
    if (decision === "REJECTED" && !notes) {
      showReviewMessage("error", "Reason for rejection is required. Add a note before submitting.");
      return;
    }

    setReviewButtons(true);
    try {
      const resp = await api("/api/review", {
        method: "POST",
        body: {
          case_id: caseId,
          decision,
          reviewer_notes: notes,
          edited_findings_text: edited,
        },
      });
      const dec = resp.decision || decision;
      if (resp.report_filename) {
        showReviewMessage("success",
          `<strong>${escapeHtml(dec)}</strong> recorded. Final report saved to <code>${escapeHtml(resp.report_filename)}</code> in results/.`);
      } else {
        showReviewMessage("success",
          `<strong>${escapeHtml(dec)}</strong> recorded and logged to <code>review_log.csv</code>.`);
      }
      // After Accept/Edit/Reject via the web, mark the review stage done.
      setStageStatus("review", dec, "done");
      // Keep buttons disabled for this run (user must click "Run Diagnosis" again
      // to start a fresh review of the same or different case).
    } catch (e) {
      showReviewMessage("error", `Failed to log review: ${escapeHtml(e.message)}`);
      setReviewButtons(false);
    }
  }

  // ---------- wiring ----------
  async function init() {
    runBtn.disabled = true;
    runBtn.textContent = "Loading cases...";
    try {
      const resp = await api("/api/cases");
      cases = resp.cases || [];
      renderCaseOptions(cases);
      runBtn.disabled = false;
      runBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Run Diagnosis
      `;
    } catch (e) {
      runBtn.disabled = true;
      runBtn.textContent = "Backend unreachable";
      alert(
        "Could not reach the NetSage AI backend.\n\n" +
        "Make sure the web server is running:\n" +
        "  python web_server.py\n\n" +
        "Then reload this page."
      );
      return;
    }

    caseSelect.addEventListener("change", refreshCaseMeta);
    runBtn.addEventListener("click", async () => {
      const cid = caseSelect.value;
      if (!cid) return;
      try {
        runBtn.disabled = true;
        setReviewButtons(false);
        await runDiagnosisAnimated(cid);
      } catch (e) {
        showReviewMessage && (reviewMessage.hidden = false);
        reviewMessage.className = "review-message error";
        reviewMessage.textContent = "Diagnosis failed: " + e.message;
        resultsSection.hidden = true;
        processSection.hidden = true;
      } finally {
        runBtn.disabled = false;
      }
    });

    btnAccept.addEventListener("click", () => {
      // If user clicked Edit earlier, submitting "Accept" after edits = EDITED decision.
      submitDecision(editingMode ? "EDITED" : "ACCEPTED");
    });
    btnEdit.addEventListener("click", () => {
      if (!currentData) return;
      enterEditMode();
    });
    btnCancelEdit.addEventListener("click", cancelEditMode);
    btnReject.addEventListener("click", () => submitDecision("REJECTED"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
