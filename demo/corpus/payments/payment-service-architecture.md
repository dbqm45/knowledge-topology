---
title: Payment Service Architecture
owner: team:payments
updated: 2026-06-10
type: architecture
links: [payment-retry-policy.md, payment-api-reference.md, refunds.md]
---
# Payment Service Architecture

The Payment Service processes card payments, bank transfers and wallet payments for checkout. It receives
payment requests from the Checkout Service through the API Gateway and calls external payment providers.

## Components

- Payment API: synchronous endpoint used by checkout to create and confirm payments.
- Payment Worker: asynchronous processing of provider callbacks and retries.
- Payment Ledger: append-only record of payment state transitions.

## Payment states

A payment moves through created, authorized, captured, failed and refunded states. State transitions are
written to the Payment Ledger before the provider is called.

## Retries

Failed card payments are retried up to 3 times by the payment retry scheduler with exponential backoff.
See the Payment Retry Policy for details.
