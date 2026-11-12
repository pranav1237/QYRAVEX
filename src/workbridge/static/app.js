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
    $("#provider-count").textContent = `${active} public data sources supported`;
    $("#provider-list").innerHTML = Object.entries(providers).map(([name, enabled]) =>
      `<div class="provider-row"><span>${escapeHtml(name.replaceAll("_"," ").toUpperCase())}</span><i class="${enabled ? "available" : "off"}">${enabled ? "Connected" : (name.includes("optional") ? "Optional · not enabled" : "Unavailable")}</i></div>`
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
  const failedSteps = (data.observations || []).filter(item => !item.success).length;
  $("#result-state").textContent = !evidence.length ? "NO EVIDENCE · REVIEW" : failedSteps ? "PARTIAL · REVIEW GAPS" : "COMPLETE · EVIDENCE COLLECTED";
  $("#result-state").className = `result-state ${!evidence.length || failedSteps ? "degraded" : "complete"}`;
  const reportMetrics = report.metrics || {};
  renderMetrics({...data.metrics, ...reportMetrics, tool_calls: data.metrics?.tool_calls || 0}, evidence);
  $("#summary-text").textContent = report.executive_summary || "The run did not return an executive summary.";
  const limitations = report.limitations || [];
  $("#limitations").innerHTML = limitations.length ? limitations.map(item => {
    const raw = String(item);
    const isNewsLimit = /gdeltproject\\.org|news\\.google\\.com|news_search/i.test(raw);
    const friendly = (raw.includes("429") || raw.includes("cooldown active")) && isNewsLimit ? "News search was rate-limited. WorkBridge tries Google News RSS as a live alternative; the news section may be incomplete if both sources are unavailable."
      : raw.includes("429") || raw.includes("cooldown active") ? "Market data was rate-limited. WorkBridge tries Stooq as an alternate daily-price source; market metrics may be unavailable if both providers are unavailable."
      : raw.includes("API_KEY") || raw.includes("not configured") ? "An optional data source is not configured. Add its API key to enable this enrichment."
      : raw.startsWith("Optional sources not configured:") ? ""
      : raw.length > 190 ? raw.slice(0, 187) + "…"
      : raw;
    if (raw.startsWith("Optional sources not configured:")) return "";
    return `<details class="limitation"><summary>${escapeHtml(friendly)}</summary><p class="limitation-detail">${escapeHtml(raw)}</p></details>`;
  }).filter(Boolean).join("") || '<div class="provider-note">No required data sources are missing.</div>' : '<div class="provider-note">No provider or parsing failures were recorded.</div>';
  const observations = data.observations || [];
  $("#execution-list").innerHTML = observations.length ? observations.map(item => {
    const rawError = String(item.error || "");
    const shortError = (rawError.includes("429") || rawError.includes("cooldown active")) && item.tool === "news_search" ? "News providers rate-limited · fallback exhausted"
      : rawError.includes("429") || rawError.includes("cooldown active") ? "Market providers rate-limited · fallback exhausted"
      : item.warnings?.length ? "Completed with live-source fallback"
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
    `<div class="evidence-item"><div><strong>${escapeHtml(item.statement)}</strong><p>${escapeHtml(item.entity || "Entity not specified")} · ${escapeHtml(item.period || "Period not specified")} · Retrieved ${item.retrieved_at ? new Date(item.retrieved_at).toLocaleString() : "time unavailable"} · Confidence ${Math.round((item.confidence || 0)*100)}%</p>${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">Open source ↗</a>` : ""}</div><span class="source-pill">${escapeHtml(item.source)}</span></div>`
  ).join("") : '<div class="empty-state">No source-backed evidence was collected in this run. Review limitations and provider availability above.</div>';
  const findings = report.findings || [];
  $("#findings-list").innerHTML = findings.map(item => `<div class="finding">${escapeHtml(item)}</div>`).join("") || '<div class="empty-state">No findings available.</div>';
  const stockStep = (data.plan?.steps || []).find(step => step.tool === "technical_summary");
  const question = String(report.question || "");
  const alias = {
    APPLE: "AAPL", MICROSOFT: "MSFT", NVIDIA: "NVDA", TESLA: "TSLA",
    AMAZON: "AMZN", GOOGLE: "GOOGL", ALPHABET: "GOOGL", META: "META"
  };
  const companyMatch = Object.entries(alias).find(([name]) =>
    new RegExp("\\b" + name + "\\b", "i").test(question)
  );
  const ignoredTickerWords = new Set([
    "THE", "AND", "FOR", "WITH", "FROM", "WHAT", "HOW", "STOCK", "STOCKS",
    "NEWS", "LATEST", "ANALYZE", "ANALYSIS", "PRICE", "PERFORMANCE",
    "COMPANY", "SHARE", "SHARES", "ABOUT", "COMPARE", "RESEARCH"
  ]);
  const tickerMatch = question.toUpperCase().match(/\b[A-Z]{1,5}\b/g)
    ?.find(token => !ignoredTickerWords.has(token));
  const symbol = stockStep?.args?.symbol
    || (companyMatch ? alias[companyMatch[1]] : null)
    || tickerMatch;
  if (symbol) loadMarketChart(symbol, "1y");
  else {
    const chart = $("#stock-visualizer");
    if (chart) chart.hidden = true;
    activeChartSymbol = null; activeChartData = null; activeChartQuote = null;
  }
  $("#results").scrollIntoView({behavior:"smooth",block:"start"});
}

let activeChartSymbol = null;
let activeChartPeriod = "1y";
let activeChartData = null;
let activeChartCurrency = "USD";
let activeChartQuote = null;

function drawStockChart(points, currency, liveQuote = activeChartQuote) {
  const canvas = $("#stock-chart");
  if (!canvas || !points?.length) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(320, rect.width);
  const height = Math.max(180, rect.height);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const values = points.map(point => Number(point.close)).filter(Number.isFinite);
  if (values.length < 2) return;
  const left = 58, right = 14, top = 14, bottom = 28;
  const min = Math.min(...values), max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.02, 1);
  const low = min - spread * 0.08, high = max + spread * 0.08;
  const x = index => left + index * (width - left - right) / (values.length - 1);
  const y = value => top + (high - value) * (height - top - bottom) / (high - low);
  const style = getComputedStyle(document.documentElement);
  const lineColor = style.getPropertyValue("--green").trim() || "#176b4b";
  const gridColor = style.getPropertyValue("--line").trim() || "#e0e9df";
  ctx.font = "10px DM Mono, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const value = high - (high - low) * i / 4;
    const py = y(value);
    ctx.beginPath(); ctx.moveTo(left, py); ctx.lineTo(width - right, py);
    ctx.strokeStyle = gridColor; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#879187";
    ctx.fillText(new Intl.NumberFormat(undefined, {maximumFractionDigits: 2}).format(value), left - 8, py);
  }
  const gradient = ctx.createLinearGradient(0, top, 0, height - bottom);
  gradient.addColorStop(0, lineColor + "30");
  gradient.addColorStop(1, lineColor + "00");
  ctx.beginPath();
  values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
  ctx.lineTo(x(values.length - 1), height - bottom);
  ctx.lineTo(x(0), height - bottom);
  ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath();
  values.forEach((value, index) => index ? ctx.lineTo(x(index), y(value)) : ctx.moveTo(x(index), y(value)));
  ctx.strokeStyle = lineColor; ctx.lineWidth = 2.2; ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.stroke();
  const first = points[0], last = points[points.length - 1];
  const startDate = new Date(first.timestamp * 1000);
  const endDate = new Date(last.timestamp * 1000);
  ctx.fillStyle = "#879187"; ctx.textAlign = "left";
  ctx.fillText(startDate.toLocaleDateString(), left, height - 9);
  ctx.textAlign = "right";
  ctx.fillText(endDate.toLocaleDateString(), width - right, height - 9);
  const change = (Number(last.close) / Number(first.close) - 1) * 100;
  const money = value => new Intl.NumberFormat(undefined, {style:"currency",currency:currency || "USD",maximumFractionDigits:2}).format(value);
  $("#stock-chart-summary").innerHTML =
    `<span>Latest close <b>${escapeHtml(money(last.close))}</b></span><span>Period change <b>${change >= 0 ? "+" : ""}${change.toFixed(2)}%</b></span><span>${values.length} daily observations</span>` +
    (liveQuote?.price != null ? `<span>Live quote <b>${escapeHtml(money(liveQuote.price))}</b> · ${escapeHtml(liveQuote.change_percent ?? 0)}%</span>` : "");
}

async function loadMarketChart(symbol, period = activeChartPeriod) {
  activeChartSymbol = symbol;
  activeChartPeriod = period;
  const panel = $("#stock-visualizer");
  panel.hidden = false;
  $("#stock-chart-status").textContent = `Loading ${symbol} live daily prices…`;
  try {
    const data = await api(`/api/market/${encodeURIComponent(symbol)}?period=${encodeURIComponent(period)}`);
    activeChartData = data.points;
    activeChartCurrency = data.currency;
    activeChartQuote = data.live_quote || null;
    drawStockChart(activeChartData, activeChartCurrency, activeChartQuote);
    const last = new Date(data.latest.timestamp * 1000).toLocaleString();
    $("#stock-chart-status").textContent = `${data.symbol} · ${data.provider} · ${period.toUpperCase()} · Latest observation ${last}`;
  } catch (error) {
    $("#stock-chart-status").textContent = `Market chart unavailable: ${error.message}`;
    $("#stock-chart-summary").textContent = "No chart was drawn because live price observations could not be retrieved.";
  }
}

$("#stock-visualizer [data-chart-refresh]")?.addEventListener("click", () => {
  if (activeChartSymbol) loadMarketChart(activeChartSymbol, activeChartPeriod);
});

$$("#stock-visualizer [data-chart-period]").forEach(button => {
  button.addEventListener("click", () => {
    if (activeChartSymbol) loadMarketChart(activeChartSymbol, button.dataset.chartPeriod);
  });
});
window.addEventListener("resize", () => {
  if (activeChartData) drawStockChart(activeChartData, activeChartCurrency, activeChartQuote);
});

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
