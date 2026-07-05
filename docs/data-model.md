# Data Model & Persistence

## Overview
The persistence layer is built on **PostgreSQL**, leveraging its robust support for JSONB (for flexible OSINT results), UUID types, and efficient indexing strategies. The data model is designed to support the asynchronous job lifecycle defined in the Architecture document.

## Entity Definitions

### -1. Entities (Global Knowledge Graph)
A deduplicated, persistent index of all unique identities discovered across all OSINT operations. This table represents the **Nodes** of the global intelligence graph.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the entity. |
| `value` | `TEXT` | Unique, Not Null | The normalized value (e.g., "j.doe@example.com"). |
| `type` | `VARCHAR(50)` | Not Null | Type of entity ("email", "username", "domain", "phone"). |
| `first_seen_at` | `TIMESTAMPTZ` | Not Null | Timestamp of first discovery. |
| `last_seen_at` | `TIMESTAMPTZ` | Not Null | Timestamp of most recent confirmation/activity. |
| `confidence_score` | `DECIMAL` | Default `1.0` | Aggregated confidence score across all sources. |

### -2. EntityRelationships (The Edges)
Stores persistent connections between entities, enabling cross-subject relationship analysis over time.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the relationship. |
| `source_entity_id` | `UUID` | FK, Not Null | Reference to `entities.id` (the subject). |
| `target_entity_id` | `UUID` | FK, Not Null | Reference to `entities.id` (the object). |
| `relationship_type` | `VARCHAR(50)` | Not Null | Nature of the link ("owns", "posted_on", "registered_with", "associated_with"). |
| `source_job_id` | `UUID` | FK | Reference to `jobs.id` for provenance/audit. |
| `created_at` | `TIMESTAMPTZ` | Not Null | When the link was first established. |
| `last_confirmed_at` | `TIMESTAMPTZ` | Not Null | When the link was last verified. |

### 0. Profiles

### -1. Entities (Global Index)
A deduplicated index of all unique discovered identities (emails, usernames, domains, phones) across all time. This forms the nodes of the intelligence graph.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the entity. |
| `value` | `TEXT` | Unique, Not Null | The normalized value (e.g., "j.doe@example.com"). |
| `type` | `VARCHAR(50)` | Not Null | The entity type ("email", "username", "domain", "phone"). |
| `first_seen_at` | `TIMESTAMPTZ` | Not Null | When this entity was first discovered. |
| `last_seen_at` | `TIMESTAMPTZ` | Not Null | When this entity was last confirmed active. |

### -2. EntityRelationships (The Edges)
Stores the connections between entities, allowing for cross-subject relationship building over time.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the relationship. |
| `source_entity_id` | `UUID` | FK, Not Null | Reference to `entities.id`. |
| `target_entity_id` | `UUID` | FK, Not Null | Reference to `entities.id`. |
| `relationship_type` | `VARCHAR(50)` | Not Null | Nature of the link ("owns", "posted_on", "registered_with"). |
| `confidence_score` | `FLOAT` | Not Null | 0.0 to 1.0 score indicating reliability of the link. |
| `discovered_in_job_id` | `UUID` | FK | Reference to `jobs.id` for provenance. |
| `created_at` | `TIMESTAMPTZ` | Not Null | When the relationship was established. |

### 0. Profiles
A Profile represents a comprehensive view of a target identity, aggregating results from multiple chained OSINT jobs.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the profile. |
| `user_id` | `UUID` | FK, Not Null | Reference to `users.id`. |
| `status` | `VARCHAR(20)` | Not Null | Enum: `"active"`, `"completed"`, `"failed"`. |
| `root_target` | `TEXT` | Not Null | The initial input (e.g., username). |
| `root_type` | `VARCHAR(50)` | Not Null | The initial input type (e.g., "username"). |
| `created_at` | `TIMESTAMPTZ` | Not Null | Profile creation time. |
| `completed_at` | `TIMESTAMPTZ` | Nullable | When the profile reached a terminal state. |
| `max_depth` | `INTEGER` | Not Null | Max hops allowed (derived from user tier: 0, 1, or 3). |

