import os
from datetime import date, timedelta
from flask import Flask, jsonify, render_template, request
import requests
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def search_web(company: str, meeting_date: date):
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is missing. Add it to your .env file.")

    start_date = meeting_date - timedelta(days=30)
    payload = {
        "api_key": api_key,
        "query": f'"{company}" news updates announcements partnerships products leadership',
        "topic": "news",
        "search_depth": "advanced",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
        "days": 30
    }
    response = requests.post(TAVILY_URL, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", "Untitled source"),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "published_date": item.get("published_date") or item.get("date") or "Date not provided",
            "score": item.get("score")
        })
    return results, start_date


def build_briefing(company: str, meeting_date: date, sources: list, start_date: date):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your .env file.")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    source_text = "\n\n".join(
        f"[{i+1}] {s['title']}\nURL: {s['url']}\nDate: {s['published_date']}\nExtract: {s['content']}"
        for i, s in enumerate(sources)
    )
    prompt = f"""Prepare a concise, evidence-led meeting briefing about: {company}
Meeting date: {meeting_date.isoformat()}
Research window requested: {start_date.isoformat()} through {meeting_date.isoformat()}.
Use ONLY the supplied search results. Do not invent facts, dates, people, or citations.
If a source has no publication date, say its date is unavailable and do not claim it is within the window.
Clearly distinguish reported facts from analysis and questions. Cite factual findings using source numbers [1], [2].
Return valid JSON with keys: executive_summary (string), key_developments (array of objects with title, detail, why_it_matters, source_numbers), discussion_points (array of strings), open_questions (array of strings), opportunities (array of strings), risks (array of strings), research_gaps (array of strings).
If evidence is weak or absent, say so instead of filling gaps.

SEARCH RESULTS:
{source_text}"""
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a careful business research analyst. Never fabricate evidence."},
                {"role": "user", "content": prompt}
            ]
        },
        timeout=90
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    import json
    return json.loads(content)


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok", "app": "StylePilot AI"})


@app.post("/api/research")
def research():
    payload = request.get_json(silent=True) or {}
    company = (payload.get("company") or "").strip()
    meeting_date_raw = (payload.get("meeting_date") or "").strip()
    if len(company) < 2:
        return jsonify({"error": "Enter a company or person's name."}), 400
    try:
        meeting_date = date.fromisoformat(meeting_date_raw)
    except ValueError:
        return jsonify({"error": "Enter a valid meeting date."}), 400
    if meeting_date < date.today():
        return jsonify({"error": "Meeting date cannot be in the past."}), 400

    try:
        sources, start_date = search_web(company, meeting_date)
        if not sources:
            return jsonify({"error": "No search results were found. Try a more specific name."}), 404
        briefing = build_briefing(company, meeting_date, sources, start_date)
        return jsonify({
            "company": company,
            "meeting_date": meeting_date.isoformat(),
            "window_start": start_date.isoformat(),
            "briefing": briefing,
            "sources": sources
        })
    except requests.HTTPError as exc:
        detail = exc.response.text[:400] if exc.response is not None else str(exc)
        return jsonify({"error": f"An external API returned an error: {detail}"}), 502
    except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
