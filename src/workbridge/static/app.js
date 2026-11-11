const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let latestReport = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 2600);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload;
}
function showView(name) {
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $("#crumb-current").textContent = ({research:"Research desk",history:"Research history",benchmarks:"Benchmarks"})[name];
  if (name === "history") loadHistory();
  if (name === "benchmarks") loadBenchmarks();
}
$$(".nav-item").forEach(button => button.addEventListener("click", () => showView(button.dataset.view)));
$$(".hint").forEach(button => button.addEventListener("click", () => { $("#question").value = button.dataset.prompt; $("#question").focus(); }));
async function loadStatus() {
  try {
    const data = await api("/api/status");
    $("#system-status").textContent = data.status === "online" ? "Core services online" : "Service degraded";
    const providers = data.providers || {};
    const active = Object.values(providers).filter(Boolean).length;
    $("#provider-count").textContent = `${active} of ${Object.keys(providers).length} sources available`;
    $("#provider-list").innerHTML = Object.entries(providers).map(([name, enabled]) =>
      `<div class="provider-row"><span>${escapeHtml(name.replaceAll("_"," ").toUpperCase())}</span><i class="${enabled ? "available" : "off"}">${enabled ? "Available" : "Not configured"}</i></div>`
    ).join("");
  } catch (error) {
    $("#system-status").textContent = "API unavailable";
    $("#provider-count").textContent = "Start WorkBridge web server";
    $("#provider-list").innerHTML = '<div class="empty-state">Could not reach the research API.</div>';
  }
}
function renderMetrics(metrics, evidence) {
  const items = [
    ["EVIDENCE ITEMS", evidence.length, "Source-backed records"],
    ["UNIQUE SOURCES", metrics.unique_sources || 0, "Distinct source names"],
    ["TOOL CALLS", metrics.tool_calls || 0, "Agent actions"],
    ["CONFLICTS", metrics.conflict_count || 0, "Need human review"]
  ];
  $("#metric-grid").innerHTML = items.map(([label,value,note]) =>
    `<div class="metric-card"><span>${label}</span><strong>${Number(value).toLocaleString()}</strong><small>${note}</small></div>`
  ).join("");
}
function renderReport(data) {
  latestReport = data;
  const report = data.report || {};
  const evidence = report.evidence || [];
  $("#results").classList.remove("hidden");
  $("#result-title").textContent = report.question || "Research report";
  const failedSteps = (data.observations || []).filter(item => !item.success).length;\n  $("#result-state").textContent = !evidence.length ? "NO EVIDENCE · REVIEW" : failedSteps ? "PARTIAL · REVIEW GAPS" : "COMPLETE · EVIDENCE COLLECTED";\n  $("#result-state").className = `result-state ${!evidence.length || failedSteps ? "degraded" : "complete"}`;
  const reportMetrics = report.metrics || {};\n  renderMetrics({...data.metrics, ...reportMetrics, tool_calls: data.metrics?.tool_calls || 0}, evidence);
  $("#summary-text").textContent = report.executive_summary || "The run did not return an executive summary.";
  const limitations = report.limitations || [];
  $("#limitations").innerHTML = limitations.length ? limitations.map(item => {
    const raw = String(item);
    const friendly = raw.includes("429") ? "Market data provider is temporarily rate limiting requests. Retry later; SEC filings and reported financials may still be available."
      : raw.includes("API_KEY") || raw.includes("not configured") ? "An optional data source is not configured. Add its API key to enable this enrichment."
      : raw.startsWith("Optional sources not configured:") ? raw
      : raw.length > 190 ? raw.slice(0, 187) + "…"
      : raw;
    return `<details class="limitation"><summary>${escapeHtml(friendly)}</summary><p class="limitation-detail">${escapeHtml(raw)}</p></details>`;
  }).join("") : '<div class="provider-note">No provider or parsing failures were recorded.</div>';
  const observations = data.observations || [];
  $("#execution-list").innerHTML = observations.length ? observations.map(item => {
    const rawError = String(item.error || "");
    const shortError = rawError.includes("429") ? "Rate limited by market-data provider"
      : rawError.includes("API_KEY") ? "API key missing"
      : rawError.includes("not configured") ? "Provider not configured"
      : rawError.includes("Skipped:") ? "Skipped · prerequisite unavailable"
      : rawError ? rawError.split(/[\\n:]/).slice(0, 2).join(": ").slice(0, 90)
      : item.cached ? "Retrieved from local memory" : "Completed successfully";
    const latency = Number(item.latency_ms || 0);
    return `<details class="execution-item ${item.success ? "success" : "failure"}">
      <summary><span class="execution-mark ${item.success ? "" : "fail"}">${item.success ? "✓" : "!"}</span>
      <span class="execution-copy"><b>${escapeHtml(item.tool.replaceAll("_"," "))}</b><small>${escapeHtml(shortError)}</small></span>
      <small class="execution-time">${latency < 1000 ? `${latency.toFixed(0)} ms` : `${(latency/1000).toFixed(1)} s`}</small></summary>
      ${rawError ? `<p class="execution-detail">${escapeHtml(rawError)}</p>` : item.warnings?.length ? `<p class="execution-detail">${escapeHtml(item.warnings.join("; "))}</p>` : ""}
    </details>`;
  }).join("") : '<div class="empty-state">No execution steps were returned.</div>';
  $("#evidence-count").textContent = `${evidence.length} items`;
  $("#evidence-list").innerHTML = evidence.length ? evidence.map(item =>
    `<div class="evidence-item"><div><strong>${escapeHtml(item.statement)}</strong><p>${escapeHtml(item.entity || "Entity not specified")} · ${escapeHtml(item.period || "Period not specified")} · Confidence ${Math.round((item.confidence || 0)*100)}%</p>${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">Open source ↗</a>` : ""}</div><span class="source-pill">${escapeHtml(item.source)}</span></div>`
  ).join("") : '<div class="empty-state">No source-backed evidence was collected in this run. Review limitations and provider availability above.</div>';
  const findings = report.findings || [];
  $("#findings-list").innerHTML = findings.map(item => `<div class="finding">${escapeHtml(item)}</div>`).join("") || '<div class="empty-state">No findings available.</div>';
  $("#results").scrollIntoView({behavior:"smooth",block:"start"});
}
async function runResearch() {
  const question = $("#question").value.trim();
  if (question.length < 4) { toast("Enter a longer research question."); return; }
  const button = $("#run-research");
  button.disabled = true;
  button.innerHTML = '<span>Researching…</span><span class="arrow">◌</span>';
  $("#result-state").textContent = "RUNNING";
  try {
    const data = await api("/api/research", {
      method:"POST",
      body:JSON.stringify({question,max_steps:Number($("#max-steps").value)})
    });
    renderReport(data);
    toast(data.report?.evidence?.length ? "Research run completed." : "Run completed with no source-backed evidence.");
    loadStatus();
  } catch (error) {
    toast(error.message);
    $("#result-state").textContent = "FAILED";
  } finally {
    button.disabled = false;
    button.innerHTML = '<span>Run research</span><span class="arrow">↗</span>';
  }
}
$("#run-research").addEventListener("click", runResearch);
$("#question").addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runResearch();
});
$("#copy-report").addEventListener("click", async () => {
  if (!latestReport) return;
  const report = latestReport.report;
  const text = [
    report.question, "", report.executive_summary, "", "FINDINGS",
    ...(report.findings || []).map(item => "- " + item), "", "LIMITATIONS",
    ...(report.limitations || []).map(item => "- " + item)
  ].join("\n");
  try { await navigator.clipboard.writeText(text); toast("Summary copied to clipboard."); }
  catch { toast("Clipboard access is unavailable in this browser."); }
});
async function loadHistory() {
  const node = $("#history-list");
  node.innerHTML = '<div class="empty-state">Loading saved sessions…</div>';
  try {
    const data = await api("/api/history");
    node.innerHTML = data.runs.length ? data.runs.map(run =>
      `<div class="history-row"><div><strong>${escapeHtml(run.question)}</strong><p>${escapeHtml(run.summary)}</p></div><time>${escapeHtml(run.created_at)}</time></div>`
    ).join("") : '<div class="empty-state">No saved research sessions yet. Run a query to create your first entry.</div>';
  } catch (error) { node.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
}
async function loadBenchmarks() {
  const list = $("#benchmark-list");
  list.innerHTML = '<div class="empty-state">Running offline checks…</div>';
  try {
    const data = await api("/api/benchmarks");
    $("#benchmark-summary").innerHTML = `<div class="metric-card"><span>CHALLENGES PASSED</span><strong>${data.passed}/${data.total}</strong><small>Deterministic offline suite</small></div><div class="metric-card"><span>PASS RATE</span><strong>${Math.round(data.passed/data.total*100)}%</strong><small>Latest benchmark run</small></div>`;
    list.innerHTML = data.challenges.map(item =>
      `<div class="benchmark-row"><div><strong>${escapeHtml(item.id)} · ${escapeHtml(item.title)}</strong><p>${escapeHtml(item.description)}</p></div><span class="${item.passed ? "pass-label" : "fail-label"}">${item.passed ? "PASS ✓" : "FAIL !"}</span></div>`
    ).join("");
  } catch (error) { list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
}
$("#refresh-benchmarks").addEventListener("click", loadBenchmarks);
loadStatus();
