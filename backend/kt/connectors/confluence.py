"""Confluence Cloud connector (REST API v2 + v1 for CQL search and restrictions).

Config::

    {
      "base_url": "https://your-site.atlassian.net",
      "email": "bot@company.com",
      "api_token_env": "CONFLUENCE_API_TOKEN",       # or "api_token": "..."
      "spaces": ["ENG", "PAY"],
      "space_principals": {"ENG": ["group:engineering"]},   # who can read the space (default ["*"])
      "reconcile_hours": 24
    }

ACL model: effective readers = space principals, narrowed by read restrictions of the page and of
every restricted ancestor (intersection — conservative: an empty intersection hides the page).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import httpx

from kt.connectors.base import KnowledgeConnector, register_connector
from kt.domain.models import ChangeBatch, ChangeEvent, NormalizedDocument
from kt.ingestion.parsing import parse_storage_html


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@register_connector
class ConfluenceConnector(KnowledgeConnector):
    type = "confluence"

    def __init__(self, config: dict[str, Any], transport: httpx.BaseTransport | None = None):
        super().__init__(config)
        token = config.get("api_token") or os.environ.get(config.get("api_token_env", "CONFLUENCE_API_TOKEN"), "")
        self.base = config["base_url"].rstrip("/")
        self.client = httpx.Client(
            base_url=self.base,
            auth=(config.get("email", ""), token) if config.get("email") else None,
            headers={"Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )
        self._space_ids: dict[str, str] = {}
        self._space_keys_by_id: dict[str, str] = {}
        self._restriction_cache: dict[str, set[str] | None] = {}

    # -- HTTP -----------------------------------------------------------------
    def _get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(5):
            resp = self.client.get(url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("Retry-After", 2**attempt))
                time.sleep(min(delay, 30))
                continue
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def _paginate(self, url: str, params: dict | None = None) -> Iterator[dict]:
        """Cursor pagination: follow ``_links.next`` until absent."""
        next_url: str | None = url
        while next_url:
            data = self._get(next_url, params)
            params = None  # the next link already carries the cursor and the original query
            yield from data.get("results", [])
            nxt = (data.get("_links") or {}).get("next")
            next_url = nxt if nxt else None

    # -- Spaces ---------------------------------------------------------------
    def _resolve_spaces(self) -> dict[str, str]:
        if not self._space_ids:
            keys = self.config.get("spaces", [])
            for space in self._paginate("/wiki/api/v2/spaces", {"keys": ",".join(keys), "limit": 250}):
                self._space_ids[space["key"]] = str(space["id"])
                self._space_keys_by_id[str(space["id"])] = space["key"]
        return self._space_ids

    def validate(self) -> None:
        missing = set(self.config.get("spaces", [])) - set(self._resolve_spaces())
        if missing:
            raise ValueError(f"Spaces not found or not accessible: {sorted(missing)}")

    # -- Changes --------------------------------------------------------------
    def _all_page_ids(self) -> dict[str, str]:
        ids: dict[str, str] = {}
        for _, space_id in self._resolve_spaces().items():
            for page in self._paginate(f"/wiki/api/v2/spaces/{space_id}/pages", {"limit": 250, "status": "current"}):
                ids[str(page["id"])] = str((page.get("version") or {}).get("number", ""))
        return ids

    def list_changes(self, cursor: dict[str, Any] | None) -> ChangeBatch:
        now = datetime.now(timezone.utc)
        cursor = cursor or {}
        last_full = _parse_dt(cursor.get("last_full_at"))
        reconcile = timedelta(hours=float(self.config.get("reconcile_hours", 24)))
        if not cursor or last_full is None or now - last_full > reconcile:
            current = self._all_page_ids()
            known: dict[str, str] = cursor.get("versions", {})
            events = [ChangeEvent(type="upsert", external_id=pid, source_version=v)
                      for pid, v in current.items() if known.get(pid) != v]
            events += [ChangeEvent(type="delete", external_id=pid) for pid in known if pid not in current]
            return ChangeBatch(
                events=events,
                next_cursor={"versions": current, "last_full_at": now.isoformat(), "since": now.isoformat()},
                complete=True,
            )
        # Incremental: CQL lastmodified since the previous run (minus a safety margin).
        since = (_parse_dt(cursor.get("since")) or now) - timedelta(minutes=5)
        spaces = ",".join(f'"{k}"' for k in self.config.get("spaces", []))
        cql = f'type=page and space in ({spaces}) and lastmodified >= "{since.strftime("%Y-%m-%d %H:%M")}"'
        versions = dict(cursor.get("versions", {}))
        events = []
        for hit in self._paginate("/wiki/rest/api/search", {"cql": cql, "limit": 100}):
            content = hit.get("content") or {}
            pid = str(content.get("id", ""))
            if pid:
                events.append(ChangeEvent(type="upsert", external_id=pid))
        return ChangeBatch(
            events=events,
            next_cursor={**cursor, "versions": versions, "since": now.isoformat()},
            complete=False,
        )

    # -- Permissions ----------------------------------------------------------
    def _read_restriction(self, content_id: str) -> set[str] | None:
        """Principals allowed by the read restriction of one content node, or None if unrestricted."""
        if content_id in self._restriction_cache:
            return self._restriction_cache[content_id]
        data = self._get(f"/wiki/rest/api/content/{content_id}/restriction/byOperation/read")
        restrictions = data.get("restrictions") or {}
        users = [u.get("accountId") for u in (restrictions.get("user") or {}).get("results", [])]
        groups = [g.get("name") for g in (restrictions.get("group") or {}).get("results", [])]
        result = {f"user:{u}" for u in users if u} | {f"group:{g}" for g in groups if g}
        self._restriction_cache[content_id] = result or None
        return result or None

    def _effective_principals(self, page_id: str, space_key: str | None) -> list[str]:
        space_principals = (self.config.get("space_principals") or {}).get(space_key or "", None)
        base = set(space_principals or self.config.get("default_principals") or ["*"])
        chain = [page_id] + [str(a["id"]) for a in self._ancestors(page_id)]
        restricted = [r for r in (self._read_restriction(cid) for cid in chain) if r is not None]
        if not restricted:
            return sorted(base)
        effective = set.intersection(*restricted)
        # Restriction lists are explicit grants; space-level visibility must also hold.
        if "*" not in base:
            effective = {p for p in effective if p in base or p.startswith("user:")}
        return sorted(effective)

    def _ancestors(self, page_id: str) -> list[dict]:
        return list(self._paginate(f"/wiki/api/v2/pages/{page_id}/ancestors", {"limit": 250}))

    def fetch_permissions(self, external_id: str) -> list[str]:
        page = self._get(f"/wiki/api/v2/pages/{external_id}")
        if not page:
            return []
        self._resolve_spaces()
        return self._effective_principals(external_id, self._space_keys_by_id.get(str(page.get("spaceId"))))

    # -- Documents ------------------------------------------------------------
    def fetch_document(self, external_id: str) -> NormalizedDocument | None:
        page = self._get(f"/wiki/api/v2/pages/{external_id}", {"body-format": "storage"})
        if not page or page.get("status") not in (None, "current"):
            return None
        self._resolve_spaces()
        space_key = self._space_keys_by_id.get(str(page.get("spaceId")))
        title = page.get("title", "")
        html = ((page.get("body") or {}).get("storage") or {}).get("value", "")
        sections, links = parse_storage_html(html, title)
        ancestors = self._ancestors(external_id)
        links_meta = page.get("_links") or {}
        webui = links_meta.get("webui")
        url = f"{self.base}/wiki{webui}" if webui else None
        version = page.get("version") or {}
        return NormalizedDocument(
            external_id=str(page["id"]),
            title=title,
            url=url,
            parent_external_id=str(page["parentId"]) if page.get("parentId") else None,
            path=[space_key or ""] + [a.get("title", str(a.get("id"))) for a in ancestors],
            sections=sections,
            source_format="confluence_storage",
            author=f"user:{page['authorId']}" if page.get("authorId") else None,
            owner=f"user:{page['ownerId']}" if page.get("ownerId") else None,
            created_at=_parse_dt(page.get("createdAt")),
            updated_at=_parse_dt(version.get("createdAt")) or _parse_dt(page.get("createdAt")),
            source_version=str(version.get("number", "")) or None,
            document_type="page",
            links=links,
            principals=self._effective_principals(str(page["id"]), space_key),
            raw_metadata={"space_key": space_key or "", "space_id": str(page.get("spaceId", ""))},
        )

    def close(self) -> None:
        self.client.close()
