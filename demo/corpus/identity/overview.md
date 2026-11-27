---
title: Identity Platform Overview
owner: team:identity
updated: 2026-10-20
type: architecture
links: [oauth2-authorization-flow.md, jwt-token-validation.md, sso-configuration.md, gateway-authentication.md]
---
# Identity Platform Overview

The Identity Platform provides authentication and authorization for every customer-facing and internal API.
It is owned by the Identity Team and consists of the Identity Provider, the Token Service and the
authentication filters running in the API Gateway.

## Responsibilities

- Issue OAuth2 access tokens and refresh tokens for users and service clients.
- Sign JWT access tokens with rotating RS256 keys published on the JWKS endpoint.
- Federate enterprise users through SAML and OIDC single sign-on (SSO).
- Enforce scopes and audiences at the API Gateway before requests reach downstream services.

## Key components

| Component | Responsibility | Owner |
| Identity Provider | user login, MFA, SSO federation | Identity Team |
| Token Service | OAuth2 token issuance, refresh, revocation | Identity Team |
| API Gateway auth filter | JWT validation, scope checks | Identity Team |

## Related documents

The OAuth2 authorization flow, JWT token validation, SSO configuration and API Gateway authentication
pages describe each part in detail.
