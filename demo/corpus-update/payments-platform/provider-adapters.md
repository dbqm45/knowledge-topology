---
title: Payment Provider Adapters
owner: team:payments-platform
updated: 2026-11-10
type: reference
links: [event-driven-payments.md]
---
# Payment Provider Adapters

Each payment provider is wrapped by a provider adapter with the same interface: authorize, capture, refund
and status. Provider adapters translate provider callbacks into payment events.

## Timeouts

Provider adapters use a 10 seconds timeout and a circuit breaker per provider. When the circuit breaker opens
the Payment Orchestrator routes payment events to the secondary provider.
