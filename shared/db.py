import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, Column, String, Integer, DECIMAL, Text, ForeignKey, DateTime, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:pass@localhost/osint_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(Text, nullable=False, unique=True)
    tier = Column(String(50), nullable=False, default='free')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    credits = relationship("UserCredits", back_populates="user", uselist=False, cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="user", cascade="all, delete-orphan")

class UserCredits(Base):
    __tablename__ = "user_credits"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="credits")

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_hash = Column(Text, nullable=False, unique=True)
    scopes = Column(JSONB, nullable=False)  # e.g., ["osint:read", "osint:write"]
    rate_limit_tier = Column(String(50), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="api_keys")

class Profile(Base):
    __tablename__ = "profiles"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False)  # 'active', 'completed', 'failed'
    root_target = Column(Text, nullable=False)
    root_type = Column(String(50), nullable=False) # 'username', 'email', 'domain', 'phone'
    max_depth = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="profiles")
    jobs = relationship("Job", back_populates="profile", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_id = Column(PG_UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    parent_job_id = Column(PG_UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    depth = Column(Integer, nullable=False, default=0)
    target_type = Column(String(50), nullable=False)
    target_value = Column(Text, nullable=False)
    requested_tools = Column(JSONB, nullable=False) # List of tool names to run
    status = Column(String(20), nullable=False) # 'pending', 'processing', 'completed', 'failed', 'cancelled', 'quarantined'
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()) # Should be set to NOW() + 7 days

    # Relationships
    profile = relationship("Profile", back_populates="jobs")
    results = relationship("JobResult", back_populates="job", cascade="all, delete-orphan")
    parent_job = relationship("Job", remote_side=[id])
    child_jobs = relationship("Job", remote_side=[parent_job_id])

class JobResult(Base):
    __tablename__ = "job_results"

    job_id = Column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    tool_name = Column(String(100), primary_key=True)
    status_code = Column(Integer, nullable=True)
    raw_output = Column(Text, nullable=True)
    parsed_data = Column(JSONB, nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    job = relationship("Job", back_populates="results")

class Entity(Base):
    __tablename__ = "entities"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    value = Column(Text, nullable=False, unique=True)
    type = Column(String(50), nullable=False) # 'username', 'email', 'domain', 'phone'
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    confidence_score = Column(DECIMAL, nullable=False, default=1.0)

class EntityRelationship(Base):
    __tablename__ = "entity_relationships"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_entity_id = Column(PG_UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    target_entity_id = Column(PG_UUID(as_uuid=True), ForeignKey("entities.id"), nullable=False)
    relationship_type = Column(String(50), nullable=False) # 'found_in', 'owns', 'associated_with'
    source_job_id = Column(PG_UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_confirmed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    credits_purchased = Column(Integer, nullable=False)
    payment_method = Column(String(50), nullable=False) # 'paypal', 'btcpay'
    status = Column(String(20), nullable=False) # 'pending', 'completed', 'failed', 'refunded'
    external_ref = Column(Text, nullable=True) # Invoice ID from PayPal/BTCPay
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="invoices")
