# ADR-0002: Real telemetry from a pinned OpenTelemetry Demo

Status: Accepted

## Context

Rook's value depends on evidence from actual running software. The project charter rejects fabricated datasets, dashboard measurements, and failure records. A representative external workload avoids building an unrelated application merely to monitor it.

This decision defines planned integration, not an existing telemetry pipeline.

## Decision

Use a pinned OpenTelemetry Demo release as the monitored workload and the Demo's current load generator as supplied by that release. Select and record the exact release during implementation. Rook will be developed independently and will not claim ownership of the Demo.

Generated HTTP traffic and intentionally triggered failures are allowed. Their resulting metrics, logs, traces, resource usage, and events must come from actual execution. Rook must never invent telemetry, incidents, or healthy values.

Start with metrics-only detection. Add logs and traces as evidence enrichment, followed by Kubernetes events and deployment observations as local Kubernetes support develops. Missing observations must be unknown, stale, or insufficient evidence; empty data is not evidence of health.

Deployment correlation will express temporal evidence, not proof of causation. Optional AI may summarize available evidence but cannot establish incident state or causal certainty.

## Consequences

- Demonstrations will be repeatable while exercising genuine system behavior.
- Pinning allows queries, labels, and failure exercises to be validated against a known workload.
- Upgrades require checking instruments, identities, dependencies, and load-generator behavior.
- Missing signals and collection failures must be visible in the product.
- Workload dependencies remain distinct from Rook dependencies; a Demo component does not justify a matching Rook service.

## Alternatives considered

- Invented CSV datasets or hard-coded incidents: violate the core product rule.
- Build a custom business application: expands scope without improving Rook's core architecture.
- Track the Demo's moving latest release: reduces reproducibility and can silently change telemetry contracts.
- Treat deployment proximity or an AI hypothesis as causation: overstates the evidence.
