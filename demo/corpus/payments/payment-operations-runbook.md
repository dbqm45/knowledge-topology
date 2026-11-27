---
title: Payment Operations Runbook
owner: team:payments-ops
updated: 2025-09-15
type: runbook
links: [payment-service-architecture.md]
---
# Payment Operations Runbook

## Stuck payments

If payments stay in the authorized state for more than 2 hours, check the Payment Worker queue depth and
the provider status page.

## Retries

The payment retry scheduler retries failed card payments 5 times before the payment is marked failed. Operators can
trigger a manual retry from the admin console when the provider confirms the incident is resolved.

## Provider outage

During a provider outage switch the traffic to the secondary payment provider using the routing flag.
Inform the Payments Team and open a SEV2 incident.
