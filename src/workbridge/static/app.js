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
  const viewName = name === "predictor" ? "research" : name;
  $(".view").forEach(view => view.classList.toggle("active", view.id === `view-${viewName}`));
  $(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $("#crumb-current").textContent = ({research:"Research desk",predictor:"AI stock predictor",history:"Research history",benchmarks:"Benchmarks"})[name];
  if (name === "history") loadHistory();
  if (name === "benchmarks") loadBenchmarks();
  if (name === "predictor") {
    $("#stock-visualizer").scrollIntoView({behavior:"smooth", block:"start"});
    $("#stock-symbol-input")?.focus({preventScroll:true});
  }
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
    $("#provider-count").textContent = "Start QYRAVEX web server";
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
  const rawLimitations = report.limitations || [];
  const limitations = [...new Map(rawLimitations.map(item => [String(item).replace(/\\s+/g, " ").trim().toLowerCase(), item])).values()];
  $("#limitations").innerHTML = limitations.length ? limitations.map(item => {
    const raw = String(item);
    const isNewsLimit = /gdeltproject\\.org|news\\.google\\.com|news_search/i.test(raw);
    const friendly = (raw.includes("429") || raw.includes("cooldown active")) && isNewsLimit ? "News search was rate-limited. QYRAVEX tries Google News RSS as a live alternative; the news section may be incomplete if both sources are unavailable."
      : raw.includes("429") || raw.includes("cooldown active") ? "Market data was rate-limited. QYRAVEX tries Stooq as an alternate daily-price source; market metrics may be unavailable if both providers are unavailable."
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
    AMAZON: "AMZN", GOOGLE: "GOOGL", ALPHABET: "GOOGL", META: "META",
    SOUTHBANK: "SOUTHBANK.NS", "SOUTH INDIAN BANK": "SOUTHBANK.NS"
  };
  const companyMatch = Object.entries(alias).find(([name]) =>
    new RegExp("\\b" + name + "\\b", "i").test(question)
  );
  const ignoredTickerWords = new Set([
    "THE", "AND", "FOR", "WITH", "FROM", "WHAT", "HOW", "STOCK", "STOCKS",
    "NEWS", "LATEST", "ANALYZE", "ANALYSIS", "PRICE", "PERFORMANCE",
    "COMPANY", "SHARE", "SHARES", "ABOUT", "COMPARE", "RESEARCH"
  ]);
  const tickerMatch = question.toUpperCase().match(/\b[A-Z]{2,5}\b/g)
    ?.find(token => !ignoredTickerWords.has(token));
  const symbol = stockStep?.args?.symbol
    || (companyMatch ? alias[companyMatch[1]] : null)
    || tickerMatch;
  if (symbol) loadMarketChart(symbol, "1y", symbol);
  else {
    activeChartSymbol = null; activeChartData = null; activeChartQuote = null;
  }
  $("#results").scrollIntoView({behavior:"smooth",block:"start"});
}

let activeChartSymbol = null;
let activeChartPeriod = "1y";
let activeChartData = null;
let activeChartCurrency = "USD";
let activeChartQuote = null;
let activeForecastData = null;

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

function drawForecastChart(data) {
  const canvas = $("#stock-forecast-chart");
  const history = (activeChartData || []).slice(-60);
  if (!canvas || history.length < 2 || !data?.scenarios) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(300, rect.width);
  const height = Math.max(150, rect.height);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const values = history.map(point => Number(point.close)).concat([
    Number(data.scenarios.bear), Number(data.scenarios.base), Number(data.scenarios.bull)
  ]).filter(Number.isFinite);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || Math.max(Math.abs(max) * .02, 1);
  const low = min - span * .08, high = max + span * .08;
  const left = 56, right = 16, top = 12, bottom = 25;
  const x = index => left + index * (width - left - right) / history.length;
  const y = value => top + (high - value) * (height - top - bottom) / (high - low);
  const style = getComputedStyle(document.documentElement);
  const line = style.getPropertyValue("--green").trim() || "#176b4b";
  const grid = style.getPropertyValue("--line").trim() || "#e0e9df";
  ctx.font = "10px DM Mono, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 3; i++) {
    const value = high - (high - low) * i / 3;
    const py = y(value);
    ctx.beginPath(); ctx.moveTo(left, py); ctx.lineTo(width - right, py);
    ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = "#879187";
    ctx.fillText(new Intl.NumberFormat(undefined, {maximumFractionDigits:2}).format(value), left - 7, py);
  }
  const last = Number(history[history.length - 1].close);
  const endX = x(history.length);
  ctx.beginPath();
  ctx.moveTo(x(history.length - 1), y(last));
  ctx.lineTo(endX, y(data.scenarios.bull));
  ctx.lineTo(endX, y(data.scenarios.bear));
  ctx.closePath();
  ctx.fillStyle = line + "18";
  ctx.fill();
  ctx.beginPath();
  history.forEach((point, index) => index ? ctx.lineTo(x(index), y(Number(point.close))) : ctx.moveTo(x(index), y(Number(point.close))));
  ctx.strokeStyle = line; ctx.lineWidth = 2.1; ctx.lineJoin = "round"; ctx.stroke();
  ctx.setLineDash([5, 4]);
  ctx.beginPath(); ctx.moveTo(x(history.length - 1), y(last)); ctx.lineTo(endX, y(data.scenarios.base));
  ctx.strokeStyle = line; ctx.lineWidth = 2; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x(history.length - 1), y(last)); ctx.lineTo(endX, y(data.scenarios.bull));
  ctx.moveTo(x(history.length - 1), y(last)); ctx.lineTo(endX, y(data.scenarios.bear));
  ctx.strokeStyle = "#9aa69a"; ctx.lineWidth = 1.3; ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#879187"; ctx.textAlign = "left";
  ctx.fillText("Historical", left, height - 8);
  ctx.textAlign = "right";
  ctx.fillText("+" + data.horizon_trading_days + " trading days", width - right, height - 8);
}

