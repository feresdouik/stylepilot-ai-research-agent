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


    def test_unassessed_sources_are_excluded_from_evidence(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Unassessed article", "url": "https://example.com/news",
            "content": "Unverified claim.", "published_date": date.today().isoformat(),
            "score": 0.8, "source_type": "secondary_or_unverified",
        }]
        briefing = {
            "executive_summary": "Unsupported summary.",
            "key_developments": [{
                "title": "Unsupported claim", "detail": "No assessed source.",
                "why_it_matters": "Unknown.", "source_numbers": [1]
            }],
            "discussion_points": [], "open_questions": [], "opportunities": [],
            "risks": [], "research_gaps": [], "source_assessments": []
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Example Ltd", "meeting_date": meeting.isoformat()
                })
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["briefing"]["key_developments"], [])
        self.assertIn("No sufficiently assessed sources", result["briefing"]["executive_summary"])

    def test_financial_claims_without_official_source_are_removed(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "News report about sales",
            "url": "https://news.example.com/story",
            "content": "Sales fell by 12%.",
            "published_date": date.today().isoformat(),
            "score": 0.9,
            "source_type": "reputable_reporting",
        }]
        briefing = {
            "executive_summary": "Revenue fell 12% and profit declined.",
            "executive_summary_source_numbers": [1],
            "key_developments": [{
                "title": "Revenue fell 12%",
                "detail": "The company's revenue fell 12%.",
                "why_it_matters": "Analysis.",
                "source_numbers": [1],
            }],
            "discussion_points": [], "open_questions": [], "opportunities": [],
            "risks": [], "research_gaps": [],
            "source_assessments": [{
                "source_number": 1, "relevance": "direct",
                "reason": "The article reports the result."
            }]
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Example Ltd", "meeting_date": meeting.isoformat()
                })
        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("does not include an official primary source", result["briefing"]["executive_summary"])
        self.assertEqual(result["briefing"]["key_developments"], [])
        self.assertTrue(any("Official primary evidence is missing" in gap for gap in result["briefing"]["research_gaps"]))

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
            "executive_summary_source_numbers": [1],
            "key_developments": [{
                "title": "Product launch", "detail": "A product was announced.",
                "why_it_matters": "Potential market impact.", "source_numbers": [1]
            }],
            "discussion_points": [], "open_questions": [], "opportunities": [],
            "risks": [], "research_gaps": [],
            "source_assessments": [{
                "source_number": 1, "relevance": "direct",
                "reason": "The extract directly describes the product launch."
            }]
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
