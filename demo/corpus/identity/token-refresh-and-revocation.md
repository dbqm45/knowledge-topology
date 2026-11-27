---
title: Token Refresh and Revocation
owner: team:identity
updated: 2026-09-28
type: reference
links: [oauth2-authorization-flow.md, jwt-token-validation.md]
---
# Token Refresh and Revocation

## Refresh

Clients exchange a refresh token for a new access token at the token endpoint. Refresh tokens are rotated:
each refresh token can be used once, and reuse of an old refresh token revokes the whole token family.
Refresh tokens are valid for 30 days.

## Revocation

Users can revoke sessions from the account page. Administrators can revoke all OAuth2 tokens of a service
client. Revoked refresh tokens are rejected immediately; access tokens expire within 15 minutes because the
API Gateway validates JWT tokens without calling the Token Service.

## Audit

Every token issuance, refresh and revocation is written to the identity audit log with the client id,
the user id and the granted scopes.
