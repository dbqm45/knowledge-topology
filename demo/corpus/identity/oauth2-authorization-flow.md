---
title: OAuth2 Authorization Flow
owner: team:identity
updated: 2026-09-14
type: architecture
links: [overview.md, jwt-token-validation.md, token-refresh-and-revocation.md]
---
# OAuth2 Authorization Flow

The Token Service implements the OAuth2 authorization code flow with PKCE for browser and mobile clients,
and the client credentials flow for service-to-service calls.

## Authorization code flow with PKCE

1. The client redirects the user to the Identity Provider authorize endpoint with a PKCE code challenge.
2. The user authenticates (password plus MFA, or SSO federation).
3. The Identity Provider returns an authorization code to the registered redirect URI.
4. The client exchanges the code and the PKCE verifier for an access token and a refresh token.

## Client credentials flow

Service clients authenticate with a client id and a private key JWT assertion. The Token Service issues an
access token with the scopes granted to that service client. Client secrets are not allowed for new clients.

## Token lifetimes

Access tokens are valid for 15 minutes. Refresh tokens are valid for 30 days and are rotated on every use.
The OAuth2 scopes and audiences are validated by the API Gateway authentication filter.
