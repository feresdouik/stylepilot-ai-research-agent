const form = document.querySelector("#research-form");
const statusBox = document.querySelector("#status");
const resultsBox = document.querySelector("#results");
const dateInput = document.querySelector("#meeting-date");
dateInput.value = new Date().toISOString().slice(0, 10);
dateInput.min = dateInput.value;

function list(items) {
  if (!items || !items.length) return "<p>No supported items found.</p>";
  return "<ul>" + items.map(x => "<li>" + escapeHtml(typeof x === "string" ? x : JSON.stringify(x)) + "</li>").join("") + "</ul>";
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function render(data) {
  const b = data.briefing || {};
  const developments = (b.key_developments || []).map(d => `<article><h3>${escapeHtml(d.title || "Development")}</h3><p>${escapeHtml(d.detail || "")}</p><p><strong>Why it matters:</strong> ${escapeHtml(d.why_it_matters || "")}</p><small>Sources: ${escapeHtml((d.source_numbers || []).join(", "))}</small></article>`).join("");
  const sources = (data.sources || []).map((s,i) => `<div class="source">[${i+1}] <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title)}</a><p>${escapeHtml(s.published_date)}</p></div>`).join("");
  resultsBox.innerHTML = `<p class="eyebrow">YOUR MEETING BRIEFING</p><h2>${escapeHtml(data.company)}</h2><p>Meeting: ${escapeHtml(data.meeting_date)} · Research window starts ${escapeHtml(data.window_start)}</p><h3>Executive summary</h3><p>${escapeHtml(b.executive_summary || "No summary available.")}</p><h3>Key developments</h3>${developments || "<p>No developments extracted.</p>"}<h3>Discussion points</h3>${list(b.discussion_points)}<h3>Open questions</h3>${list(b.open_questions)}<h3>Opportunities</h3>${list(b.opportunities)}<h3>Risks</h3>${list(b.risks)}<h3>Research gaps</h3>${list(b.research_gaps)}<h3>Sources</h3>${sources}`;
  resultsBox.hidden = false;
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  statusBox.textContent = "Researching recent developments and preparing your briefing…";
  resultsBox.hidden = true;
  try {
    const response = await fetch("/api/research", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({company: document.querySelector("#company").value, meeting_date: dateInput.value})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Research failed.");
    render(data);
    statusBox.textContent = "Briefing ready.";
  } catch (error) {
    statusBox.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