async function loadMarketForecast(symbol, horizon = activeForecastHorizon) {
  activeForecastHorizon = horizon;
  const panel = $("#stock-forecast");
  if (!panel || !symbol) return;
  panel.hidden = false;
  $("#stock-forecast-status").textContent = "Calculating historical trend and retrieving current news evidence…";
  $("#stock-forecast-content").innerHTML = "";
  try {
    const data = await api("/api/market/" + encodeURIComponent(symbol) + "/forecast?horizon=" + horizon);
    activeForecastData = data;
    drawForecastChart(data);
    const currency = data.currency || "USD";
    const money = value => new Intl.NumberFormat(undefined, {style:"currency",currency,maximumFractionDigits:2}).format(value);
    const percent = value => (value >= 0 ? "+" : "") + (value * 100).toFixed(2) + "%";
    const scenarios = data.scenarios || {};
    const sources = data.sources || [];
    const news = data.news || {};
    const aiReview = data.ai_review || {};
    const aiPanels = (aiReview.analyses || []).map(item =>
      '<section class="forecast-ai-provider"><strong>' + escapeHtml(item.provider) +
      '</strong><p>' + escapeHtml(item.analysis) + '</p></section>'
    ).join("");
    $("#stock-forecast-status").textContent =
      (data.company || data.symbol) + " · " + horizon + " trading-day horizon · Built " +
      new Date(data.generated_at).toLocaleString() + " · " + data.method;
    const sourceLinks = sources.slice(0,8).map(source =>
      '<a href="' + escapeHtml(source.url) + '" target="_blank" rel="noopener">' +
      escapeHtml(source.name) + (source.published_at ? " · " + escapeHtml(source.published_at) : "") + " ↗</a>"
    ).join("");
    const limitations = (data.limitations || []).map(item => "<li>" + escapeHtml(item) + "</li>").join("");
    $("#stock-forecast-content").innerHTML =
      '<div class="forecast-summary">' +
        '<div class="forecast-lead"><span>MODEL OUTLOOK</span><strong>' + escapeHtml(data.outlook) +
        '</strong><small>Expected scenario return ' + escapeHtml(percent(data.expected_return)) + '</small></div>' +
        '<div class="forecast-metric"><span>BASE SCENARIO</span><strong>' + escapeHtml(money(scenarios.base)) +
        '</strong><small>Latest close ' + escapeHtml(money(data.latest_close)) + '</small></div>' +
        '<div class="forecast-metric"><span>BEAR SCENARIO</span><strong>' + escapeHtml(money(scenarios.bear)) +
        '</strong><small>Approximate lower range</small></div>' +
        '<div class="forecast-metric"><span>BULL SCENARIO</span><strong>' + escapeHtml(money(scenarios.bull)) +
        '</strong><small>Approximate upper range</small></div></div>' +
      '<div class="forecast-detail">' +
        '<span>20-session momentum <b>' + escapeHtml(percent(data.momentum_20d)) + '</b></span>' +
        '<span>60-session momentum <b>' + escapeHtml(percent(data.momentum_60d)) + '</b></span>' +
        '<span>Annualized volatility <b>' + escapeHtml((data.annualized_volatility * 100).toFixed(1)) + '%</b></span>' +
        '<span>Data coverage score <b>' + Math.round(data.confidence_score * 100) + '%</b></span>' +
        '<span>Historical direction hit rate <b>' +
          (data.backtest?.directional_accuracy == null ? "Insufficient test samples" :
            (data.backtest.directional_accuracy * 100).toFixed(1) + "% · " + data.backtest.samples + " tests") +
        '</b></span></div>' +
      '<p class="forecast-note">' + escapeHtml(data.range_level) + '. ' + escapeHtml(data.confidence_note) + '</p>' +
      '<div class="forecast-evidence"><strong>News evidence (' + Number(news.article_count || 0) +
        ' indexed articles)</strong><span>Headline signal: ' +
        (news.sentiment_score > 0 ? "positive-leaning" : news.sentiment_score < 0 ? "negative-leaning" : "mixed / neutral") +
        ' · Sources: ' + escapeHtml((news.providers || []).join(", ") || "No news provider returned articles") + '</span>' +
        (news.error ? '<small>News retrieval note: ' + escapeHtml(news.error) + '</small>' : "") +
        sourceLinks + '</div>' +
      '<div class="forecast-evidence"><strong>Independent AI research review</strong>' +
        '<span>Configured: ' + escapeHtml((aiReview.enabled_providers || []).join(", ") || "No AI API keys configured") +
        ' · Successful: ' + escapeHtml((aiReview.successful_providers || []).join(", ") || "No model responses") + '</span>' +
        (aiPanels || '<small>Add one or more AI provider keys to enable independent evidence reviews. The statistical forecast remains available without them.</small>') +
        ((aiReview.errors || []).length ? '<small>Provider errors: ' + escapeHtml(aiReview.errors.join(" · ")) + '</small>' : "") +
      '</div>' +
      '<details class="forecast-method"><summary>How this forecast is calculated and its limitations</summary><p>' +
        escapeHtml(data.method) + '</p><ul>' + limitations + '</ul></details>';
  } catch (error) {
    activeForecastData = null;
    $("#stock-forecast-status").textContent = "Forecast unavailable: " + error.message;
    $("#stock-forecast-content").innerHTML = '<p class="muted">The historical chart can still be used. Forecasting requires a valid daily price series with at least 21 observations.</p>';
  }
}

