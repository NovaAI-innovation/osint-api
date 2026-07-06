import os
import time
import json
import redis
import sys

# Add shared module to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import SessionLocal

REDIS_URL = os.getenv("REDIS_URL")
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

def process_job(job_data):
    print(f"Processing job: {job_data['job_id']}")
    # TODO: Execute OSINT tool based on job_data['tool_name']
    # TODO: Update database with results
    pass

def main():
    print("Worker started...")
    while True:
        try:
            # Blocking pop from the gateway's queue.
            _, job_data = r.brpop(QUEUE_NAME)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
            # Transient: Redis not yet accepting commands (e.g., mid-RDB-load
            # on startup) or socket stalled. Back off and retry rather than
            # letting the container exit and get endlessly restarted.
            print(f"Redis unavailable, retrying in 2s: {e}", flush=True)
            time.sleep(2)
            continue
        if job_data is None:
            # brpop only returns (None, None) when called with a timeout we
            # didn't pass — keep looping defensively.
            continue
        process_job(json.loads(job_data))

if __name__ == "__main__":
    main()
