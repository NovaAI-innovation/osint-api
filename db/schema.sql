-- OSINT Identity Resolution Platform Schema
-- PostgreSQL 15+

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- For hashing API keys

-- 1. Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    tier VARCHAR(50) NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. UserCredits
CREATE TABLE user_credits (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    balance INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. ApiKeys
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    scopes JSONB NOT NULL,
    rate_limit_tier VARCHAR(50) NOT NULL,
    last_used_at TIMESTAMPTZ
);

-- 4. Profiles
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('active', 'completed', 'failed')),
    root_target TEXT NOT NULL,
    root_type VARCHAR(50) NOT NULL,
    max_depth INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 5. Jobs
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id),
    parent_job_id UUID REFERENCES jobs(id),
    depth INTEGER NOT NULL DEFAULT 0,
    target_type VARCHAR(50) NOT NULL,
    target_value TEXT NOT NULL,
    requested_tools JSONB NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled', 'quarantined')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days'
);

-- Indexes for Jobs (Deduplication & Speed)
CREATE INDEX idx_jobs_profile_target ON jobs(profile_id, target_value);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_requested_tools ON jobs USING GIN (requested_tools);
CREATE INDEX idx_jobs_expires ON jobs(expires_at);

-- 6. JobResults
CREATE TABLE job_results (
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    status_code INTEGER,
    raw_output TEXT,
    parsed_data JSONB,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, tool_name)
);

-- 7. Entities (Global Knowledge Graph Nodes)
CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    value TEXT NOT NULL UNIQUE,
    type VARCHAR(50) NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence_score DECIMAL DEFAULT 1.0
);

-- 8. EntityRelationships (Global Knowledge Graph Edges)
CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_entity_id UUID NOT NULL REFERENCES entities(id),
    target_entity_id UUID NOT NULL REFERENCES entities(id),
    relationship_type VARCHAR(50) NOT NULL,
    source_job_id UUID REFERENCES jobs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. Invoices
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    amount_cents INTEGER NOT NULL,
    credits_purchased INTEGER NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
    external_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
