---
title: Kubernetes Clusters
owner: team:platform
updated: 2026-10-11
type: architecture
links: [deployment-pipeline.md, monitoring-and-alerting.md]
---
# Kubernetes Clusters

Production workloads run on three Kubernetes clusters: prod-eu, prod-us and staging. Each cluster spans three
availability zones.

## Node pools

| Pool | Purpose | Autoscaling |
| system | ingress, monitoring agents | fixed 3 nodes |
| general | stateless services | 6 to 40 nodes |
| batch | jobs and data pipelines | 0 to 20 nodes |

## Namespaces and access

Each team owns a namespace. Access is granted through SSO groups mapped to Kubernetes RBAC roles. Production
write access requires an approved change in the deployment pipeline.

## Upgrades

Clusters are upgraded every quarter, staging first, then prod-eu and prod-us one week later.
