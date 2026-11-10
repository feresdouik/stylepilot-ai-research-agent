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
        request_payload = groq_post.call_args.kwargs["json"]
        self.assertEqual(output_format["type"], "json_schema")
        self.assertTrue(output_format["json_schema"]["strict"])
        self.assertFalse(request_payload["include_reasoning"])
        self.assertEqual(request_payload["max_completion_tokens"], 3072)
        prompt = request_payload["messages"][-1]["content"]
        self.assertIn("Include every required key", prompt)
        self.assertIn('"direct", "contextual", "irrelevant", and "unassessed"', prompt)
        self.assertIn("no other keys or properties", prompt)
        schema = output_format["json_schema"]["schema"]
        self.assertIn("source_assessments", schema["required"])
        self.assertEqual(
            schema["properties"]["source_assessments"]["items"]["properties"]["relevance"]["enum"],
            ["direct", "contextual", "irrelevant", "unassessed"],
        )
        self.assertEqual(schema["properties"]["executive_summary_source_numbers"]["items"], {"type": "integer"})
        development = schema["properties"]["key_developments"]["items"]
        assessment = schema["properties"]["source_assessments"]["items"]
        self.assertEqual(development["properties"]["source_numbers"]["items"], {"type": "integer"})
        self.assertEqual(assessment["properties"]["source_number"], {"type": "integer"})
        for object_schema in (schema, development, assessment):
            self.assertFalse(object_schema["additionalProperties"])
            self.assertEqual(set(object_schema["required"]), set(object_schema["properties"]))

        def check_strict_objects(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(set(node.get("required", [])), set(node.get("properties", {})))
                for value in node.values():
                    check_strict_objects(value)
            elif isinstance(node, list):
                for value in node:
                    check_strict_objects(value)
        check_strict_objects(schema)

    def test_groq_json_validation_error_redacts_failed_generation(self):
        meeting = date.today() + timedelta(days=2)
        private_text = "PRIVATE_SOURCE_EXCERPT_92d128"
        sources = [{
            "title": "Private meeting source", "url": "https://example.com/private",
            "content": private_text, "published_date": date.today().isoformat(),
            "score": 0.8, "source_type": "secondary_or_unverified",
        }]
        class ProviderErrorResponse:
            status_code = 400
            text = "This raw body must not be logged."
            def json(self):
                return {"error": {
                    "message": "Failed to validate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
                    "type": "invalid_request_error", "code": "json_validate_failed",
                    "failed_generation": private_text,
                }}
        provider_response = ProviderErrorResponse()
        error = stylepilot.requests.HTTPError("provider rejected JSON", response=provider_response)
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", side_effect=error):
                with self.assertLogs("app", level="WARNING") as captured:
                    response = self.client.post("/api/research", json={
                        "company": "Example Ltd", "meeting_date": meeting.isoformat(),
                    })
        self.assertEqual(response.status_code, 502)
        body = response.get_json()
        self.assertEqual(body["provider_error_code"], "json_validate_failed")
        self.assertIn("could not validate the generated JSON", body["error"])
        diagnostic = "\n".join(captured.output)
        self.assertIn("failed_generation_present=True", diagnostic)
        self.assertNotIn(private_text, diagnostic)
        self.assertNotIn(private_text, body["error"])
        self.assertNotIn("raw body", diagnostic)

    def test_malformed_groq_provider_error_body_uses_safe_generic_reason(self):
        class MalformedProviderError:
            status_code = 400
            text = "PRIVATE_RAW_RESPONSE_SHOULD_NOT_ESCAPE"
            def json(self): raise ValueError("malformed JSON")
        details = stylepilot._safe_groq_error_details(MalformedProviderError())
        self.assertIn("detailed provider text was redacted", details["message"])
        self.assertFalse(details["failed_generation_present"])
        self.assertNotIn("PRIVATE_RAW_RESPONSE", details["message"])

    def test_safe_groq_error_keeps_diagnostic_message_and_redacts_private_fragments(self):
        private_text = "Confidential source excerpt with distinctive wording."
        class ProviderError:
            def json(self):
                return {"error": {
                    "message": f"Invalid response_format near {private_text}; bearer sample-secret-value",
                    "type": "invalid_request_error", "code": "invalid_schema",
                }}
        details = stylepilot._safe_groq_error_details(ProviderError(), [private_text])
        self.assertIn("Invalid response_format", details["message"])
        self.assertIn("invalid_schema", details["code"] or "")
        self.assertNotIn(private_text, details["message"])
        self.assertNotIn("sample-secret-value", details["message"])

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

    def test_citations_remain_aligned_after_leading_source_is_filtered(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Irrelevant lead", "url": "https://other.example/story",
            "content": "Different subject.", "published_date": date.today().isoformat(),
            "source_type": "secondary_or_unverified", "score": 0.9,
        }, {
            "title": "Relevant source two", "url": "https://entity.example/two",
            "content": "Relevant fact two.", "published_date": date.today().isoformat(),
            "source_type": "secondary_or_unverified", "score": 0.8,
        }, {
            "title": "Relevant source three", "url": "https://entity.example/three",
            "content": "Relevant fact three.", "published_date": date.today().isoformat(),
            "source_type": "secondary_or_unverified", "score": 0.7,
        }]
        briefing = {
            "executive_summary": "A fact from source three.", "executive_summary_source_numbers": [3],
            "key_developments": [{"title": "A fact", "detail": "Source three reports it.",
                                  "why_it_matters": "Discussion topic.", "source_numbers": [3]}],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [], "source_assessments": [
                {"source_number": 1, "relevance": "irrelevant", "reason": "Different entity."},
                {"source_number": 2, "relevance": "direct", "reason": "About entity."},
                {"source_number": 3, "relevance": "contextual", "reason": "Relevant context."},
            ],
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Example Co", "meeting_date": meeting.isoformat()
                })
        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([source["url"] for source in result["sources"]], [
            "https://entity.example/two", "https://entity.example/three"
        ])
        self.assertEqual(result["briefing"]["executive_summary_source_numbers"], [2])
        self.assertEqual(result["briefing"]["key_developments"][0]["source_numbers"], [2])
        cited = result["sources"][result["briefing"]["key_developments"][0]["source_numbers"][0] - 1]
        self.assertEqual(cited["url"], "https://entity.example/three")

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
        self.assertIn("cited evidence does not verify", result["briefing"]["executive_summary"])
        self.assertEqual(result["briefing"]["key_developments"], [])
        self.assertTrue(any("Secondary evidence is available but is not independently verified" in gap for gap in result["briefing"]["research_gaps"]))

    def test_syndicated_release_requires_exact_first_party_corroboration(self):
        official = {
            "title": "Example Group announces annual investor day",
            "url": "https://investors.example.org/news/investor-day",
            "content": "Example Group announces annual investor day. The event takes place November 16 and 17 with a live webcast for shareholders.",
            "source_type": "official_primary", "publisher_domain": "investors.example.org",
        }
        distributed = {
            "title": "Example Group announces annual investor day",
            "url": "https://wire.example.net/releases/annual-investor-day",
            "content": "Example Group announces annual investor day. The event takes place November 16 and 17 with a live webcast for shareholders. The company also achieved $999 billion in savings.",
            "source_type": "secondary_or_unverified", "publisher_domain": "wire.example.net",
        }
        lookalike_title = {
            "title": "Example Group: market commentary",
            "url": "https://wire.example.net/releases/commentary",
            "source_type": "secondary_or_unverified", "publisher_domain": "wire.example.net",
        }
        copied_headline = {
            "title": "Example Group announces annual investor day",
            "url": "https://wire.example.net/releases/copied-headline",
            "content": "Example Group announces annual investor day. A different story concerns unrelated market activity and broad investor sentiment.",
            "source_type": "secondary_or_unverified", "publisher_domain": "wire.example.net",
        }
        headline_only = {
            "title": "Example Group announces annual investor day",
            "url": "https://wire.example.net/releases/headline-only",
            "content": "Example Group announces annual investor day.",
            "source_type": "secondary_or_unverified", "publisher_domain": "wire.example.net",
        }
        sources = [official, distributed, lookalike_title, copied_headline, headline_only]
        stylepilot.verify_syndicated_releases(sources)
        self.assertEqual(distributed["source_type"], "official_primary")
        self.assertEqual(distributed["issuer_provenance"], "verified_company_issued")
        self.assertEqual(distributed["publisher_domain"], "wire.example.net")
        self.assertEqual(distributed["verification_evidence"][0]["url"], official["url"])
        self.assertEqual(distributed["content"], official["content"])
        self.assertFalse(stylepilot.financial_claim_has_support(
            "The company achieved $999 billion in savings.", [1], [distributed]
        )[0], "Distributor-only appended claims must not become primary evidence.")
        self.assertEqual(lookalike_title["source_type"], "secondary_or_unverified")
        self.assertEqual(lookalike_title["issuer_provenance"], "unverified_third_party")
        self.assertEqual(copied_headline["source_type"], "secondary_or_unverified")
        self.assertEqual(headline_only["source_type"], "secondary_or_unverified")

    def test_event_date_extraction_does_not_infer_missing_year(self):
        exact = stylepilot.extract_event_date({
            "title": "CFO transition", "content": "The appointment is effective 2026-08-17."
        })
        self.assertEqual(exact, ("2026-08-17", "2026-08-17", "effective"))
        yearless = stylepilot.extract_event_date({
            "title": "CFO transition", "content": "The appointment is effective August 17."
        })
        self.assertEqual(yearless, (None, "August 17", "effective"))
        article = stylepilot.extract_event_date({
            "title": "CFO appointment", "content": "This article was published October 23. The appointment is effective August 17."
        })
        self.assertEqual(article, (None, "August 17", "effective"))

    def test_financial_support_is_claim_specific_and_recognizes_basis_points(self):
        sources = [
            {"source_type": "official_primary", "title": "Other results", "content": "Profit was $1 million."},
            {"source_type": "official_primary", "title": "Quarterly report", "content": "Revenue fell 4 percent. Gross margin expanded 60 basis points to 42.8 percent."},
        ]
        self.assertTrue(stylepilot.requires_official_evidence("Gross margin improved 60 basis points."))
        self.assertFalse(stylepilot.financial_claim_has_support(
            "Gross margin improved 60 basis points.", [1], sources
        )[0])
        supported, category, _ = stylepilot.financial_claim_has_support(
            "Gross margin expanded 60 basis points to 42.8 percent.", [2], sources
        )
        self.assertTrue(supported)
        self.assertEqual(category, "officially_reported_historical_result")
        source = [{
            "source_type": "official_primary",
            "content": "Revenue declined 4 percent. Gross margin improved 60 basis points.",
        }]
        # The amount and the word "revenue" both occur, but the 60 bps value
        # belongs to gross margin, not revenue.
        self.assertFalse(stylepilot.financial_claim_has_support(
            "Revenue improved 60 basis points.", [1], source
        )[0])
        self.assertFalse(stylepilot.financial_claim_has_support(
            "Revenue increased 4 percent.", [1], source
        )[0], "A matching number with the opposite direction is not support.")

    def test_official_source_elsewhere_does_not_validate_wrong_financial_citation(self):
        meeting = date.today() + timedelta(days=2)
        sources = [{
            "title": "Other company figure", "url": "https://company.example/other",
            "content": "The official report says revenue increased 99 percent.",
            "published_date": date.today().isoformat(), "source_type": "official_primary",
            "issuer_provenance": "first_party_domain", "score": 0.9,
        }, {
            "title": "Actual quarter result", "url": "https://company.example/results",
            "content": "The official report says revenue declined 4 percent.",
            "published_date": date.today().isoformat(), "source_type": "official_primary",
            "issuer_provenance": "first_party_domain", "score": 0.8,
        }]
        briefing = {
            "executive_summary": "Revenue declined 4 percent.", "executive_summary_source_numbers": [1],
            "key_developments": [{"title": "Revenue decline", "detail": "Revenue declined 4 percent.",
                                  "why_it_matters": "Discussion topic.", "source_numbers": [1]}],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [], "source_assessments": [
                {"source_number": 1, "relevance": "direct", "reason": "About the company."},
                {"source_number": 2, "relevance": "direct", "reason": "About the company."},
            ],
        }
        with patch.object(stylepilot, "search_web", return_value=(sources, [], meeting - timedelta(days=30), date.today())):
            with patch.object(stylepilot, "build_briefing", return_value=briefing):
                response = self.client.post("/api/research", json={
                    "company": "Example Co", "meeting_date": meeting.isoformat()
                })
        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["briefing"]["key_developments"], [])
        self.assertEqual(result["briefing"]["executive_summary_source_numbers"], [])
        self.assertTrue(any("does not support the specific claim" in gap for gap in result["briefing"]["research_gaps"]))

    def test_company_estimate_is_not_labeled_as_achieved_result(self):
        source = {
            "source_type": "official_primary", "issuer_provenance": "first_party_domain",
            "title": "Company outlook", "content": "The company expects $2.5 billion in cumulative savings through fiscal 2031. Actual savings may differ.",
        }
        claim = "The company expects $2.5 billion in cumulative savings through fiscal 2031."
        supported, category, _ = stylepilot.financial_claim_has_support(claim, [1], [source])
        self.assertTrue(supported)
        self.assertEqual(category, "company_forward_looking_estimate")
        self.assertIn("$2.5 billion", source["content"])
        achieved_claim = "The company saved $2.5 billion through fiscal 2031."
        self.assertFalse(stylepilot.financial_claim_has_support(achieved_claim, [1], [source])[0])

    def test_research_gap_reasons_distinguish_evidence_states(self):
        secondary = {"source_type": "reputable_reporting"}
        official = {"source_type": "official_primary"}
        self.assertIn("Secondary evidence is available", stylepilot.financial_research_gap("4% revenue decline", [secondary]))
        self.assertIn("Official evidence was not found", stylepilot.financial_research_gap("4% revenue decline", []))
        self.assertIn("does not support the specific claim", stylepilot.financial_research_gap("4% revenue decline", [official]))
        stylepilot._out_of_window_sources.set(({
            "source_type": "official_primary", "title": "Old annual report", "published_date": "2026-09-01"
        },))
        self.assertIn("falls outside the 30-day publication window", stylepilot.financial_research_gap("4% revenue decline", []))
        stylepilot._out_of_window_sources.set(())

    def test_ui_explicitly_separates_relevance_and_provenance_labels(self):
        from pathlib import Path
        source = Path(stylepilot.__file__).parent / "static" / "app.js"
        ui = source.read_text(encoding="utf-8")
        self.assertIn('direct: "Direct relevance"', ui)
        self.assertIn('contextual: "Contextual relevance"', ui)
        self.assertIn('official_primary: "Official primary source"', ui)
        self.assertIn('secondary_or_unverified: "Secondary source · verify provenance"', ui)

    def test_explicit_old_event_date_cannot_be_marked_newly_announced(self):
        meeting = date.today()
        source = {
            "title": "Leadership update", "url": "https://company.example/leadership",
            "content": "The appointment is effective 2026-08-17.",
            "published_date": "2026-10-23", "event_date": "2026-08-17",
            "event_date_text": "2026-08-17", "event_date_type": "effective",
            "source_type": "official_primary",
        }
        briefing = {
            "executive_summary": "A leadership article was published.", "executive_summary_source_numbers": [1],
            "key_developments": [{"title": "Appointment", "detail": "Appointment effective 2026-08-17.",
                                  "why_it_matters": "Context.", "event_date": "2026-08-17",
                                  "event_status": "newly_announced", "source_numbers": [1]}],
            "discussion_points": [], "open_questions": [], "opportunities": [], "risks": [],
            "research_gaps": [], "source_assessments": [{"source_number": 1, "relevance": "direct", "reason": "About entity."}],
        }
        class FakeResponse:
            status_code = 200
            headers = {}
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": json.dumps(briefing)}}]}
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            with patch.object(stylepilot.requests, "post", return_value=FakeResponse()):
                result = stylepilot.build_briefing("Example company", meeting, [source], meeting - timedelta(days=30), meeting)
        self.assertEqual(result["key_developments"][0]["event_status"], "older_event")

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
