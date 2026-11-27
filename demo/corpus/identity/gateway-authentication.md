---
title: API Gateway Authentication
owner: team:identity
updated: 2026-11-05
type: architecture
links: [jwt-token-validation.md, overview.md]
---
# API Gateway Authentication

The API Gateway terminates TLS and runs the authentication filter for every route.

## Request pipeline

1. The authentication filter extracts the bearer JWT access token.
2. The token is validated as described in JWT Token Validation (signature, issuer, audience, expiry).
3. Route policies declare the required OAuth2 scopes; missing scopes are rejected with AUTH-403-SCOPE.
4. The gateway forwards the verified identity context to downstream services in signed headers.

## Service-to-service calls

Internal services call each other through the API Gateway using client credentials access tokens. Direct
calls that bypass the gateway are blocked by network policy.

## Rate limiting

Authenticated clients are rate limited per client id. Anonymous routes are limited per IP address.