async function loadMarketChart(symbol, period = activeChartPeriod, searchQuery = symbol) {
  const searchTerm = String(searchQuery || symbol || "").trim();
  if (!searchTerm) return;
  activeChartPeriod = period;
  const panel = $("#stock-visualizer");
  panel.hidden = false;
  $("#stock-chart-status").textContent = 'Verifying "' + searchTerm + '" against the live stock directory…';
  $("#stock-candidates").hidden = true;
  $("#stock-candidates").innerHTML = "";
  $("#stock-chart-summary").textContent = "";
  $("#stock-forecast").hidden = true;
  try {
    let resolvedSymbol = String(symbol || searchTerm).trim().toUpperCase();
    let identity = null;
    try {
      const search = await api("/api/market/search?q=" + encodeURIComponent(searchTerm));
      const matches = (search.matches || []).filter(item => item.quote_type === "EQUITY" || item.quote_type === "ETF");
      const normalized = searchTerm.toUpperCase();
      identity = matches.find(item => item.symbol.toUpperCase() === normalized) || null;
      if (!identity && matches.length > 1) {
        const selector = $("#stock-candidates");
        selector.innerHTML = '<option value="">Choose the correct exchange listing…</option>' +
          matches.map(item => '<option value="' + escapeHtml(item.symbol) + '">' +
            escapeHtml(item.symbol + " — " + item.name + " (" + item.exchange + ")") + '</option>').join("");
        selector.hidden = false;
        $("#stock-chart-status").textContent = "Several listed instruments match. Choose the correct company and exchange above before loading its chart.";
        return;
      }
      if (!identity && matches.length === 1) identity = matches[0];
      if (identity) resolvedSymbol = identity.symbol;
      else if (!/^[A-Z0-9][A-Z0-9.=-]{0,14}$/i.test(searchTerm)) {
        throw new Error('No listed stock matched "' + searchTerm + '". Try its exchange ticker, e.g. RELIANCE.NS.');
      }
    } catch (lookupError) {
      if (!/^[A-Z0-9][A-Z0-9.=-]{0,14}$/i.test(searchTerm)) throw lookupError;
      console.warn("Symbol directory lookup unavailable; trying supplied ticker:", lookupError.message);
    }
    activeChartSymbol = resolvedSymbol;
    $("#stock-chart-status").textContent = "Loading verified listing " + resolvedSymbol + "…";
    const data = await api("/api/market/" + encodeURIComponent(resolvedSymbol) + "?period=" + encodeURIComponent(period));
    activeChartSymbol = data.symbol || resolvedSymbol;
    activeChartData = data.points;
    activeChartCurrency = data.currency;
    activeChartQuote = data.live_quote || null;
    drawStockChart(activeChartData, activeChartCurrency, activeChartQuote);
    const last = new Date(data.latest.timestamp * 1000).toLocaleString();
    const company = data.company || (identity && identity.name) || "";
    const exchange = data.exchange || (identity && identity.exchange) || "";
    const sourceUrl = data.source_url || (identity && identity.source_url) || "https://finance.yahoo.com/quote/" + encodeURIComponent(data.symbol);
    $("#stock-chart-status").innerHTML = (company ? escapeHtml(company) + " · " : "") +
      escapeHtml(data.symbol) + (exchange ? " · " + escapeHtml(exchange) : "") + " · " +
      escapeHtml(data.provider) + " · " + period.toUpperCase() + " · Latest observation " +
      escapeHtml(last) + ' · <a href="' + escapeHtml(sourceUrl) + '" target="_blank" rel="noopener">Verify source ↗</a>';
    $("#stock-symbol-input").value = data.symbol || resolvedSymbol;
    await loadMarketForecast(activeChartSymbol, activeForecastHorizon);
  } catch (error) {
    activeChartData = null;
    $("#stock-chart-status").textContent = "Market chart unavailable: " + error.message;
    $("#stock-chart-summary").textContent = "No verified daily price observations were returned. Check the company name or exchange-qualified ticker.";
    $("#stock-forecast").hidden = true;
  }
}

