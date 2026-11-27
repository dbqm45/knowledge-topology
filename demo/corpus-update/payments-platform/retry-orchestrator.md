---
title: Retry Orchestrator
owner: team:payments-platform
updated: 2026-11-19
type: architecture
links: [event-driven-payments.md, payment-events.md]
---
# Retry Orchestrator

The Retry Orchestrator consumes PaymentFailed events and decides whether a failed card payment is retried.

## Policy

Failed card payments with a transient provider error are retried up to 4 times by the Retry Orchestrator.
Each retry is published as a PaymentRetryScheduled event with exponential backoff. Hard declines are never
retried.

## Observability

Retry attempts, success after retry and exhausted retries are exported as metrics per provider.
