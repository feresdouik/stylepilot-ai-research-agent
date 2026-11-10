import json
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

    def test_optional_resolution_context_is_validated_and_forwarded(self):
        meeting = date.today() + timedelta(days=2)
        with patch.object(stylepilot, "search_web", return_value=([], [], meeting - timedelta(days=30), date.today())) as search:
            response = self.client.post("/api/research", json={
                "company": "Example", "meeting_date": meeting.isoformat(),
                "entity_type": "company", "industry": "technology",
                "meeting_context": "Discuss a cloud partnership",
            })
        self.assertEqual(response.status_code, 404)
        search.assert_called_once_with(
            "Example", meeting, "technology", "Discuss a cloud partnership", "company"
        )

        invalid = self.client.post("/api/research", json={
            "company": "Example", "meeting_date": meeting.isoformat(), "entity_type": "planet"
        })
        self.assertEqual(invalid.status_code, 400)

    def test_dynamic_official_domains_for_common_companies_and_unknown(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body

        cases = {
            "Apple": "apple.com", "Adidas": "adidas.com", "Samsung": "samsung.com",
            "Amazon": "amazon.com", "Tesla": "tesla.com", "Microsoft": "microsoft.com",
            "Nike": "nike.com", "Zara": "inditex.com",
        }
        for name, domain in cases.items():
            with self.subTest(company=name):
                with patch.dict(stylepilot._official_domain_cache, {}, clear=True):
                    responses = [
                        FakeResponse({"search": [{"id": "Q123", "label": name, "description": "company"}]}),
                        FakeResponse({"entities": {"Q123": {
                            "labels": {"en": {"value": name}},
                            "descriptions": {"en": {"value": "company"}},
                            "claims": {
                                "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q783794"}}}}],
                                "P856": [{"mainsnak": {"datavalue": {"value": f"https://www.{domain}"}}}],
                            },
                        }}}),
                    ]
                    with patch.object(stylepilot.requests, "get", side_effect=responses):
                        verified = stylepilot.discover_official_domains(name)
                self.assertIn(domain, verified)
                self.assertEqual(stylepilot.classify_source_type(name, f"https://{domain}/news", verified), "official_primary")

    def test_unknown_or_ambiguous_entities_are_not_guessed_official(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body

        with patch.dict(stylepilot._official_domain_cache, {}, clear=True):
            with patch.object(stylepilot.requests, "get", return_value=FakeResponse({"search": []})):
                verified = stylepilot.discover_official_domains("Unknown Example Company")
        self.assertEqual(verified, set())
        self.assertEqual(stylepilot.classify_source_type(
            "Unknown Example Company", "https://unknownexamplecompany.com", verified
        ), "secondary_or_unverified")

    def test_verified_domain_matching_rejects_lookalikes_and_unrelated_domains(self):
        classify = stylepilot.classify_source_type
        verified = {"apple.com"}
        self.assertEqual(classify("Apple", "https://www.apple.com/news", verified), "official_primary")
        self.assertEqual(classify("Apple", "https://investors.apple.com/", verified), "official_primary")
        self.assertEqual(classify("Apple", "https://apple.com.attacker.example/", verified), "secondary_or_unverified")
        self.assertEqual(classify("Apple", "https://apple-investors.example/", verified), "secondary_or_unverified")

    def test_ambiguous_exact_entities_fail_closed(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body
        search = FakeResponse({"search": [
            {"id": "Q1", "label": "Mercury", "description": "company"},
            {"id": "Q2", "label": "Mercury", "description": "company"},
        ]})
        detail = FakeResponse({"entities": {
            qid: {
                "labels": {"en": {"value": "Mercury"}},
                "descriptions": {"en": {"value": "energy company"}},
                "claims": {
                    "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q783794"}}}}],
                    "P856": [{"mainsnak": {"datavalue": {"value": f"https://{qid.lower()}.example"}}}],
                },
            } for qid in ("Q1", "Q2")
        }})
        with patch.dict(stylepilot._official_domain_cache, {}, clear=True):
            with patch.object(stylepilot.requests, "get", side_effect=[search, detail]):
                self.assertEqual(stylepilot.discover_official_domains("Mercury"), set())

    def test_entity_type_and_context_rank_official_candidates(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body

        fixtures = {
            "Apple": {
                "industry": "technology", "entity_type": "company", "expected": "apple.com",
                "candidates": [
                    ("Q89", "apple", "edible fruit", "Q5", None),
                    ("Q312", "Apple Inc.", "American multinational technology company", "Q783794", "https://www.apple.com/"),
                    ("Q111", "Apple", "registered trademark owned by Apple", "Q431289", "https://brand.example/"),
                ],
            },
            "Adidas": {
                "industry": "sportswear", "entity_type": "company", "expected": "adidas.com",
                "candidates": [
                    ("Q123", "Adidas", "trade mark of Adidas AG", "Q431289", "https://adidas-group.com/"),
                    ("Q303", "Adidas", "business", "Q4830453", None),
                    ("Q3895", "Adidas AG", "German multinational corporation", "Q783794", "https://www.adidas.com/"),
                ],
            },
            "Tesla": {
                "industry": "automotive", "entity_type": "company", "expected": "tesla.com",
                "candidates": [
                    ("Q163343", "tesla", "SI unit of magnetic flux density", "QOTHER", None),
                    ("Q478214", "Tesla", "American automotive and clean energy company", "Q783794", "https://www.tesla.com/"),
                ],
            },
            "Microsoft": {
                "industry": "technology", "entity_type": "company", "expected": "microsoft.com",
                "candidates": [("Q2283", "Microsoft", "American multinational technology corporation", "Q167037", "https://www.microsoft.com/")],
            },
            "Taylor Swift": {
                "industry": "music", "entity_type": "person", "expected": "taylorswift.com",
                "candidates": [
                    ("Q845783", "Taylor Swift", "2006 studio album", "QOTHER", None),
                    ("Q26876", "Taylor Swift", "American singer-songwriter", "Q5", "https://taylorswift.com/"),
                ],
            },
        }
        for name, fixture in fixtures.items():
            with self.subTest(entity=name):
                candidates = fixture["candidates"]
                search = FakeResponse({"search": [
                    {"id": qid, "label": label, "description": description}
                    for qid, label, description, _kind, _url in candidates
                ]})
                details = FakeResponse({"entities": {
                    qid: {
                        "labels": {"en": {"value": label}},
                        "descriptions": {"en": {"value": description}},
                        "claims": {
                            "P31": [{"mainsnak": {"datavalue": {"value": {"id": kind}}}}],
                            **({"P856": [{"mainsnak": {"datavalue": {"value": url}}}]} if url else {}),
                        },
                    }
                    for qid, label, description, kind, url in candidates
                }})
                with patch.dict(stylepilot._official_domain_cache, {}, clear=True):
                    with patch.object(stylepilot.requests, "get", side_effect=[search, details]):
                        domains = stylepilot.discover_official_domains(
                            name, fixture["industry"], "Leadership or product discussion", fixture["entity_type"]
                        )
                self.assertIn(fixture["expected"], domains)
                self.assertEqual(stylepilot.classify_source_type(name, f"https://{fixture['expected']}/news", domains), "official_primary")

    def test_context_does_not_break_mercury_tie_or_guess_first_result(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body
        candidates = [
            ("Q1", "Mercury", "energy company", "https://mercury-one.example"),
            ("Q2", "Mercury", "energy company", "https://mercury-two.example"),
        ]
        search = FakeResponse({"search": [{"id": qid, "label": label} for qid, label, _desc, _url in candidates]})
        details = FakeResponse({"entities": {
            qid: {
                "labels": {"en": {"value": label}},
                "descriptions": {"en": {"value": description}},
                "claims": {
                    "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q783794"}}}}],
                    "P856": [{"mainsnak": {"datavalue": {"value": url}}}],
                },
            } for qid, label, description, url in candidates
        }})
        with patch.dict(stylepilot._official_domain_cache, {}, clear=True):
            with patch.object(stylepilot.requests, "get", side_effect=[search, details]):
                domains = stylepilot.discover_official_domains("Mercury", "energy", "Supplier meeting", "company")
        self.assertEqual(domains, set())

    def test_search_web_separates_undated_and_out_of_window_results(self):
        today = date.today()
        meeting = today + timedelta(days=5)
        old_date = (meeting - timedelta(days=31)).isoformat()
        responses = [
            {"results": [
                {"title": "Undated", "url": "https://example.com/undated", "published_date": None},
                {"title": "Too old", "url": "https://example.com/old", "published_date": old_date},
                {"title": "Inside window", "url": "https://example.com/current", "published_date": today.isoformat()},
            ]},
            {"results": []},
        ]
        class FakeResponse:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            with patch.object(stylepilot.requests, "post", side_effect=[FakeResponse(x) for x in responses]) as search_post:
                with patch.object(stylepilot, "discover_official_domains", return_value=set()):
                    dated, undated, start, end = stylepilot.search_web(
                        "Nike", meeting, "sportswear", "partnership meeting", "company"
                    )
        self.assertIn("sportswear", search_post.call_args_list[0].kwargs["json"]["query"])
        self.assertIn("partnership meeting", search_post.call_args_list[0].kwargs["json"]["query"])
        self.assertEqual([s["title"] for s in dated], ["Inside window"])
        self.assertEqual([s["title"] for s in undated], ["Undated"])
        self.assertEqual(start, meeting - timedelta(days=30))
        self.assertEqual(end, today)

    def test_assessment_parser_marks_missing_malformed_and_unknown_explicitly(self):
        sources = [{"source_type": "secondary_or_unverified"} for _ in range(4)]
        parsed = stylepilot.normalize_source_assessments([
            {"source_number": 1, "relevance": "direct", "reason": "Relevant"},
            {"source_number": 2, "relevance": "maybe"},
            "malformed entry",
            {"source_number": 4, "relevance": "irrelevant"},
        ], sources)
        self.assertEqual([a["relevance"] for a in parsed], ["direct", "unassessed", "unassessed", "irrelevant"])

    def test_assessment_parser_normalizes_supported_labels_and_is_idempotent(self):
        sources = [{"source_type": "secondary_or_unverified"} for _ in range(6)]
        parsed = stylepilot.normalize_source_assessments([
            {"source_number": 1, "relevance": " DIRECTLY RELEVANT ", "reason": "Exact subject."},
            {"source_id": "2", "relevance_label": "Partially Relevant", "reason": "Related context."},
            {"source_number": 3, "assessment": {"label": "not relevant"}},
            {"source_number": 4, "relevance": "uncertain", "reason": "Insufficient extract."},
            {"source_number": 5, "relevance": "relevant", "reason": "General relevance."},
            {"source_number": 6, "relevance": "unsupported new label"},
        ], sources)
        self.assertEqual(
            [item["relevance"] for item in parsed],
            ["direct", "contextual", "irrelevant", "unassessed", "contextual", "unassessed"],
        )
        self.assertEqual(
            stylepilot.normalize_source_assessments(parsed, sources), parsed,
            "Normalizing canonical output twice must preserve explicit unassessed reasons.",
        )

    def test_six_source_groq_response_uses_strict_schema_and_normalizes_all_assessments(self):
        meeting = date.today()
        sources = [{
            "title": f"Source {index}", "url": f"https://news{index}.example/story",
            "content": "A dated report.", "published_date": meeting.isoformat(),
            "source_type": "secondary_or_unverified",
        } for index in range(1, 7)]
        briefing = {
            "executive_summary": "Recent reports identify topics for discussion.",
            "executive_summary_source_numbers": [1, 2, 5],
            "key_developments": [], "discussion_points": [], "open_questions": [],
            "opportunities": [], "risks": [], "research_gaps": [],
            "source_assessments": [
                {"source_number": 1, "assessment": "directly relevant", "reason": "Exact subject."},
                {"source_number": 2, "relevance": "relevant", "reason": "Useful related report."},
                {"source_number": 3, "relevance": "unrelated", "reason": "Different subject."},
                {"source_number": 4, "relevance": "uncertain", "reason": "Extract too thin."},
                {"source_number": 5, "relevance": "direct", "reason": "Exact subject."},
                {"source_number": 6, "relevance": "unknown future label"},
            ],
        }
        class FakeResponse:
            status_code = 200
            headers = {}
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": json.dumps(briefing)}}]}
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            with patch.object(stylepilot.requests, "post", return_value=FakeResponse()) as groq_post:
                result = stylepilot.build_briefing(
                    "Nike", meeting, sources, meeting - timedelta(days=30), meeting
                )
        self.assertEqual(len(result["source_assessments"]), 6)
        self.assertEqual(
            [item["relevance"] for item in result["source_assessments"]],
            ["direct", "contextual", "irrelevant", "unassessed", "direct", "unassessed"],
        )
        output_format = groq_post.call_args.kwargs["json"]["response_format"]
        self.assertEqual(output_format["type"], "json_schema")
        self.assertTrue(output_format["json_schema"]["strict"])
        schema = output_format["json_schema"]["schema"]
        self.assertIn("source_assessments", schema["required"])
        self.assertEqual(
            schema["properties"]["source_assessments"]["items"]["properties"]["relevance"]["enum"],
            ["direct", "contextual", "irrelevant", "unassessed"],
        )

    def test_malformed_groq_json_logs_structure_without_content_and_fails_clearly(self):
        malformed = '{"source_assessments":[{"relevance":"direct"}] SECRET_SENTINEL'
        with self.assertLogs("app", level="WARNING") as captured:
            with self.assertRaisesRegex(ValueError, "malformed briefing JSON"):
                stylepilot.parse_briefing_json(malformed, [{"source_type": "secondary_or_unverified"}])
        logs = "\n".join(captured.output)
        self.assertIn("Groq briefing JSON parse failed", logs)
        self.assertNotIn("SECRET_SENTINEL", logs)

    def test_linkedin_on_result_is_excluded_but_useful_secondary_sources_remain(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "On unveils its next running shoe", "url": "https://www.linkedin.com/posts/on-running_launch",
            "content": "A post about On Running; Nike appears only as a hashtag.",
            "published_date": date.today().isoformat(), "score": 0.9,
            "source_type": "secondary_or_unverified",
        }] + [{
            "title": f"Nike trade report {index}", "url": f"https://news{index}.example/nike",
            "content": "A report about Nike.", "published_date": date.today().isoformat(),
            "score": 0.8, "source_type": "reputable_reporting",
        } for index in range(2, 7)]
        briefing = {
            "executive_summary": "A trade report describes a Nike development.",
            "executive_summary_source_numbers": [1, 6],
            "key_developments": [{
                "title": "Nike development", "detail": "The report says Nike acted.",
                "why_it_matters": "Discussion point.", "source_numbers": [1, 6],
            }],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [],
            # /api/research ranks reputable reporting above LinkedIn before
            # assigning source numbers, so the LinkedIn post is source 6.
            "source_assessments": [
                *[{
                    "source_number": index, "relevance": "directly relevant",
                    "reason": "The report is about Nike.",
                } for index in range(1, 6)],
                {"source_number": 6, "relevance": "not relevant", "reason": "The post is about On; Nike is incidental."},
            ],
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Nike", "meeting_date": meeting.isoformat(),
                })
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(len(result["sources"]), 5)
        self.assertTrue(all("linkedin.com" not in source["url"] for source in result["sources"]))
        self.assertEqual(result["briefing"]["executive_summary_source_numbers"], [1])
        self.assertEqual(result["briefing"]["key_developments"][0]["source_numbers"], [1])

    def test_invalid_citations_are_removed_and_unassessed_source_is_not_evidence(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Article", "url": "https://example.com/story", "content": "Claim",
            "published_date": date.today().isoformat(), "score": 0.8,
            "source_type": "secondary_or_unverified",
        }]
        briefing = {
            "executive_summary": "Unsupported claim.", "executive_summary_source_numbers": [1, 99, True],
            "key_developments": [{"title": "Claim", "detail": "Claim", "source_numbers": [1, 99, True]}],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [], "source_assessments": [{"source_number": 1, "relevance": "unknown"}],
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={"company": "Example Ltd", "meeting_date": meeting.isoformat()})
        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(result["sources"]), 1)  # Kept visible, explicitly unassessed.
        self.assertEqual(result["briefing"]["source_assessments"][0]["relevance"], "unassessed")
        self.assertEqual(result["briefing"]["executive_summary_source_numbers"], [])
        self.assertIn("No sufficiently assessed sources", result["briefing"]["executive_summary"])
        self.assertEqual(result["briefing"]["key_developments"], [])

    def test_empty_but_valid_briefing_returns_success_without_fabrication(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Unrelated article", "url": "https://example.com/story", "content": "Unrelated",
            "published_date": date.today().isoformat(), "score": 0.8,
            "source_type": "secondary_or_unverified",
        }]
        briefing = {
            "executive_summary": "", "executive_summary_source_numbers": [], "key_developments": [],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [], "source_assessments": [{"source_number": 1, "relevance": "irrelevant"}],
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={"company": "Example Ltd", "meeting_date": meeting.isoformat()})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["briefing"]["key_developments"], [])
        self.assertIn("No sufficiently assessed sources", result["briefing"]["executive_summary"])


    def test_unassessed_sources_remain_visible_but_are_not_evidence(self):
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
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["briefing"]["source_assessments"][0]["relevance"], "unassessed")
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
