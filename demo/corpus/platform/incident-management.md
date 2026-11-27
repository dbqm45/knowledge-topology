---
title: Incident Management
owner: team:platform
updated: 2026-09-18
type: procedure
links: [monitoring-and-alerting.md, deployment-pipeline.md]
---
# Incident Management

## Severity levels

| Severity | Definition | Response |
| SEV1 | customer-facing outage | page incident commander immediately |
| SEV2 | degraded service | page on-call, update status page |
| SEV3 | minor impact | ticket, next business day |

## Roles

The incident commander coordinates, the communications lead updates the status page and stakeholders,
and the on-call engineers investigate and mitigate.

## Postmortems

Every SEV1 and SEV2 incident requires a blameless postmortem within 5 business days. Action items are
tracked in the incident tracker and reviewed weekly by the Platform Team.
