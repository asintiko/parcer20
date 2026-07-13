from parsers.parser_orchestrator import ParserOrchestrator
from datetime import datetime
from decimal import Decimal


def test_orchestrator_without_openai_returns_none():
    orchestrator = ParserOrchestrator(db_session=None, openai_api_key=None, allow_missing_openai=True)
    text = "Unparsable text without known format"
    res = orchestrator.process(text)
    assert res is None
    assert orchestrator.last_rejection_reason is not None
    assert "ai" in orchestrator.last_rejection_reason.lower()


def test_receiver_extractors_do_not_cross_lines_or_return_garbage():
    orchestrator = ParserOrchestrator.__new__(ParserOrchestrator)
    text = """Receiver name: JOHN DOE
Receiver card: 860012******1234
Amount: 500,000 UZS"""

    assert orchestrator._extract_receiver_name(text) == "JOHN DOE"
    assert orchestrator._extract_receiver_card(text) == "1234"
    assert orchestrator._extract_receiver_card("Receiver: JOHN DOE") is None


def test_regex_success_never_triggers_second_ai_mapping_by_default(monkeypatch):
    monkeypatch.delenv("AI_APPLICATION_MAPPING_ENABLED", raising=False)
    orchestrator = ParserOrchestrator(db_session=None)
    orchestrator.regex_parser.parse = lambda _text: {
        "amount": Decimal("100.00"),
        "currency": "UZS",
        "transaction_type": "DEBIT",
        "transaction_date": datetime(2026, 7, 12, 10, 0),
        "operator_raw": "UNKNOWN MERCHANT",
        "parsing_method": "REGEX_SMS",
        "parsing_confidence": 0.95,
    }

    class Mapper:
        def map_operator_details(self, _operator):
            return None

        def get_existing_applications(self):
            return []

        def get_candidate_examples(self, _operator, limit=10):  # noqa: ARG002
            return []

    class Ai:
        enabled = True

        def resolve_application(self, *_args, **_kwargs):
            raise AssertionError("second AI mapping call must be opt-in")

    orchestrator.operator_mapper = Mapper()
    orchestrator.ai_parser = Ai()

    result = orchestrator.process("valid regex receipt")

    assert result is not None
    assert result["application_mapped"] is None
