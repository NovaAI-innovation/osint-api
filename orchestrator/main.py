import os
import re
import json
import time
import logging
from datetime import datetime
from typing import List, Tuple, Set

import redis
from sqlalchemy.orm import Session

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import SessionLocal, Job, JobResult, Profile, Entity

# --- Configuration ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
POLL_INTERVAL_SECONDS = 10

redis_client = redis.from_url(REDIS_URL)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Tool Capability Registry ---
# Maps entity types to tools that can process them
TOOL_REGISTRY = {
    "username": ["sherlock", "maigret"],
    "email": ["sherlock", "holehe", "theHarvester"],
    "domain": ["theHarvester"]
}

# --- Regex Patterns for Entity Extraction ---
PATTERNS = {
    "email": re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
    "domain": re.compile(r'(?:https?:\/\/)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'),
    "username": re.compile(r'(?:(?:https?:\/\/)?(?:www\.)?(?:twitter|github|instagram|facebook|linkedin)\.com\/)?([a-zA-Z0-9_-]{3,30})')
}

def extract_entities(text: str) -> List[Tuple[str, str]]:
    """
    Scan text for entities and return list of (type, value) tuples.
    """
    entities = []
    for entity_type, pattern in PATTERNS.items():
        matches = pattern.findall(text)
        for match in matches:
            # Ensure matches are strings
            val = match if isinstance(match, str) else match[0] if isinstance(match, tuple) else str(match)
            entities.append((entity_type, val.lower().strip()))
    return list(set(entities)) # Deduplicate within the text

def get_or_create_entity(db: Session, value: str, entity_type: str) -> Entity:
    """
    Check Knowledge Graph for entity, update timestamp, or create new.
    """
    entity = db.query(Entity).filter(Entity.value == value, Entity.type == entity_type).first()
    if entity:
        entity.last_seen_at = datetime.utcnow()
    else:
        entity = Entity(value=value, type=entity_type, first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow())
        db.add(entity)
    return entity

def process_job(job_id: str, db: Session):
    """
    Core logic: Read results -> Extract Entities -> Check Depth -> Queue new Jobs.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        logger.warning(f"Job {job_id} not found.")
        return
    
    if not job.profile_id:
        logger.info(f"Job {job_id} has no profile_id. Skipping.")
        return

    profile = db.query(Profile).filter(Profile.id == job.profile_id).first()
    if not profile:
        logger.warning(f"Profile {job.profile_id} not found for Job {job_id}.")
        return

    # 1. Gather all text data from JobResults
    results = db.query(JobResult).filter(JobResult.job_id == job.id).all()
    full_text = ""
    for res in results:
        # We parse raw_output (text) or parsed_data (JSON -> string)
        if res.raw_output:
            full_text += res.raw_output + " "
        if res.parsed_data:
            full_text += json.dumps(res.parsed_data) + " "

    if not full_text.strip():
        logger.info(f"No text output found for Job {job_id}.")
        return

    # 2. Extract Entities
    found_entities = extract_entities(full_text)
    logger.info(f"Extracted {len(found_entities)} entities from Job {job_id}.")

    new_jobs_queued = 0

    for entity_type, entity_value in found_entities:
        # Skip if entity type is not supported by our registry
        if entity_type not in TOOL_REGISTRY:
            continue

        # 3. Update Knowledge Graph
        get_or_create_entity(db, entity_value, entity_type)

        # 4. Check Depth Limits
        # We create a child job at depth + 1
        if job.depth + 1 > profile.max_depth:
            logger.debug(f"Max depth reached for Profile {profile.id}. Skipping {entity_value}.")
            continue

        # 5. Deduplication: Check if we already queued or ran a job for this entity in this profile
        # We look for any job in this profile that targets this value
        existing_job = db.query(Job).filter(
            Job.profile_id == profile.id,
            Job.target_value == entity_value
        ).first()

        if existing_job:
            logger.debug(f"Entity {entity_value} already processed/queued in Profile {profile.id}.")
            continue

        # 6. Create New Job & Queue
        # Determine which tools to run based on entity type
        tools_to_run = TOOL_REGISTRY.get(entity_type, [])
        
        if not tools_to_run:
            continue

        new_job = Job(
            profile_id=profile.id,
            user_id=job.user_id,
            parent_job_id=job.id,
            depth=job.depth + 1,
            target_type=entity_type,
            target_value=entity_value,
            requested_tools=tools_to_run,
            status='pending'
        )
        db.add(new_job)
        db.flush() # Ensure we have the ID before committing
        
        # Push to Redis
        job_payload = {
            "job_id": str(new_job.id),
            "target_type": new_job.target_type,
            "target_value": new_job.target_value,
            "tools": new_job.requested_tools
        }
        
        try:
            redis_client.rpush("osint_jobs", json.dumps(job_payload))
            new_jobs_queued += 1
            logger.info(f"Queued new job {new_job.id} for entity {entity_value} ({entity_type}).")
        except Exception as e:
            logger.error(f"Failed to queue job {new_job.id}: {e}")
            db.rollback()
            return # Stop processing this job if queue fails

    if new_jobs_queued > 0:
        db.commit()

def main_loop():
    logger.info("Starting Orchestrator polling loop...")
    
    while True:
        db = SessionLocal()
        try:
            # Find jobs that are completed but might not have been fully processed by the orchestrator.
            # Simple strategy: Check jobs updated in the last X minutes that are 'completed'.
            # To prevent infinite loops, we rely on the deduplication check inside process_job.
            # We query for jobs updated recently to avoid scanning the whole history every time.
            
            # Note: A more robust production system would use a dedicated 'orchestrated_at' timestamp column.
            recent_cutoff = datetime.utcnow() - timedelta(minutes=5)
            
            completed_jobs = db.query(Job).filter(
                Job.status == 'completed',
                Job.updated_at >= recent_cutoff
            ).all()
            
            logger.info(f"Found {len(completed_jobs)} completed jobs to check.")
            
            for job in completed_jobs:
                try:
                    process_job(str(job.id), db)
                except Exception as e:
                    logger.error(f"Error processing job {job.id}: {e}")
                    db.rollback()
        
        except Exception as e:
            logger.error(f"Orchestrator loop error: {e}")
            db.rollback()
        finally:
            db.close()
        
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    from datetime import timedelta
    main_loop()
