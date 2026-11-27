---
title: SSO Configuration (SAML and OIDC)
owner: team:identity
updated: 2026-08-30
type: howto
links: [overview.md, oauth2-authorization-flow.md]
---
# SSO Configuration (SAML and OIDC)

Enterprise customers federate their users through single sign-on. The Identity Provider supports SAML 2.0
and OIDC federation.

## Onboarding a new SSO connection

1. Collect the customer IdP metadata (SAML metadata XML or OIDC discovery URL).
2. Create the federation connection in the Identity Provider admin console.
3. Map the customer groups to roles and OAuth2 scopes.
4. Test the login with a customer test account and enable MFA enforcement if required.

## Attribute mapping

The email claim is the stable user identifier. Group claims map to roles. Just-in-time provisioning creates
the user on first SSO login.

## Troubleshooting

Clock skew larger than 2 minutes breaks SAML assertions. Certificate expiry of the customer IdP is monitored
and alerts the Identity Team 30 days before expiry.
