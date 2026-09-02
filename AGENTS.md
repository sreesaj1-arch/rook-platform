# Rook Engineering Guide

## Project Purpose

Rook is a cloud-native incident intelligence and reliability platform. It monitors distributed applications using live telemetry and helps engineers detect, investigate, and resolve operational incidents.

## Core Product Rule

Rook must use telemetry produced by real running software.

Do not create:

- Invented monitoring datasets
- Random dashboard metrics
- Hard-coded incident records
- Fake health-status values

Generated HTTP load and intentionally triggered failures are allowed because the resulting latency, errors, resource consumption, logs, metrics, and traces are real.

## Repository Structure

- `apps/api` — FastAPI control-plane API
- `apps/frontend` — React and TypeScript dashboard
- `services/telemetry-ingestor` — telemetry ingestion and normalization
- `services/incident-engine` — detection and incident correlation
- `packages/contracts` — shared schemas and event contracts
- `docs` — architecture, decisions, and runbooks
- `infra/terraform` — Google Cloud infrastructure
- `deploy/helm` — Kubernetes deployment packages
- `observability` — Prometheus and Grafana configuration
- `tests` — integration and end-to-end tests
- `scripts` — development and operational scripts

## Engineering Standards

- Use Python type hints.
- Use TypeScript rather than plain JavaScript.
- Keep services independently testable.
- Add tests for meaningful behavior.
- Never commit secrets or credentials.
- Keep infrastructure reproducible.
- Document important architectural decisions.
- Prefer simple implementations until additional complexity is justified.

## Git Workflow

- Keep `main` stable.
- Build changes on focused feature branches.
- Use pull requests to merge meaningful changes.
- Use clear commit messages.
- Do not commit generated dependencies or secrets.

## Definition of Done

A change is complete only when:

1. The implementation works.
2. Relevant tests pass.
3. Configuration and secrets are handled safely.
4. Documentation is updated when behavior changes.
5. The change can be explained clearly.