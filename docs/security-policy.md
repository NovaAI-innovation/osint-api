# Security & Compliance Policy

## Overview
This document defines the operational security rules for the OSINT API. Given the sensitive nature of personal information gathering, strict adherence to these policies is mandatory for all operational tiers.

## 1. Rate Limiting

To prevent abuse and ensure fair resource allocation, rate limits are enforced based on the user's subscription tier (`users.tier`).

### Tiers and Limits

| Tier | Request Limit | Window | Burst Allowance |
| :--- | :--- | :--- | :--- |
| **Free** | 10 requests | 1 minute | +5 requests |
| **Pro** | 100 requests | 1 minute | +20 requests |
| **Enterprise** | 1000 requests | 1 minute | +100 requests |

### Enforcement Mechanism
1.  **Token Bucket Algorithm:** Used to allow bursting within defined limits.
2.  **Headers:** All responses include HTTP headers indicating the limit status:
    *   `X-RateLimit-Limit`: The maximum requests allowed in the window.
    *   `X-RateLimit-Remaining`: The requests remaining in the current window.
    *   `X-RateLimit-Reset`: Unix timestamp when the window resets.
3.  **Violation:** If a limit is exceeded, the API returns `429 Too Many Resources`. The `Retry-After` header indicates the seconds to wait.

### Special Limits
*   **Job Polling:** `GET /v1/jobs/{id}` is exempt from general rate limits but is throttled to 1 request per second per job ID to prevent tight loops.

## 2. Input Sanitization

All inputs passed to OSINT tools must be validated and sanitized at the Gateway before queueing to prevent command injection or crashes in the Worker nodes.

### Target-Specific Rules

| Input Type | Validation Rule | Sanitization Action |
| :--- | :--- | :--- |
| **Username** | Regex `^[a-zA-Z0-9_-]{3,30}$` | Reject if fails regex. Trim whitespace. |
| **Email** | RFC 5322 Regex + Domain Resolution check | Reject if malformed. Lowercase domain part. |
| **Domain** | RFC 1123 Regex + `dig` check | Reject if invalid TLD. Strip `http://` or `https://`. |
| **Phone** | E.164 Format (`+[1-9]\d{1,14}`) | Reject if fails regex. Strip dashes/spaces. |
| **Tool List** | Enum against allow-list (`sherlock`, `maigret`, `theHarvester`) | Reject unknown tools silently (security by obscurity). |

### Command Construction Safety
*   **Worker Execution:** Workers must use subprocess APIs that separate the command from arguments (e.g., `subprocess.run` with a list, not a shell string).
*   **Argument Escaping:** All target values passed to external tools must be shell-escaped before execution.

## 3. Chaining Limits & Cost Control

To monetize the "Full Profile" feature while preventing resource exhaustion, the Orchestrator enforces strict limits on the resolution graph.

### Graph Traversal Rules

| Tier | Max Depth (Hops) | Max Fan-out per Node | Auto-Expansion |
| :--- | :--- | :--- | :--- |
| **Free** | 0 | 0 | Disabled (Root tool execution only). |
| **Pro** | 1 | 5 | Enabled (Emails/Domains only). |
| **Enterprise** | 3 | 20 | Enabled (All valid entities). |

### Enforcement Mechanism
1.  **Depth Check:** Before creating a child job, the Orchestrator checks `parent.depth + 1`. If it exceeds `profile.max_depth`, the entity is logged but not queued.
2.  **Fan-out Check:** A single `JobResult` cannot trigger more than the defined Max Fan-out. If a tool returns 50 emails, only the top N (e.g., 5) are queued for further investigation.
3.  **Cycle Detection:** The Orchestrator maintains a bloom filter or cache of `target_value` within the current `Profile`. If an entity is seen twice, it is ignored to prevent infinite loops.

## 4. Quarantine Policy

If an OSINT tool returns content that is potentially malicious, illegal, or violates the Terms of Service, the system must react defensively.

### Trigger Conditions
*   **Malware Signatures:** The output contains a known file signature for malware (e.g., PE header, ELF magic bytes).
*   **Illegal Content:** The tool result indicates access to leaked credit card numbers, social security numbers, or explicit non-consensual imagery.
*   **PII Overflow:** The result returns > 500 records of personally identifiable information (PII) in a single request, suggesting a bulk scrape (violating acceptable use).

