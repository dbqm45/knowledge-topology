---
title: Payment API Reference
owner: team:payments
updated: 2026-10-01
type: reference
links: [payment-service-architecture.md]
---
# Payment API Reference

## POST /payments

Creates a payment. Requires the payments:write OAuth2 scope. The request contains the amount, the currency,
the payment method token and an idempotency key.

## POST /payments/{id}/confirm

Confirms an authorized payment and captures the funds.

## GET /payments/{id}

Returns the payment state and the provider reference.

## Errors

| Code | Meaning |
| PAY-402-DECLINED | the provider declined the payment |
| PAY-409-DUPLICATE | idempotency key reused with different payload |
| PAY-503-PROVIDER | provider unavailable, the payment will be retried |

The Payment API timeout towards providers is 30 seconds.
