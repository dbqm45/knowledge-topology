---
title: Refunds
owner: team:payments
updated: 2026-05-20
type: procedure
links: [payment-service-architecture.md, payment-api-reference.md]
---
# Refunds

Refunds can be full or partial. A refund is only possible for captured payments and must be issued within
180 days of the capture.

## Process

1. Customer support creates the refund in the admin console.
2. The Payment Service writes the refund request to the Payment Ledger.
3. The Payment Worker sends the refund to the payment provider.
4. The refund state becomes refunded when the provider confirms it.

Refunds above 1000 EUR require approval from a second support agent.
