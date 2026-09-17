# ADR-0001: Modular backend with API and worker processes

Status: Accepted

## Context

Rook needs a responsive product API and continuous telemetry evaluation. The repository separates ingestion and incident concerns, but separate folders do not justify independently operated microservices. Initial load and scale requirements do not justify distributed messaging or task infrastructure.

This ADR accepts a planned architecture; it does not claim the backend is implemented.

## Decision

Implement a modular Python backend with one FastAPI process and one background-worker process. Both will use shared Python modules and may initially use the same container image with different entry points.

The API will serve product data and bounded chart queries. The worker will own periodic detection, evidence ingestion, observed changes, and incident transitions. Ingestion and incident modules will remain independently testable without requiring an internal HTTP boundary.

Use PostgreSQL for durable product state and worker checkpoints. Begin with one worker, guarded against overlap by database ownership locking and transactional uniqueness. Optional AI analysis will be disabled by default, may summarize evidence, and cannot determine incident state.

Exclude Kafka, Redis, and Celery from Rook V1 unless measured requirements later justify a new decision. Do not add a separate AI microservice.

## Consequences

- API traffic and continuous work have separate process lifecycles without extra service protocols.
- Shared modules and an initial shared image reduce packaging and operational work.
- Database availability limits durable processing; restart and deduplication behavior require meaningful tests.
- Worker scale is deliberately limited; concurrent workers or queues require a revised ownership and delivery design.
- AI failure cannot block the deterministic incident lifecycle.

## Alternatives considered

- Run detection inside API request handlers or API worker lifecycles: fewer entry points, but risks blocked requests and duplicated evaluators.
- Deploy ingestion and incident processing as independent microservices: adds network contracts and operations without demonstrated need.
- Use Celery with Redis or Kafka-based processing: potentially useful for future measured scheduling or throughput needs, but unnecessary for the initial workload.
