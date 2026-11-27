---
title: Payment Events Catalogue
owner: team:payments-platform
updated: 2026-11-18
type: reference
links: [event-driven-payments.md]
---
# Payment Events Catalogue

| Event | Producer | Consumers |
| PaymentRequested | Checkout | Payment Orchestrator |
| PaymentAuthorized | Payment Orchestrator | Ledger Service, Notifications |
| PaymentFailed | Payment Orchestrator | Retry Orchestrator, Notifications |
| PaymentRetryScheduled | Retry Orchestrator | Payment Orchestrator |
| PaymentCaptured | Payment Orchestrator | Ledger Service |

## Event schema

Every payment event carries the payment id, the idempotency key, the amount, the currency and the event
version. Payment events are partitioned by payment id so that events of one payment are processed in order.
