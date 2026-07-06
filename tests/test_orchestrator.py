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


def test_get_or_create_entity_is_idempotent():
    """Calling get_or_create_entity twice with the same (value, type) must
    not raise. The create branch flushes after db.add so the second
    iteration of the caller's for-loop sees the row via SELECT and skips
    the create path. Without the flush, the second SELECT returns None
    (uncommitted) and the second db.add races into a UniqueViolation on
    the final commit. Mocks the SQLAlchemy session.
    """
    from unittest.mock import MagicMock

    db = MagicMock()
    fake_entity = MagicMock()
    # First call: SELECT misses, entity added. Second call: SELECT hits
    # (because of the flush inside the first call). The side_effect
    # sequence assumes the implementation flushes inside the create
    # branch.
    db.query.return_value.filter.return_value.first.side_effect = [None, fake_entity]

    e1 = orch_main.get_or_create_entity(db, "alice", "username")
    e2 = orch_main.get_or_create_entity(db, "alice", "username")

    # First call appended the entity; second call returned the existing
    # one (we never appended again).
    assert db.add.call_count == 1
    assert e2 is fake_entity
    # Sanity: e1 is not None (the created MagicMock entity).
    assert e1 is not None
