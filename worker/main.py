import os
import sys
import time
import json
import uuid
import subprocess
from datetime import datetime

import redis

# Add shared module to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import SessionLocal, Job, JobResult

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
# Force RESP2 and disable socket read timeouts so BRPOP can block indefinitely
# on an empty queue. The modern RESP3 parser in redis-py 5.x picks a finite
# socket_timeout default, which raises TimeoutError on every BRPOP against
# an empty queue and surfaces as the worker's "Redis unavailable, retrying in
# 2s" wall. protocol=2 + explicit socket_timeout=None is the standard fix.
r = redis.from_url(
    REDIS_URL,
    socket_timeout=None,
    socket_connect_timeout=None,
    protocol=2,
)

# Must match the gateway's queue: gateway/main.py -> "osint_jobs".
QUEUE_NAME = "osint_jobs"

# Per-tool subprocess commands. Real tools (sherlock, maigret, holehe) would
# be added here as their own argv arrays. For now every tool name resolves
# to an inline Python helper that simulates a basic lookup against
# (target_type, target_value) and emits JSON. The subprocess boundary stays
# real, so swapping in a real tool is just a registry change.
def _tool_command(tool_name):
    script = (
        "import sys, json\n"
        "tt = sys.argv[1]\n"
        "tv = sys.argv[2]\n"
        "tn = sys.argv[3]\n"
        "r = {\n"
        "  'tool': tn,\n"
        "  'target_type': tt,\n"
        "  'target_value': tv,\n"
        "  'matches': [\n"
        "    {'site': 'probe-' + tt, 'url': 'https://example.com/' + tv, 'status': 'available'}\n"
        "  ]\n"
        "}\n"
        "print(json.dumps(r))\n"
    )
    return [sys.executable, "-c", script]


def _run_tool(tool_name, target_type, target_value):
    """Spawn the tool subprocess. Returns (status_code, raw_output, parsed_or_None)."""
    cmd = _tool_command(tool_name) + [target_type, target_value, tool_name]
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        raw = (completed.stdout or completed.stderr or "").strip()
        parsed = None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass
        return (completed.returncode, raw, parsed)
    except subprocess.TimeoutExpired:
        return (-1, "tool timeout: 30s exceeded", None)
    except Exception as e:
        return (-1, f"tool error: {e}", None)


def process_job(job_data):
    """Consume one job from the queue, run each requested tool, persist results.

    Expected payload shape (built by gateway POST /v1/profiles):
      {
        "job_id": "<uuid string>",
        "target_type": "username|email|domain|phone",
        "target_value": "<string>",
        "tools": ["sherlock", ...],
      }
    """
    job_id_str = job_data.get("job_id")
    target_type = job_data.get("target_type", "username")
    target_value = job_data.get("target_value", "")
    tools = job_data.get("tools") or ["sherlock"]

    print(
        f"Processing job: {job_id_str} target={target_type}:{target_value} tools={tools}",
        flush=True,
    )

    if not job_id_str:
        print("process_job error: missing job_id in payload", flush=True)
        return

    job_id = uuid.UUID(job_id_str)

    db = SessionLocal()
    try:
        for tool_name in tools:
            status_code, raw_output, parsed_data = _run_tool(
                tool_name, target_type, target_value
            )
            db.add(JobResult(
                job_id=job_id,
                tool_name=tool_name,
                status_code=status_code,
                raw_output=raw_output or None,
                parsed_data=parsed_data,
                executed_at=datetime.utcnow(),
            ))
            print(
                f"Tool {tool_name} rc={status_code} bytes={len(raw_output or '')}",
                flush=True,
            )

        # Mark the parent Job as completed.
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            print(f"process_job warning: Job {job_id_str} not found in DB", flush=True)
        else:
            job.status = "completed"
            job.updated_at = datetime.utcnow()
        db.commit()
        print(f"Job {job_id_str} marked completed", flush=True)
    except Exception as e:
        db.rollback()
        print(f"process_job error: {e}", flush=True)
    finally:
        db.close()


def main():
    print("Worker started...", flush=True)
    while True:
        try:
            _, job_data = r.brpop(QUEUE_NAME)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            print(f"Redis unavailable, retrying in 2s: {e}", flush=True)
            time.sleep(2)
            continue
        if job_data is None:
            continue
        try:
            process_job(json.loads(job_data))
        except Exception as e:
            print(f"queue payload error: {e}", flush=True)


if __name__ == "__main__":
    main()
