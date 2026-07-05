import os
import time
import redis
import sys

# Add shared module to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import SessionLocal

REDIS_URL = os.getenv("REDIS_URL")
r = redis.from_url(REDIS_URL)

def process_job(job_data):
    print(f"Processing job: {job_data['job_id']}")
    # TODO: Execute OSINT tool based on job_data['tool_name']
    # TODO: Update database with results
    pass

def main():
    print("Worker started...")
    while True:
        # Blocking pop from 'jobs' queue
        _, job_data = r.brpop('jobs')
        # Assuming job_data is JSON string
        import json
        process_job(json.loads(job_data))

if __name__ == "__main__":
    main()