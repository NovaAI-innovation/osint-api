import os
import time
import json
import redis
import sys

# Add shared module to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import SessionLocal

REDIS_URL = os.getenv("REDIS_URL")
r = redis.from_url(REDIS_URL)

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