### Quarantine Workflow
1.  **Detection:** The Worker Node parses the tool output against signatures.
2.  **Flagging:** The `jobs` table is updated with status `quarantined`.
3.  **Client Response:** The `GET /v1/jobs/{id}` endpoint returns `403 Forbidden` with a generic error message: `"Result withheld due to policy violation."`. No raw data is returned.
4.  **Admin Notification:** An alert is sent to the operations team (via the Monitoring system) containing:
    *   `job_id`
    *   `user_id`
    *   `tool_name`
    *   `reason_code` (e.g., `MALWARE_DETECTED`, `PII_BULK_SCRAPE`)
5.  **Audit Log:** The event is logged in a secure, append-only audit log.

## 4. Global Graph Access Control

The persistent `Entities` and `EntityRelationships` tables constitute a sensitive intelligence database.

### Access Rules

| Tier | Access Level | Description |
| :--- | :--- | :--- |
| **Free** | None | Cannot query historical data or cross-subject relationships. Only sees ephemeral job results. |
| **Pro** | Read-Only (Self) | Can query the graph, but results are filtered to only show entities linked to their own `user_id` (via `profiles`). |
| **Enterprise** | Full Access | Can query the entire global graph to find cross-subject relationships (e.g., "Show all users linked to domain X"). |

### Scope Requirements
*   `graph:read`: Required to access the Knowledge Graph endpoints.
*   `graph:admin`: Required to prune or modify graph data (internal use only).

## 5. Webhook Security (Billing)

To prevent fraudulent credit issuance, the Billing Service MUST verify the authenticity of incoming payment notifications.

### PayPal Verification
1.  **Headers:** Verify `PayPal-Auth-Algo` and `PayPAL-Transmisson-Sig`.
2.  **Cert Store:** Verify against PayPal's public certificates.

### BTCPay Server (Decentralized) Verification
1.  **Header:** Verify the `BTCPay-Sig` header (HMAC SHA256).
2.  **Secret:** Recompute the hash using the `BTCPAY_WEBHOOK_SECRET` configured in the Billing Service.
3.  **Comparison:** If the computed hash does not match `BTCPay-Sig`, reject with `403 Forbidden`.

### General Rules
*   **Idempotency:** Ensure `external_ref` (Invoice ID) has not already been processed to prevent double-spending if the webhook is received twice.

### Rules
*   Never trust the `status="completed"` field in the webhook body alone without verifying the signature.
*   Implement idempotency: Ensure `external_ref` (Order ID) has not already been processed to prevent double-spending if the webhook is received twice.

## 6. Compliance Checklist

### GDPR (General Data Protection Regulation)

| Requirement | Implementation Status | Mechanism |
| :--- | :--- | :--- |
| **Lawfulness, Fairness, Transparency** | ✅ Implemented | Terms of Service acceptance required on signup. Data sources are public only. |
| **Purpose Limitation** | ✅ Implemented | Data is used only for the specific job result provided to the user. |
| **Data Minimization** | ✅ Implemented | Only requested data points are returned. No mass data harvesting. |
| **Accuracy** | ⚠️ Partial | OSINT data is sourced from 3rd parties and cannot be guaranteed accurate. Disclaimer included in API response. |
| **Storage Limitation** | ✅ Implemented | **TTL Policy** (see Data Model) deletes results after 7 days. |
| **Integrity and Confidentiality** | ✅ Implemented | TLS 1.3 for transit. Database encryption at rest (TDE). |
| **Right to be Forgotten (Art. 17)** | ✅ Implemented | `DELETE /v1/account` purges all user data and associated jobs immediately. |

### CCPA (California Consumer Privacy Act)

| Requirement | Implementation Status | Mechanism |
| :--- | :--- | :--- |
| **Right to Know** | ✅ Implemented | `GET /v1/account` and `GET /v1/jobs` provide a full export of user data and history. |
| **Right to Delete** | ✅ Implemented | `DELETE /v1/account` triggers immediate cascade delete of all records. |
| **Right to Non-Discrimination** | ✅ Implemented | Service tiers are based on volume/limits, not on data usage rights. |

## 5. Incident Response Plan

In the event of a security breach (e.g., database leak):n
1.  **Containment:** Immediate revocation of all API Keys. `api_keys` table is truncated.
2.  **Eradication:** Patch vulnerability identified in the root cause analysis.
3.  **Notification:** Affected users are notified via email within 72 hours of discovery.
4.  **Recovery:** Restore database from the last known clean backup.