let activeForecastHorizon = 20;
$("#stock-load")?.addEventListener("click", () => {
  const query = $("#stock-symbol-input").value.trim();
  if (!query) { toast("Enter a company name or ticker first."); return; }
  loadMarketChart(query, activeChartPeriod, query);
});
$("#stock-symbol-input")?.addEventListener("keydown", event => {
  if (event.key === "Enter") $("#stock-load").click();
});
$("#stock-candidates")?.addEventListener("change", event => {
  if (event.target.value) loadMarketChart(event.target.value, activeChartPeriod, event.target.value);
});
$("#stock-visualizer [data-chart-refresh]")?.addEventListener("click", () => {
  if (activeChartSymbol) loadMarketChart(activeChartSymbol, activeChartPeriod);
});
$$("[data-chart-period]").forEach(button => {
  button.addEventListener("click", () => {
    if (activeChartSymbol) loadMarketChart(activeChartSymbol, button.dataset.chartPeriod);
  });
});
$$("[data-forecast-horizon]").forEach(button => {
  button.addEventListener("click", () => {
    if (activeChartSymbol) loadMarketForecast(activeChartSymbol, Number(button.dataset.forecastHorizon));
  });
});
window.addEventListener("resize", () => {
  if (activeChartData) drawStockChart(activeChartData, activeChartCurrency, activeChartQuote);
  if (activeForecastData) drawForecastChart(activeForecastData);
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
