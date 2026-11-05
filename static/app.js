const form = document.querySelector("#research-form");
const statusBox = document.querySelector("#status");
const resultsBox = document.querySelector("#results");
const dateInput = document.querySelector("#meeting-date");

function localDateString() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}
dateInput.value = localDateString();
dateInput.min = dateInput.value;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}
function safeSourceUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch {
    return "#";
  }
}
function renderList(items) {
  if (!Array.isArray(items) || !items.length) return "<p class='muted'>No supported items identified.</p>";
  return "<ul>" + items.map(item => "<li>" + escapeHtml(typeof item === "string" ? item : JSON.stringify(item)) + "</li>").join("") + "</ul>";
}
function render(data) {
  const b = data.briefing || {};
  const developments = (b.key_developments || []).map(item => {
    const refs = Array.isArray(item.source_numbers) ? item.source_numbers : [];
    const citations = refs.map(number => {
      const source = data.sources[number - 1];
      return source ? `<a href="${safeSourceUrl(source.url)}" target="_blank" rel="noopener noreferrer">[${number}]</a>` : "";
    }).join(" ");
    return `<article class="development">
      <h3>${escapeHtml(item.title || "Development")}</h3>
      <p>${escapeHtml(item.detail || "")}</p>
      <p><strong>Why it matters:</strong> ${escapeHtml(item.why_it_matters || "")}</p>
      <small>Evidence: ${citations || "No source reference supplied"}</small>
    </article>`;
  }).join("");
  const assessmentByNumber = new Map((b.source_assessments || []).map(item => [item.source_number, item]));
  const sources = (data.sources || []).map((source, index) => {
    const assessment = assessmentByNumber.get(index + 1);
    const relevance = assessment ? assessment.relevance : "unassessed";
    const reason = assessment && assessment.reason ? `<p>${escapeHtml(assessment.reason)}</p>` : "";
    return `<div class="source"><strong>[${index + 1}] ${escapeHtml(relevance.toUpperCase())}</strong> <a href="${safeSourceUrl(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.title)}</a><p>${escapeHtml(source.published_date)}</p>${reason}</div>`;
  }).join("");
  resultsBox.innerHTML = `
    <div class="result-heading"><div><p class="eyebrow">YOUR MEETING BRIEFING</p><h2>${escapeHtml(data.company)}</h2></div><button class="print-button" type="button" onclick="window.print()">Print / Save PDF</button></div>
    <p class="muted">Meeting: ${escapeHtml(data.meeting_date)} · Evidence window: ${escapeHtml(data.window_start)} – ${escapeHtml(data.window_end)}</p>
    <h3>Executive summary</h3><p>${escapeHtml(b.executive_summary || "No summary available.")}</p>
    <h3>Key developments</h3>${developments || "<p>No developments extracted.</p>"}
    <h3>Discussion points</h3>${renderList(b.discussion_points)}
    <h3>Open questions</h3>${renderList(b.open_questions)}
    <h3>Opportunities</h3>${renderList(b.opportunities)}
    <h3>Risks</h3>${renderList(b.risks)}
    <h3>Research gaps</h3>${renderList(b.research_gaps)}
    <h3>Sources (${(data.sources || []).length} dated)</h3>${sources}
    <p class="notice">AI-generated research can be incomplete. Open the sources and verify important claims independently before relying on this briefing.</p>
    ${data.undated_sources_count ? `<p class="muted">${data.undated_sources_count} additional search result(s) had no usable publication date and were excluded from the AI analysis.</p>` : ""}
  `;
  resultsBox.hidden = false;
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  statusBox.textContent = "Searching recent sources and preparing your briefing…";
  resultsBox.hidden = true;
  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        company: document.querySelector("#company").value.trim(),
        meeting_date: dateInput.value
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Research failed.");
    render(data);
    statusBox.textContent = "Briefing ready — check the linked evidence.";
  } catch (error) {
    statusBox.textContent = error.message || "Something went wrong. Please try again.";
  } finally {
    button.disabled = false;
  }
});
