---
title: Payment Retry Policy
owner: team:payments
updated: 2026-04-02
type: policy
links: [payment-service-architecture.md]
---
# Payment Retry Policy

## Which payments are retried

Only failed card payments with a transient provider error (timeout, provider unavailable, rate limited) are
retried. Hard declines such as insufficient funds or stolen card are never retried.

## Retry schedule

Failed card payments are retried up to 3 times by the payment retry scheduler. The backoff between attempts
is 1 minute, 10 minutes and 60 minutes. After the last attempt the payment is marked failed and the
customer is notified.

## Idempotency

Every retry reuses the original idempotency key so that the payment provider never charges the customer
twice.
