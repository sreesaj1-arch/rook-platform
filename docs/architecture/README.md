# Rook V1 architecture

Status: approved design; implementation is planned. These documents do not establish that any runtime component, deployment, or integration has been completed.

Rook will help engineers investigate incidents in a real distributed workload. V1 will use a modular Python backend with one FastAPI process and one background-worker process, a React/TypeScript dashboard, PostgreSQL product state, and dedicated telemetry backends.

## Architecture views

- [System context](system-context.md): users, external systems, and trust boundaries.
- [Container view](container-view.md): runtime responsibilities and repository mapping.
- [Telemetry and incident flow](telemetry-and-incident-flow.md): progressive signals, detection, evidence, and failure handling.
- [Deployment evolution](deployment-evolution.md): Docker Compose through temporary GKE.

## Accepted decisions

- [0001: Modular backend, API and worker](../adr/0001-modular-backend-api-and-worker.md)
- [0002: Real telemetry and Demo workload](../adr/0002-real-telemetry-and-demo-workload.md)
- [0003: Telemetry storage and product state](../adr/0003-telemetry-storage-and-product-state.md)
- [0004: Local-first deployment](../adr/0004-local-first-deployment.md)

## V1 scope and progression

The first implementation slice will query real metrics from Prometheus, detect sustained threshold violations, persist incidents, and display measurements and freshness. Logs in OpenSearch and traces in Jaeger will subsequently enrich incident evidence. Kubernetes events and observed deployment changes will follow during local Kubernetes development.

V1 acceptance requires demonstrating canary deployment and safe operator-led rollback through a Git desired-state change. The demonstration must detect a genuine failure, identify the affected service, associate relevant recent changes, display supporting evidence, observe rollback, and confirm recovery from real telemetry. The canary implementation mechanism remains flexible; automated rollback is a later enhancement, not an acceptance requirement. A metrics-only slice will not by itself satisfy the [Project Charter](../PROJECT_CHARTER.md).

Rook must never invent telemetry, incidents, or healthy values. Missing observations will be unknown, stale, or insufficient evidence. Correlation will indicate temporal evidence, not proof of causation. Optional AI will be disabled by default and may summarize evidence but cannot determine incident state.

Kafka, Redis, and Celery are excluded from Rook V1 unless measured requirements later justify a new decision. Logical ingestion and incident modules will not require independent network services. These accepted decisions define V1 scope.

## Later enhancements

Automated rollback using Prometheus analysis and Argo Rollouts, precise canary traffic management, multi-cluster operation, high availability, and long-term telemetry retention are later enhancements. AI is not a prerequisite for detection, investigation, or recovery.

Cloud budget, project, region, lifetime, and teardown policy must be agreed before provisioning. External AI use requires agreement on provider, cost, and permitted evidence. Public exposure or autonomous remediation requires a separate scope decision.
