---
title: Monitoring and Alerting
owner: team:platform
updated: 2026-10-25
type: reference
links: [incident-management.md, kubernetes-clusters.md]
---
# Monitoring and Alerting

Metrics are collected with Prometheus, logs are shipped to the central log platform and traces use
OpenTelemetry.

## SLO-based alerting

Each service defines availability and latency SLOs. Alerts fire on error budget burn rate, not on single
metric thresholds. A fast burn alert pages the on-call engineer; a slow burn alert creates a ticket.

## Dashboards

Every service has a standard dashboard with request rate, error rate, latency percentiles and saturation.

## On-call

Alerts route to the owning team on-call rotation. Escalation follows the incident management procedure.
