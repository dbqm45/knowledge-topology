---
title: Event-Driven Payments Platform
owner: team:payments-platform
updated: 2026-11-20
type: architecture
links: [payment-events.md, ledger-service.md, retry-orchestrator.md]
---
# Event-Driven Payments Platform

The new payments platform replaces the synchronous Payment Service calls with payment events on the event
bus. Checkout publishes a PaymentRequested event; the Payment Orchestrator consumes it and drives the payment
through the provider adapters.

## Components

- Payment Orchestrator: state machine that consumes payment events and calls provider adapters.
- Ledger Service: double-entry ledger that replaces the Payment Ledger.
- Retry Orchestrator: schedules retries of failed card payments as delayed payment events.

## Migration

Traffic moves from the Payment Service to the Payment Orchestrator country by country. During the migration
both platforms write to the Ledger Service.
