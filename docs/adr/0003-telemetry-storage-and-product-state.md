# ADR-0003: Separate telemetry storage from product state

Status: Accepted

## Context

Metrics, logs, and traces require specialized storage and query behavior. Rook needs durable incident state and evidence provenance, not a second copy of every raw signal. Reusing the Demo's telemetry integrations keeps the first implementation small.

The stores and integrations described here are planned, not asserted to be deployed.

## Decision

Prometheus will store metrics, Jaeger will store traces, and OpenSearch will store logs. The OpenTelemetry Collector will route real signals to these backends. Grafana will support detailed exploration.

PostgreSQL will store incidents, incident transitions, evidence references, observed changes, rule configuration, and worker checkpoints. It must not duplicate raw metrics, logs, or traces. References will retain backend identity, relevant service and time range, and query or trace/event identifiers as appropriate.

The first implementation slice will query Prometheus only. Logs and traces will be introduced later as evidence enrichment. The worker will normalize evidence metadata and observations; it will not replace the telemetry backends. The API will serve product state and bounded metric queries.

Bound retention and query sizes. Preserve the distinction between source time and ingestion time. When referenced telemetry expires or was not collected, report unavailable or incomplete evidence rather than fabricating it.

## Consequences

- Each signal retains a dedicated query/store boundary, while PostgreSQL stays focused on product state.
- Backend retention can outlive or be shorter than incident retention; an incident reference may become unavailable.
- Investigation will depend on backend availability, but persisted incidents will remain accessible while PostgreSQL is available.
- Adapters must handle query errors, identity mapping, and partial evidence explicitly.
- No raw telemetry duplication means this design does not promise permanent forensic replay of every incident.

## Alternatives considered

- Store raw telemetry in PostgreSQL: duplicates specialized infrastructure and expands ingestion/storage responsibilities.
- Copy all incident-related raw signals into PostgreSQL: violates the chosen storage boundary and adds retention complexity.
- Introduce another logs/traces stack immediately: increases configuration work without a demonstrated advantage over the Demo integrations.
- Keep incidents only in telemetry tools: does not provide Rook-owned durable lifecycle state and checkpoints.
