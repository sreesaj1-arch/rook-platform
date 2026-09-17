# ADR-0004: Local-first deployment and temporary GKE

Status: Accepted

## Context

Rook must develop at near-zero cloud cost while retaining a credible Kubernetes deployment path. Early cloud infrastructure and automated remediation would add expense and operational risk before the incident workflow is validated.

This ADR accepts a future deployment sequence; it does not claim any environment has been provisioned.

## Decision

Progress through Docker Compose, local kind Kubernetes, Helm packaging, Argo CD reconciliation, and finally temporary Terraform-provisioned GKE. Helm work may overlap local Kubernetes validation. Reuse images and configuration structure across environments.

Introduce GitHub Actions for relevant tests and image builds when implementation warrants it. Use Argo CD as the workload reconciler after repeatable Helm deployment works. Keep initial access local or port-forwarded and use bounded persistent storage suitable for a demonstration.

The initial rollback will be operator-led through a Git desired-state change. Once Argo CD is present, it will reconcile that change. Rook will observe rollout outcomes and require actual telemetry recovery before resolving incidents.

Automated rollback using Prometheus analysis and Argo Rollouts is a later enhancement, not a V1 prerequisite. Agree on cloud project, region, budget, lifetime, retention/export needs, and teardown responsibility before provisioning temporary GKE.

## Consequences

- Most development and failure testing will avoid recurring cloud cost.
- Local CPU, memory, and disk needs must still be measured; the Demo is a real distributed workload.
- Local/cloud differences require environment-specific values and validation.
- Single-instance demonstration storage will not provide production high availability.
- Git desired state will preserve rollback intent under reconciliation, and Rook will not require mutation privileges for its observer role.
- Temporary deployment requires explicit teardown of chargeable resources, including retained disks.

## Alternatives considered

- Develop directly on an always-on GKE cluster: incurs cost before cloud infrastructure is necessary.
- Stop at Docker Compose: cannot validate Kubernetes events, rollouts, Helm, or GitOps behavior.
- Add Argo CD before repeatable deployments work: introduces reconciliation complexity too early.
- Use imperative rollback without updating Git: risks reconciliation restoring the faulty desired state.
- Add automated rollback and Argo Rollouts immediately: expands scope before detection and recovery rules have been validated.
