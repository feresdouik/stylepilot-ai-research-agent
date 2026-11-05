# StylePilot AI

**Research before you walk in.**

StylePilot AI is an AI-powered meeting research agent. Enter a company or person's name and a meeting date to generate a concise, source-backed briefing based on developments from the preceding 30 days.

## What it does

- Searches recent web/news coverage with the Tavily Search API.
- Uses an LLM to organize the supplied evidence into a meeting briefing.
- Highlights key developments, why they matter, discussion points, open questions, opportunities, risks, and research gaps.
- Displays source links so users can inspect the underlying material.

The initial demo is designed for business meeting preparation across industries. Fashion and retail can be used as an example research domain, not as a product limitation.

## Tech stack

- Python and Flask
- Tavily Search API
- OpenAI-compatible Chat Completions API
- HTML, CSS, and vanilla JavaScript

## Run locally

1. Use Python 3.10 or newer.
2. Clone this repository and open its directory.
3. Create and activate a virtual environment.
4. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and add your API keys:

   ```env
   TAVILY_API_KEY=...
   OPENAI_API_KEY=...
   OPENAI_MODEL=gpt-4o-mini
   OPENAI_BASE_URL=https://api.openai.com/v1
   ```

6. Start the app:

   ```bash
   python app.py
   ```

7. Open http://127.0.0.1:5000

## API

- `GET /health` — health check.
- `POST /api/research` — accepts JSON with `company` and `meeting_date` (`YYYY-MM-DD`).

## Important limitations

This is an early hackathon MVP. Search results and AI summaries can be incomplete or inaccurate. Publication dates may be missing, and the app explicitly labels missing dates rather than treating them as verified. Always open the source links and independently verify important claims before relying on them in a meeting.

Never commit your `.env` file or API keys.
