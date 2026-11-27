"""Process-wide wiring (settings, DB, embedder, vector store, auth)."""

from __future__ import annotations

import hashlib
import hmac

from kt.config import get_settings
from kt.domain.models import Principal


class AuthError(Exception):
    pass


def principal_from_api_key(api_key: str | None) -> Principal:
    settings = get_settings()
    keys = settings.load_api_keys()
    if not api_key:
        raise AuthError("missing API key")
    for key, spec in keys.items():
        if hmac.compare_digest(hashlib.sha256(key.encode()).digest(), hashlib.sha256(api_key.encode()).digest()):
            return Principal(id=spec["principal"], groups=spec.get("groups", []), roles=spec.get("roles", []),
                             tenant_id=spec.get("tenant_id", settings.default_tenant))
    raise AuthError("invalid API key")
