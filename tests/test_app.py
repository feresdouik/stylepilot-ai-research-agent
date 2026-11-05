import unittest
from datetime import date, timedelta
from unittest.mock import patch

import app as stylepilot


class StylePilotTests(unittest.TestCase):
    def setUp(self):
        self.client = stylepilot.app.test_client()

    def test_health_does_not_expose_secrets(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("status", response.get_json())
        self.assertNotIn("TAVILY_API_KEY", response.get_json())

    def test_rejects_short_company(self):
        response = self.client.post("/api/research", json={
            "company": "A", "meeting_date": (date.today() + timedelta(days=1)).isoformat()
        })
        self.assertEqual(response.status_code, 400)

    def test_rejects_invalid_date(self):
        response = self.client.post("/api/research", json={
            "company": "Example Ltd", "meeting_date": "not-a-date"
        })
        self.assertEqual(response.status_code, 400)

    def test_rejects_past_meeting(self):
        response = self.client.post("/api/research", json={
            "company": "Example Ltd", "meeting_date": (date.today() - timedelta(days=1)).isoformat()
        })
        self.assertEqual(response.status_code, 400)

    def test_valid_request_returns_briefing(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Example launches a product",
            "url": "https://example.com/news",
            "content": "A new product was announced.",
            "published_date": date.today().isoformat(),
            "score": 0.9,
        }]
        briefing = {
            "executive_summary": "Example announced a product.",
            "key_developments": [{
                "title": "Product launch", "detail": "A product was announced.",
                "why_it_matters": "Potential market impact.", "source_numbers": [1]
            }],
            "discussion_points": [], "open_questions": [], "opportunities": [],
            "risks": [], "research_gaps": []
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Example Ltd", "meeting_date": meeting.isoformat()
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["briefing"]["executive_summary"], briefing["executive_summary"])


if __name__ == "__main__":
    unittest.main()