### 1. Users
Stores the identity of the consumers of the API.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the user. |
| `email` | `TEXT` | Unique, Not Null | User's contact email (used for OAuth). |
| `created_at` | `TIMESTAMPTZ` | Not Null, Default `NOW()` | Account creation timestamp. |
| `tier` | `VARCHAR(50)` | Not Null, Default `"free"` | Subscription tier ("free", "pro", "enterprise"). |

### 2. UserCredits
Tracks the credit balance for each user to support the pay-per-use model.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `user_id` | `UUID` | PK, FK | Reference to `users.id`. |
| `balance` | `INTEGER` | Not Null, Default `0` | Current number of available credits. |
| `updated_at` | `TIMESTAMPTZ` | Not Null | Last time the balance changed. |

### 3. Invoices
Records of payment attempts (PayPal or Bitcoin) for auditing.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique invoice identifier. |
| `user_id` | `UUID` | FK, Not Null | Reference to `users.id`. |
| `amount_cents` | `INTEGER` | Not Null | Amount paid in smallest currency unit (e.g., cents). |
| `credits_purchased` | `INTEGER` | Not Null | Number of credits added to balance. |
| `payment_method` | `VARCHAR(50)` | Not Null | "paypal", "bitcoin", "stripe". |
| `status` | `VARCHAR(20)` | Not Null | "pending", "completed", "failed", "refunded". |
| `external_ref` | `TEXT` | Nullable | PayPal Order ID or Bitcoin Transaction ID. |
| `created_at` | `TIMESTAMPTZ` | Not Null | Invoice creation time. |

### 4. ApiKeys
Handles authentication for machine-to-machine (M2M) interactions.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | Unique identifier for the key. |
| `user_id` | `UUID` | FK, Not Null | Reference to `users.id`. |
| `key_hash` | `TEXT` | Unique, Not Null | SHA-256 hash of the API key secret. |
| `scopes` | `JSONB` | Not Null | Array of strings defining permissions (e.g., `["osint:read", "email:search"]`). |
| `rate_limit_tier` | `VARCHAR(50)` | Not Null | Determines rate limit quotas (mapped to `users.tier`). |
| `last_used_at` | `TIMESTAMPTZ` | Nullable | Timestamp of the last successful API request. |

### 3. Jobs
Tracks the lifecycle of OSINT requests. Now supports hierarchical chaining for identity resolution.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | PK | The `job_id` returned to the client. |
| `profile_id` | `UUID` | FK, Nullable | Reference to `profiles.id`. Null for legacy or standalone jobs. |
| `user_id` | `UUID` | FK, Not Null | Reference to `users.id`. |
| `parent_job_id` | `UUID` | FK, Nullable | Reference to `jobs.id`. Used for chaining; identifies the job that spawned this one. |
| `depth` | `INTEGER` | Not Null, Default `0` | Depth in the resolution graph (0 = root input). Enforced by user tier limits. |
| `target_type` | `VARCHAR(50)` | Not Null | The type of target ("username", "email", "domain", "phone"). |
| `target_value` | `TEXT` | Not Null | The actual value being searched (e.g., "johndoe"). |
| `requested_tools` | `JSONB` | Not Null | List of tools to execute (e.g., `["sherlock", "maigret"]`). |
| `status` | `VARCHAR(20)` | Not Null | Enum: `"pending"`, `"processing"", "completed"`, `"failed"`, `"cancelled"`, `"quarantined"`. |
| `created_at` | `TIMESTAMPTZ` | Not Null, Default `NOW()` | Request submission time. |
| `updated_at` | `TIMESTAMPTZ` | Not Null, Auto-update | Last status change timestamp. |
| `expires_at` | `TIMESTAMPTZ` | Not Null | TTL timestamp for automatic deletion. |

### 4. JobResults
Stores the raw and processed output from OSINT tools.

