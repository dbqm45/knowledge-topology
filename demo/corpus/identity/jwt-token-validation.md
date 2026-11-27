---
title: JWT Token Validation
owner: team:identity
updated: 2026-10-02
type: reference
links: [oauth2-authorization-flow.md, gateway-authentication.md]
---
# JWT Token Validation

Every API request carries a JWT access token issued by the Token Service. Validation happens in the
API Gateway authentication filter and, for defence in depth, in the service authentication library.

## Validation steps

1. Verify the RS256 signature against the signing keys published on the JWKS endpoint.
2. Check the issuer, the audience and the expiry claims. Access tokens are valid for 15 minutes.
3. Reject tokens whose key id is not present in the cached JWKS (refresh the cache at most once per minute).
4. Map OAuth2 scopes to permissions and attach the identity context to the request.

## Key rotation

Signing keys rotate every 90 days. The previous key stays published on the JWKS endpoint for 7 days so that
tokens signed before the rotation remain valid until they expire.

## Error handling

Invalid or expired tokens return HTTP 401 with error code AUTH-401-INVALID-TOKEN. Missing scopes return
HTTP 403 with error code AUTH-403-SCOPE.
