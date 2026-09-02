# Rook Project Charter

## Product

Rook is a cloud-native incident intelligence and reliability platform that monitors distributed applications using live operational telemetry.

## Problem

Engineers often investigate incidents using separate tools for metrics, logs, traces, deployments, and Kubernetes events. This makes it difficult to quickly determine:

- Which service is unhealthy?
- When did the problem begin?
- What changed immediately before the failure?
- How are users being affected?
- Should the latest deployment be rolled back?

Rook brings this information together in one operational control room.

## Target Users

- Site Reliability Engineers
- Platform Engineers
- DevOps Engineers
- Software Engineers operating distributed applications

## MVP Capabilities

Rook will:

1. Monitor a real running distributed application.
2. Collect live service and infrastructure telemetry.
3. Display service health, traffic, latency, and error rates.
4. create incidents when reliability thresholds are violated.
5. Correlate incidents with recent deployments and Kubernetes events.
6. Display an incident timeline and supporting evidence.
7. Provide an optional AI-generated incident explanation.
8. Demonstrate canary deployment and safe rollback.

## Monitored Workload

The OpenTelemetry Demo application will serve as the external distributed workload monitored by Rook.

Rook will be developed independently and will not claim ownership of the monitored demo application.

## Real-Data Policy

Rook will not use invented CSV datasets, randomly generated dashboard values, or hard-coded failure records.

Operational data must come from:

- Real HTTP requests
- OpenTelemetry instrumentation
- Prometheus metrics
- Application logs and traces
- Kubernetes resource events
- Deployment events
- Real container CPU and memory consumption

Automated load generation and intentionally triggered failures are permitted because their resulting system behavior and telemetry are real.

## Initial Non-Goals

The first release will not attempt to:

- Replace enterprise platforms such as Datadog or Splunk
- Support every cloud provider
- Provide enterprise billing or multi-tenancy
- Automatically modify arbitrary production clusters
- Build an unrelated business application from scratch

## Success Criteria

The completed demonstration must show Rook:

1. Monitoring a healthy distributed application.
2. Detecting a genuine failure or bad deployment.
3. Identifying the affected service.
4. Correlating the failure with a recent system change.
5. Showing supporting metrics, logs, or traces.
6. Rolling back the faulty release.
7. Confirming that system health recovered.
8. Recording the incident timeline and resolution.