| Field | Type | Attributes | Description |
| :--- | :--- | :--- | :--- |
| `job_id` | `UUID` | FK, Not Null | Reference to `jobs.id`. |
| `tool_name` | `VARCHAR(100)` | Not Null | Name of the tool that generated the result. |
| `status_code` | `INTEGER` | Nullable | Exit code of the underlying tool process. |
| `raw_output` | `TEXT` | Nullable | Standard output (stdout) from the tool. |
| `parsed_data` | `JSONB` | Nullable | Structured data extracted from the raw output. |
| `executed_at` | `TIMESTAMPTZ` | Not Null | When the tool finished execution. |

## Schema Mapping

The following table maps the OpenAPI 3.1 definitions (in `osint-api-spec.yaml`) to the database columns.

| OpenAPI JSON Schema | Database Column | Postgres Type | Rationale |
| :--- | :--- | :--- | :--- |
| `type: string, format: uuid` | `id` (all tables) | `UUID` | Efficient storage and native UUID functions. |
| `type: string, format: email` | `email` | `TEXT` | RFC 5321 compliance is better handled at app layer; `TEXT` allows max length. |
| `type: string` (generic) | `target_value` | `TEXT` | Unbounded length for phone numbers or complex usernames. |
| `type: array` (tools) | `requested_tools` | `JSONB` | Flexible storage for lists of tool names without migration overhead. |
| `type: object` (result) | `parsed_data` | `JSONB` | OSINT results vary wildly per tool; JSONB allows querying inside the data. |
| `enum: [pending, ...]` | `status` | `VARCHAR(20)` | Explicit check constraint will be added to enforce valid states. |

## Relationships

1.  **Users -> Profiles**: One-to-Many. A user can initiate multiple identity resolution profiles.
2.  **Profiles -> Jobs**: One-to-Many. A profile aggregates multiple OSINT jobs (root and chained).
3.  **Jobs -> Jobs**: Self-referencing (Recursive). `parent_job_id` creates a tree structure representing the resolution graph.
4.  **Users -> Jobs**: One-to-Many. A user creates multiple jobs over time (legacy support).
5.  **Jobs -> JobResults**: One-to-Many. A single job (e.g., "Search Username") may yield multiple result entries (one per tool: Sherlock, Maigret, etc.).

## Indexing Strategy

To ensure high performance for the most common query patterns:

*   **`jobs(user_id, created_at DESC)`**: Index for "List my recent jobs" queries.
*   **`jobs(status)`**: Index for Workers polling for `pending` jobs.
*   **`jobs(expires_at)`**: Index for the TTL cleanup background worker.
*   **`api_keys(key_hash)`**: Unique index for fast authentication lookups during every request.
*   **`job_results(job_id)`**: Index for fetching all results associated with a specific job.

### Re-evaluation / Deduplication Indexes
To support the Orchestrator's logic for checking if a tool has already run on a specific entity:
*   **`jobs(profile_id, target_value)`**: Composite index to quickly find all jobs processing a specific entity within a profile.
*   **`jobs(requested_tools)`**: GIN index on the JSONB column to efficiently check for the presence of a specific tool name (e.g., `WHERE 'sherlock' = ANY(requested_tools)`).

## TTL Strategy (Data Retention)

To comply with privacy standards and manage storage costs, OSINT data is ephemeral by design.

### Policy
*   **Retention Period:** 7 days after job completion.
*   **Scope:** Applies to all rows in `jobs` and `job_results`.

### Implementation Plan
1.  **On Creation:** When a `job` is created, `expires_at` is set to `NOW() + INTERVAL '7 days'`.
2.  **On Completion:** If the job fails early, `expires_at` is not shortened; data is kept for the full 7 days for audit debugging.
3.  **Cleanup Job:** A scheduled background process runs hourly:
    ```sql
    DELETE FROM job_results WHERE job_id IN (SELECT id FROM jobs WHERE expires_at < NOW());
    DELETE FROM jobs WHERE expires_at < NOW();
    ```
4.  **GDPR/CCPA:** If a user requests account deletion, their data (including `users`, `api_keys`, and all historical `jobs`) is purged immediately, overriding the 7-day policy.