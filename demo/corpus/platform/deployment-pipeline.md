---
title: Deployment Pipeline
owner: team:platform
updated: 2026-11-12
type: procedure
links: [kubernetes-clusters.md, incident-management.md]
---
# Deployment Pipeline

All services are deployed through the GitOps deployment pipeline.

## Stages

1. Build: the CI pipeline builds the container image, runs unit tests and signs the image.
2. Staging: the pipeline updates the staging manifests; smoke tests run automatically.
3. Canary: production receives the new version on 5 percent of pods for 30 minutes.
4. Rollout: if error rate and latency stay within the SLO, the rollout continues to all pods.

## Rollback

Rollback reverts the manifest commit. The previous image is redeployed within 5 minutes. Every rollback
creates an incident ticket for follow-up.

## Change freeze

Production deployments are frozen during the end-of-year change freeze, except for approved emergency fixes.
