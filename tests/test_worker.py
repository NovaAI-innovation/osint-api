"""Happy-path tests for worker.main.process_job."""
import json
import uuid
from unittest.mock import MagicMock, patch

from worker import main as worker_main


def test_run_tool_returns_status_and_parsed_json():
    """The default tool subprocess returns rc=0, stdout is JSON, parsed_data populated."""
    rc, raw, parsed = worker_main._run_tool("sherlock", "username", "alice")
    assert rc == 0
    assert raw.strip().startswith("{")
    assert parsed is not None, f"Could not parse JSON from tool output: {raw!r}"
    assert parsed["tool"] == "sherlock"
    assert parsed["target_type"] == "username"
    assert parsed["target_value"] == "alice"
    assert isinstance(parsed["matches"], list)
    assert len(parsed["matches"]) >= 1


def test_process_job_writes_result_and_marks_completed(fake_session):
    """Full happy path: process_job runs the tool, writes a JobResult, marks Job completed."""
    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "target_type": "email",
        "target_value": "alice@example.com",
        "tools": ["sherlock"],
    }

    # Make SessionLocal().query(...).first() return a job-like MagicMock so the
    # completion branch runs.
    fake_job = MagicMock()
    fake_session.query.return_value.filter.return_value.first.return_value = fake_job

    with patch("worker.main.SessionLocal", return_value=fake_session):
        worker_main.process_job(payload)

    # A JobResult row was added.
    assert fake_session.add.called
    added = fake_session.add.call_args[0][0]
    # JobResult has the right shape; we don't import the class to keep
    # the test independent of shared.db model identity.
    assert added.job_id == uuid.UUID(job_id)
    assert added.tool_name == "sherlock"
    assert added.status_code == 0
    assert added.raw_output is not None
    assert isinstance(added.parsed_data, dict)

    # Parent Job was marked completed and committed.
    assert fake_job.status == "completed"
    assert fake_session.commit.called


def test_process_job_skips_payload_missing_job_id(capsys):
    """Bad payload (no job_id) prints a warning and does not raise."""
    worker_main.process_job({"target_type": "username", "target_value": "x"})
    captured = capsys.readouterr()
    assert "missing job_id" in captured.out
