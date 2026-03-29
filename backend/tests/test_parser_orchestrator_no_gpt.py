from parsers.parser_orchestrator import ParserOrchestrator


def test_orchestrator_without_openai_returns_none():
    orchestrator = ParserOrchestrator(db_session=None, openai_api_key=None, allow_missing_openai=True)
    text = "Unparsable text without known format"
    res = orchestrator.process(text)
    assert res is None
    assert orchestrator.last_rejection_reason is not None
    assert "gpt" in orchestrator.last_rejection_reason.lower()
