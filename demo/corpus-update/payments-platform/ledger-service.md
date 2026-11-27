---
title: Ledger Service
owner: team:payments-platform
updated: 2026-11-15
type: architecture
links: [event-driven-payments.md, payment-events.md]
---
# Ledger Service

The Ledger Service is a double-entry ledger. Every payment event that moves money creates balanced ledger
entries: a debit and a credit on ledger accounts.

## Ledger accounts

Customer funds, provider receivables, merchant payables and fees are separate ledger accounts.

## Reconciliation

The Ledger Service reconciles ledger entries with provider settlement files every hour instead of the nightly
reconciliation job. Mismatches create reconciliation tasks owned by the Payments Platform Team.
