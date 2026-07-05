# Monitoring & Observability Plan

## Overview
This document outlines the strategy for monitoring system health, performance, and reliability. It ensures that operators have visibility into the asynchronous job lifecycle and can react to failures before they impact users.

## 1. Key Metrics

The following metrics must be exposed by the API Gateway, Worker Nodes, and Database, and scraped by Prometheus.

### System Health Metrics
| Metric Name | Type | Description |
| :--- | :--- | :--- |
| `up` | Gauge | Is the service scraping target (1 for up, 0 for down)? |
| `process_cpu_seconds_total` | Counter | Total CPU time consumed. |
| `process_resident_memory_bytes` | Gauge | Memory usage in bytes. |

### Application Specific Metrics
| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `job_queue_depth` | Gauge | `queue="high"|"low"` | Number of jobs currently waiting in Redis. |
| `job_duration_seconds` | Histogram | `status="completed"|"failed"`, `tool_name` | Time taken from submission to completion. |
| `active_profiles_count` | Gauge | `tier` | Number of profiles currently in 'active' or 'processing' state. |
| `profile_resolution_depth` | Histogram | `tier` | Depth of the identity graph achieved per profile. |
| `orchestrator_chain_triggered_total` | Counter | `reason="email"|"domain"|"phone"` | Number of times the Orchestrator spawned a child job. |
| `knowledge_graph_entities_total` | Gauge | `type` | Total count of unique entities (nodes) in the persistent graph. |
| `knowledge_graph_relationships_total` | Gauge | `type` | Total count of links (edges) in the persistent graph. |
| `graph_query_duration_seconds` | Histogram | - | Latency for querying the persistent knowledge graph. |
| `job_completion_time_p95` | Gauge | - | 95th percentile of job duration (derived from histogram). |
| `active_worker_count` | Gauge | - | Number of worker processes currently polling/active. |
| `api_request_duration_seconds` | Histogram | `method`, `path`, `status` | HTTP request latency for Gateway endpoints. |
| `db_query_duration_seconds` | Histogram | `operation="select"|"insert"|"update"` | Database query latency. |
| `osint_tool_executions_total` | Counter | `tool_name`, `status` | Total count of tool invocations. |

## 2. Alert Thresholds

Alerts are defined in Prometheus (Alertmanager) to notify the operations team via Slack/PagerDuty when thresholds are breached.

### Critical Alerts (PagerDuty)

| Alert Name | Condition | Severity | Description |
| :--- | :--- | :--- | :--- |
| **HighFailureRate** | `rate(osint_tool_executions_total{status="failed"}[5m]) > 0.05` | Critical | >5% of jobs are failing. Immediate investigation required. |
| **ServiceDown** | `up{job="api-gateway"} == 0` | Critical | The API Gateway is unreachable. |
| **DatabaseDown** | `up{job="postgres"} == 0` | Critical | The persistence layer is down. System is read-only or failing. |

### Warning Alerts (Slack)

| Alert Name | Condition | Severity | Description |
| :--- | :--- | :--- | :--- |
| **QueueBacklog** | `job_queue_depth > 100` | Warning | Jobs are accumulating faster than workers can process. Consider scaling workers. |
| **HighLatency** | `histogram_quantile(0.95, rate(job_duration_seconds_bucket[5m])) > 300` | Warning | 95% of jobs are taking longer than 5 minutes. Users are experiencing delays. |
| **WorkerStarvation** | `active_worker_count < 2` | Warning | Less than 2 workers are active. Check for crashes. |

## 3. Logging Strategy

### Log Format
All logs must be emitted in **JSON** format to facilitate parsing by centralized log aggregators (e.g., ELK Stack, Loki).

### Required Fields
Every log entry must contain the following top-level fields:

| Field | Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `timestamp` | String (ISO8601) | `"2023-10-27T10:00:00Z"` | Time of the event. |
| `level` | String | `"info"`, `"error"`, `"warn"` | Log severity. |
| `service` | String | `"api-gateway"`, `"worker-1"` | Name of the generating service. |
| `correlation_id` | String (UUID) | `"550e8400-e29b-41d4-a716-446655440000"` | Traces a request from Gateway -> Queue -> Worker -> DB. |
| `user_id` | String (UUID) | - | ID of the authenticated user (omit if system task). |
| `message` | String | `"Job queued successfully"` | Human-readable message. |
| `error` | Object (Optional) | `{"code": 500, "stack_trace": "..."}` | Detailed error info if level is error. |

### Structured Logging Examples

**API Gateway (Job Received)**
```json
{
  "timestamp": "2023-10-27T10:00:00Z",
  "level": "info",
  "service": "api-gateway",
  "correlation_id": "req-123",
  "user_id": "user-abc",
  "message": "Job queued successfully",
  "job_id": "job-xyz",
  "target_type": "username"
}
```

**Worker Node (Tool Execution)**
```json
{
  "timestamp": "2023-10-27T10:00:05Z",
  "level": "info",
  "service": "worker-1",
  "correlation_id": "req-123",
  "user_id": "user-abc",
  "message": "Tool execution completed",
  "job_id": "job-xyz",
  "tool_name": "sherlock",
  "duration_ms": 4200
}
```

## 4. Dashboards

A **Grafana** dashboard should be configured with the following panels:
1.  **Request Rate:** `rate(http_requests_total[1m])`
2.  **Job Queue Depth:** Gauge of `job_queue_depth`
3.  **Job Latency (P95):** Graph of `job_completion_time_p95`
4.  **Error Rate:** `rate(http_requests_total{status=~"5.."}[1m])`
5.  **Active Workers:** Gauge of `active_worker_count`