import os
import re
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field, field_validator
import redis
from sqlalchemy.orm import Session

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.db import engine, get_db, SessionLocal, User, UserCredits, Profile, Job, Invoice

# --- Configuration ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CREDIT_COST_PROFILE = 10  # Example cost

app = FastAPI(title="OSINT API Gateway")
redis_client = redis.from_url(REDIS_URL)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
