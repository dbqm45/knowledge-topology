---
title: Backup and Disaster Recovery
owner: team:platform
updated: 2026-07-30
type: runbook
links: [kubernetes-clusters.md, incident-management.md]
---
# Backup and Disaster Recovery

## Backups

Databases are backed up continuously with point-in-time recovery for 14 days. Daily snapshots are copied
to a second region and kept for 90 days. Object storage buckets use versioning.

## Recovery objectives

The recovery point objective (RPO) is 15 minutes and the recovery time objective (RTO) is 4 hours for
tier-1 services.

## Restore tests

The Platform Team runs a restore test every month and a full region failover exercise twice a year. Results
are recorded in the disaster recovery log.
