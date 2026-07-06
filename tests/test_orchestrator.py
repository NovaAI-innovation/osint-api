"""Happy-path tests for orchestrator.main entity extraction."""
from orchestrator import main as orch_main


def test_extract_entities_finds_email_and_username():
    text = "Contact me at alice@example.com or see https://github.com/alice123"
    found = orch_main.extract_entities(text)
    types = sorted(t for t, _ in found)
    assert "email" in types
    assert "username" in types


def test_extract_entities_dedupes_within_text():
    text = "alice@example.com alice@example.com alice@example.com"
    found = orch_main.extract_entities(text)
    emails = [v for t, v in found if t == "email"]
    assert len(emails) == 1


def test_extract_entities_returns_tuples_of_type_and_value():
    text = "foo bar alice@example.com"
    for ent in orch_main.extract_entities(text):
        assert isinstance(ent, tuple)
        assert len(ent) == 2
        assert isinstance(ent[0], str)
        assert isinstance(ent[1], str)
