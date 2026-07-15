import os
import re
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import redis
from sqlalchemy.orm import Session

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import engine, get_db, SessionLocal, User, UserCredits, Profile, Job, Invoice

# --- Configuration ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CREDIT_COST_PROFILE = 10  # Example cost

# CORS: comma-separated list of origins. "*" means allow any origin
# (fine for dev with no cookies; unsafe for prod with credentials).
# Default "*" so the HTML UI on a different port can call the API in dev.
# Production should set OSINT_CORS_ORIGINS="https://app.example.com" explicitly.
CORS_ORIGINS_RAW = os.getenv("OSINT_CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()] or ["*"]

app = FastAPI(title="OSINT API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "api-key", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Type", "X-Request-ID"],
    max_age=600,  # cache preflight 10 min
)

redis_client = redis.from_url(REDIS_URL)


@app.get("/healthz", tags=["meta"])
def healthz():
    """Lightweight liveness probe used by the HTML UI and external monitors.

    Returns 200 even if Redis is briefly unreachable - we only need to know
    the FastAPI worker itself is up. A separate readiness probe (TODO: future)
    will check downstream Redis/Postgres.
    """
    return {"status": "ok", "service": "osint-api-gateway"}

# --- Request/Response Schemas ---

class ProfileCreateRequest(BaseModel):
    target: str = Field(..., description="The target to investigate (e.g., username, email, domain)")
    target_type: str = Field(..., description="Type of target: username, email, domain, phone")
    tools: List[str] = Field(default=[], description="List of tools to run. Empty implies default for type.")
    max_depth: int = Field(default=1, ge=0, le=3, description="Graph traversal depth")

    @field_validator('target_type')
    @classmethod
    def validate_target_type(cls, v):
        allowed = ['username', 'email', 'domain', 'phone']
        if v not in allowed:
            raise ValueError(f"target_type must be one of {allowed}")
        return v

    @field_validator('target')
    @classmethod
    def validate_target(cls, v, info):
        t_type = info.data.get('target_type') if info.data else None
        if t_type == 'email':
            if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", v):
                raise ValueError("Invalid email format")
        elif t_type == 'domain':
            if not re.match(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.[A-Za-z]{2,6}$", v):
                raise ValueError("Invalid domain format")
        elif t_type == 'phone':
            if not re.match(r"^\+[1-9]\d{1,14}$", v):
                raise ValueError("Phone must be E.164 format (e.g. +1234567890)")
        elif t_type == 'username':
            if not re.match(r"^[a-zA-Z0-9_-]{3,30}$", v):
                raise ValueError("Username must be 3-30 alphanumeric characters")
        return v.strip()

class ProfileResponse(BaseModel):
    profile_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    message: str

class CreditPurchaseRequest(BaseModel):
    amount_cents: int
    payment_method: str  # 'paypal' or 'btcpay'

class InvoiceResponse(BaseModel):
    invoice_id: uuid.UUID
    status: str
    checkout_url: str

# --- Dependencies ---

def get_api_key(api_key: Optional[str] = Header(...)):
    """Simple API Key validation. In production, hash lookup in DB."""
    # Mock: Accept any key that starts with 'osint_'
    if not api_key or not api_key.startswith("osint_"):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    # In a real app, we would decode the key to get user_id
    # For this implementation, we assume a fixed user or lookup
    return "user_id_from_key" # Placeholder user ID

def get_current_user(user_id: str = Depends(get_api_key), db: Session = Depends(get_db)):
    """Fetch user from DB based on API key user_id (mocked)."""
    # Mocking user lookup. In reality, derive user_id from validated API Key
    user = db.query(User).filter(User.email == "demo@osint.api").first()
    if not user:
        # Create a demo user if not exists
        user = User(email="demo@osint.api", tier="pro")
        db.add(user)
        db.commit()
        db.refresh(user)
        # Add credits
        credits = UserCredits(user_id=user.id, balance=100)
        db.add(credits)
        db.commit()
    return user

# --- Endpoints ---

@app.post("/v1/profiles", response_model=ProfileResponse)
def create_profile(
    payload: ProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    1. Validate Input
    2. Check/Deduct Credits
    3. Create Profile & Root Job
    4. Push to Redis
    """
    
    # 1. Check Credits
    user_credits = db.query(UserCredits).filter(UserCredits.user_id == current_user.id).first()
    if not user_credits or user_credits.balance < CREDIT_COST_PROFILE:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    
    # 2. Create Profile
    profile = Profile(
        user_id=current_user.id,
        status='active',
        root_target=payload.target,
        root_type=payload.target_type,
        max_depth=payload.max_depth
    )
    db.add(profile)
    db.flush() # Get ID
    
    # 3. Create Root Job
    # Default tools if not provided
    requested_tools = payload.tools if payload.tools else ['sherlock'] 
    
    # Ensure job expires in 7 days
    expires_at = datetime.utcnow() + timedelta(days=7)
    
    job = Job(
        profile_id=profile.id,
        user_id=current_user.id,
        depth=0,
        target_type=payload.target_type,
        target_value=payload.target,
        requested_tools=requested_tools,
        status='pending',
        expires_at=expires_at
    )
    db.add(job)
    
    # 4. Deduct Credits
    user_credits.balance -= CREDIT_COST_PROFILE
    
    db.commit()
    db.refresh(job)
    
    # 5. Push to Redis Queue
    job_payload = {
        "job_id": str(job.id),
        "target_type": job.target_type,
        "target_value": job.target_value,
        "tools": job.requested_tools
    }
    try:
        redis_client.rpush("osint_jobs", json.dumps(job_payload))
    except Exception as e:
        # Rollback if queue fails
        db.rollback()
        raise HTTPException(status_code=503, detail="Job queue unavailable")
    
    return ProfileResponse(
        profile_id=profile.id,
        job_id=job.id,
        status="pending",
        message="Profile created and job queued"
    )

@app.post("/v1/credits/purchase", response_model=InvoiceResponse)
def purchase_credits(
    payload: CreditPurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create an invoice record. 
    Returns a mock checkout URL (in reality, this would call PayPal/BTCPay API)
    """
    
    if payload.payment_method not in ['paypal', 'btcpay']:
        raise HTTPException(status_code=400, detail="Invalid payment method")
    
    invoice = Invoice(
        user_id=current_user.id,
        amount_cents=payload.amount_cents,
        credits_purchased=payload.amount_cents // 10, # 10 cents per credit logic
        payment_method=payload.payment_method,
        status='pending',
        external_ref=None # Will be set when provider returns ID
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    
    # Mock URL generation
    checkout_url = f"https://checkout.osint.api/pay/{invoice.id}"
    
    return InvoiceResponse(
        invoice_id=invoice.id,
        status="pending",
        checkout_url=checkout_url
    )


# --- Dev / Free Search Endpoint (DEVELOPMENT ONLY) ---
#
# Purpose:
#   Give frontend devs and CI a way to exercise the OSINT pipeline UI without
#   an API key, without credits, without a running worker, and without writing
#   to the database. Returns a deterministic mocked result for any
#   (target_type, target) so the HTML UI can render against it.
#
#   Production deployments MUST disable this endpoint (set
#   OSINT_ENABLE_FREE_SEARCH=false in the gateway environment).

ENABLE_FREE_SEARCH = os.getenv("OSINT_ENABLE_FREE_SEARCH", "true").lower() in ("1", "true", "yes")


def _free_search_mock(target_type: str, target: str) -> dict:
    """Build a deterministic mock OSINT result for dev. Pure function, no I/O."""
    # Deterministic per (target_type, target) so repeated calls return
    # the same shape, which is what frontend tests expect.
    seed = abs(hash((target_type.lower(), target.lower()))) % 1000

    base = {
        "tool": f"{target_type}-probe",
        "target_type": target_type,
        "target_value": target,
        "source": "mock",
        "seed": seed,
    }

    if target_type == "username":
        base["matches"] = [
            {"site": "GitHub",   "url": f"https://github.com/{target}",   "status": "available" if seed % 2 == 0 else "claimed"},
            {"site": "Twitter",  "url": f"https://twitter.com/{target}",  "status": "available" if seed % 3 == 0 else "claimed"},
            {"site": "Reddit",   "url": f"https://reddit.com/u/{target}",  "status": "available" if seed % 5 == 0 else "taken"},
        ]
    elif target_type == "email":
        domain = target.split("@", 1)[1] if "@" in target else "unknown.local"
        base["matches"] = [
            {"service": "Gravatar",       "url": f"https://www.gravatar.com/avatar/{target}", "status": "found" if seed % 2 == 0 else "missing"},
            {"service": "GitHub Commits", "url": f"https://github.com/search?q={target}&type=commits", "status": "found" if seed % 3 == 0 else "none"},
            {"service": "HaveIBeenPwned", "url": f"https://haveibeenpwned.com/unifiedsearch/{target}", "breaches": seed % 4},
            {"domain_hint": domain},
        ]
    elif target_type == "domain":
        base["matches"] = [
            {"type": "A",    "value": f"203.0.113.{seed % 254 + 1}"},
            {"type": "MX",   "value": f"mail.{target}"},
            {"type": "NS",   "value": f"ns1.{target}"},
            {"type": "TXT",  "value": "v=spf1 include:_spf.{target} -all"},
        ]
    elif target_type == "phone":
        base["matches"] = [
            {"carrier": "mock-carrier", "country": "US" if target.startswith("+1") else "??", "line_type": "mobile"},
            {"spam_score": (seed % 100) / 100.0},
        ]
    else:
        base["matches"] = []

    return base


class FreeSearchRequest(BaseModel):
    target_type: str = Field(..., description="username | email | domain | phone")
    target: str = Field(..., description="The target value to probe")

    @field_validator("target_type")
    @classmethod
    def _v_type(cls, v):
        allowed = {"username", "email", "domain", "phone"}
        if v not in allowed:
            raise ValueError(f"target_type must be one of {sorted(allowed)}")
        return v


class FreeSearchResponse(BaseModel):
    dev_mode: bool = True
    target_type: str
    target: str
    result: dict


def _serve_free_search(target_type: str, target: str) -> FreeSearchResponse:
    """Internal helper used by both GET and POST variants of /dev/free-search.

    Raises 422 if target_type is not one of the supported values, so the
    GET and POST variants behave consistently.
    """
    allowed = {"username", "email", "domain", "phone"}
    if target_type not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"target_type must be one of {sorted(allowed)}",
        )
    return FreeSearchResponse(
        target_type=target_type,
        target=target,
        result=_free_search_mock(target_type, target),
    )


@app.get("/dev/free-search", response_model=FreeSearchResponse)
def free_search_get(
    target_type: str,
    target: str,
):
    """Dev-only: synchronous mock OSINT lookup. No auth, no credits, no DB writes.

    Disable in production by setting OSINT_ENABLE_FREE_SEARCH=false.
    """
    if not ENABLE_FREE_SEARCH:
        raise HTTPException(status_code=404, detail="Not Found")
    return _serve_free_search(target_type, target)


@app.post("/dev/free-search", response_model=FreeSearchResponse)
def free_search_post(payload: FreeSearchRequest):
    """POST variant of /dev/free-search. Same semantics as GET."""
    if not ENABLE_FREE_SEARCH:
        raise HTTPException(status_code=404, detail="Not Found")
    return _serve_free_search(payload.target_type, payload.target)


# --- Real Job Read Endpoint ---
#
# The OpenAPI spec and the HTML UI both promise `GET /v1/jobs/{id}` to
# inspect a job's status and collected tool results. This endpoint does
# NOT consume credits; it only reads existing rows.

class JobResultRead(BaseModel):
    tool_name: str
    status_code: Optional[int] = None
    raw_output: Optional[str] = None
    parsed_data: Optional[dict] = None
    executed_at: Optional[str] = None


class JobRead(BaseModel):
    job_id: uuid.UUID
    profile_id: Optional[uuid.UUID] = None
    parent_job_id: Optional[uuid.UUID] = None
    depth: int
    target_type: str
    target_value: str
    requested_tools: List[str]
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None
    results: List[JobResultRead] = []


# --- Recursive profile (identity-resolution cascade) ---
#
# The orchestrator chains child jobs automatically when a job completes,
# so a single POST /v1/profiles can grow into a tree of depth N. The
# following endpoints let a client fetch the full tree, block until the
# cascade is done, or cancel a long-running cascade.

class JobNodeRead(JobRead):
    """A job plus its recursively-loaded child jobs."""
    children: List["JobNodeRead"] = []


JobNodeRead.model_rebuild()


class ProfileRead(BaseModel):
    profile_id: uuid.UUID
    status: str
    root_target: str
    root_type: str
    max_depth: int
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    # The full job tree, rooted at the root job (depth 0).
    tree: List[JobNodeRead] = []
    # Aggregate counts for quick status checks.
    counts: dict = {}


def _load_job_tree(db: Session, root_jobs: list) -> List[JobNodeRead]:
    """Recursively load all jobs in a profile as a tree.

    Uses a single SELECT for all jobs in the profile, then builds the
    tree in memory. Avoids N+1 queries for arbitrarily deep cascades.
    """
    if not root_jobs:
        return []

    profile_id = root_jobs[0].profile_id
    all_jobs = db.query(Job).filter(Job.profile_id == profile_id).all()

    # Build a map id -> JobNodeRead.
    nodes: dict = {}
    for j in all_jobs:
        nodes[j.id] = JobNodeRead(
            job_id=j.id,
            profile_id=j.profile_id,
            parent_job_id=j.parent_job_id,
            depth=j.depth,
            target_type=j.target_type,
            target_value=j.target_value,
            requested_tools=j.requested_tools or [],
            status=j.status,
            created_at=_iso(j.created_at),
            updated_at=_iso(j.updated_at),
            expires_at=_iso(j.expires_at),
            results=[
                JobResultRead(
                    tool_name=r.tool_name,
                    status_code=r.status_code,
                    raw_output=r.raw_output,
                    parsed_data=r.parsed_data,
                    executed_at=_iso(r.executed_at),
                )
                for r in (j.results or [])
            ],
            children=[],
        )

    # Wire up children under their parents.
    roots: List[JobNodeRead] = []
    for j in all_jobs:
        node = nodes[j.id]
        parent_id = j.parent_job_id
        if parent_id and parent_id in nodes:
            nodes[parent_id].children.append(node)
        else:
            roots.append(node)
    # Stable ordering: depth then target_value.
    roots.sort(key=lambda n: (n.depth, n.target_value))
    for n in nodes.values():
        n.children.sort(key=lambda c: (c.depth, c.target_value))
    return roots


def _profile_counts(jobs) -> dict:
    """Bucket jobs by status for a quick progress summary."""
    counts: dict = {}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    counts["total"] = sum(c for k, c in counts.items() if k != "total")
    return counts


def _load_profile(db: Session, profile_id: uuid.UUID, current_user) -> ProfileRead:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    jobs = db.query(Job).filter(Job.profile_id == profile_id).all()
    tree = _load_job_tree(db, jobs)
    return ProfileRead(
        profile_id=profile.id,
        status=profile.status,
        root_target=profile.root_target,
        root_type=profile.root_type,
        max_depth=profile.max_depth,
        created_at=_iso(profile.created_at),
        completed_at=_iso(profile.completed_at),
        tree=tree,
        counts=_profile_counts(jobs),
    )


@app.get("/v1/profiles/{profile_id}", response_model=ProfileRead)
def read_profile(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a profile with the full job tree (root + all recursive children).

    Auth required, tenancy-scoped to the profile owner, no credit cost.
    Use `?wait=true&timeout_s=60` to block until the cascade finishes.
    """
    return _load_profile(db, profile_id, current_user)


@app.get("/v1/profiles/{profile_id}/wait", response_model=ProfileRead)
def wait_for_profile(
    profile_id: uuid.UUID,
    timeout_s: int = 60,
    poll_interval_s: float = 1.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Block (poll DB) until no jobs in the profile are pending/processing
    OR until `timeout_s` elapses. Returns the full profile tree.

    Useful for one-shot callers that want the entire recursive search
    sequence to complete before responding. The HTTP connection stays
    open for up to `timeout_s` seconds.
    """
    if timeout_s < 1:
        raise HTTPException(status_code=400, detail="timeout_s must be >= 1")
    if timeout_s > 600:
        raise HTTPException(status_code=400, detail="timeout_s must be <= 600")
    if poll_interval_s < 0.1 or poll_interval_s > 10:
        raise HTTPException(status_code=400, detail="poll_interval_s must be in [0.1, 10]")

    # Authorise up front.
    _load_profile(db, profile_id, current_user)

    import time as _time
    deadline = _time.monotonic() + timeout_s
    while _time.monotonic() < deadline:
        db.expire_all()
        pending = (
            db.query(Job)
            .filter(
                Job.profile_id == profile_id,
                Job.status.in_(["pending", "processing"]),
            )
            .count()
        )
        if pending == 0:
            break
        _time.sleep(poll_interval_s)

    # Refresh and return the final tree.
    db.expire_all()
    return _load_profile(db, profile_id, current_user)


@app.post("/v1/profiles/{profile_id}/cancel")
def cancel_profile(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel all pending/processing jobs in the profile.

    Marks every still-running job in the profile as 'cancelled' and
    closes the profile. The worker picks up status='cancelled' and
    skips them.
    """
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.utcnow()
    cancelled = 0
    jobs = (
        db.query(Job)
        .filter(
            Job.profile_id == profile_id,
            Job.status.in_(["pending", "processing"]),
        )
        .all()
    )
    for j in jobs:
        j.status = "cancelled"
        j.updated_at = now
        cancelled += 1
    if profile.status == "active":
        profile.status = "completed"
        profile.completed_at = now
    db.commit()
    return {
        "profile_id": str(profile_id),
        "cancelled_jobs": cancelled,
        "status": profile.status,
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


@app.get("/v1/jobs/{job_id}", response_model=JobRead)
def read_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a job and its tool results. Auth required, no credit cost."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Tenancy: a job can only be read by its owning user.
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    results = [
        JobResultRead(
            tool_name=r.tool_name,
            status_code=r.status_code,
            raw_output=r.raw_output,
            parsed_data=r.parsed_data,
            executed_at=_iso(r.executed_at),
        )
        for r in (job.results or [])
    ]

    return JobRead(
        job_id=job.id,
        profile_id=job.profile_id,
        parent_job_id=job.parent_job_id,
        depth=job.depth,
        target_type=job.target_type,
        target_value=job.target_value,
        requested_tools=job.requested_tools or [],
        status=job.status,
        created_at=_iso(job.created_at),
        updated_at=_iso(job.updated_at),
        expires_at=_iso(job.expires_at),
        results=results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
