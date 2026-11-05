# StylePilot AI

**Research before you walk in.**

StylePilot AI is an AI-powered meeting research agent. Enter a company or person's name and a meeting date to create a concise briefing from relevant developments in the 30 days before the meeting.

## MVP workflow

1. The user enters a company/person and meeting date.
2. Tavily News Search retrieves sources using an explicit date range.
3. The backend parses publication dates and only sends dated sources inside the window to the AI analysis step.
4. Groq's Groq API (OpenAI-compatible Chat Completions) organizes supported evidence into a meeting briefing.
5. The interface displays findings, discussion prompts, risks, research gaps, and clickable source links.

For a future meeting, the search window ends at the current date because future news cannot be retrieved yet. Undated results are disclosed and excluded from AI analysis.

## Features

- Evidence-first meeting preparation for companies and people across industries.
- 30-day date window anchored to the meeting date.
- Dated-source filtering before AI synthesis.
- Key developments with source-number references.
- Discussion points, open questions, opportunities, risks, and research gaps.
- Print / Save as PDF from the browser.
- Basic health endpoint showing whether API keys are configured (never exposes the keys).

## Tech stack

- Python 3.10+
- Flask
- Tavily Search API
- OpenAI-compatible Chat Completions API
- HTML, CSS, vanilla JavaScript

## Run locally

1. Clone the repository.
2. Create and activate a Python virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and add your keys:

   ```env
   TAVILY_API_KEY=your_tavily_api_key
   GROQ_API_KEY=your_groq_api_key
   GROQ_MODEL=llama-3.3-70b-versatile
   GROQ_BASE_URL=https://api.groq.com/openai/v1
   ```

5. Start the app:

   ```bash
   python app.py
   ```

6. Open http://127.0.0.1:5000

## Deploy on Render

1. Push this repository to GitHub (already done for this project).
2. In Render, choose **New + → Blueprint** and select this repository.
3. Render reads `render.yaml` and creates the web service.
4. In the service environment settings, add `TAVILY_API_KEY` and `GROQ_API_KEY` as secret values. Do not put API keys in GitHub.
5. Wait for the deploy to finish, then open the generated `onrender.com` URL. The `/health` endpoint confirms the app is running and whether the two keys are configured.

## API

- `GET /health` — app status and boolean API-configuration indicators.
- `POST /api/research` — JSON body: `{"company":"Example Ltd","meeting_date":"2026-11-20"}`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `TAVILY_API_KEY` | Yes | Tavily Search API authentication |
| `GROQ_API_KEY` | Yes | Groq LLM provider authentication |
| `GROQ_MODEL` | No | Model name; defaults to `llama-3.3-70b-versatile` |
| `GROQ_BASE_URL` | No | Groq OpenAI-compatible API base URL |
| `PORT` | No | Local server port; defaults to `5000` |
| `FLASK_DEBUG` | No | Enable Flask debug mode only for local development |

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```

## Important limitations

This is a hackathon MVP, not a verified intelligence service. Search coverage may be incomplete, publishers may omit dates, and AI summaries can make mistakes. The app filters sources by their parsed publication dates, but this does not independently verify the truth of an article. Always open the source links and independently verify important claims.

Never commit your `.env` file or API keys.
