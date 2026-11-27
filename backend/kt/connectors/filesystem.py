"""Filesystem connector: a folder of Markdown / HTML / text files.

Optional YAML front matter per file::

    ---
    title: Payment Retry Policy
    owner: user:anna
    groups: [group:engineering]     # read principals; default ["*"]
    updated: 2026-10-12
    type: policy
    links: [payments/architecture.md]
    ---
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from kt.connectors.base import KnowledgeConnector, register_connector
from kt.domain.models import ChangeBatch, ChangeEvent, NormalizedDocument, Section
from kt.ingestion.parsing import parse_markdown, parse_storage_html

SUPPORTED = {".md", ".markdown", ".txt", ".html", ".htm"}


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            meta = yaml.safe_load(parts[0][3:]) or {}
            body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
            return (meta if isinstance(meta, dict) else {}), body
    return {}, text


@register_connector
class FilesystemConnector(KnowledgeConnector):
    type = "filesystem"

    @property
    def root(self) -> Path:
        return Path(self.config["path"]).expanduser().resolve()

    def validate(self) -> None:
        if not self.root.is_dir():
            raise ValueError(f"Directory does not exist: {self.root}")

    def _files(self) -> list[Path]:
        excludes = self.config.get("exclude", [])
        files = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if p.is_file() and p.suffix.lower() in SUPPORTED and not any(Path(rel).match(e) for e in excludes):
                if not any(part.startswith(".") for part in Path(rel).parts):
                    files.append(p)
        return files

    def _version(self, p: Path) -> str:
        return hashlib.sha1(p.read_bytes()).hexdigest()[:12]

    def list_changes(self, cursor: dict[str, Any] | None) -> ChangeBatch:
        current = {p.relative_to(self.root).as_posix(): self._version(p) for p in self._files()}
        previous: dict[str, str] = (cursor or {}).get("versions", {})
        events = [
            ChangeEvent(type="upsert", external_id=k, source_version=v)
            for k, v in current.items()
            if previous.get(k) != v
        ]
        events += [ChangeEvent(type="delete", external_id=k) for k in previous if k not in current]
        # Comparing two full listings is a complete enumeration -> deletes are reliable.
        return ChangeBatch(events=events, next_cursor={"versions": current}, complete=True)

    def fetch_document(self, external_id: str) -> NormalizedDocument | None:
        path = (self.root / external_id).resolve()
        if not path.is_file() or self.root not in path.parents:
            return None
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        title = str(meta.get("title") or path.stem.replace("-", " ").replace("_", " ").title())
        if path.suffix.lower() in (".html", ".htm"):
            sections, links = parse_storage_html(body, title)
            fmt = "html"
        elif path.suffix.lower() == ".txt":
            sections, links, fmt = [Section(text=body.strip())] if body.strip() else [], [], "text"
        else:
            sections, links = parse_markdown(body)
            fmt = "markdown"
        links = list(dict.fromkeys([*links, *[str(x) for x in meta.get("links", []) or []]]))
        # Resolve relative file links to external ids of this source.
        resolved = []
        for link in links:
            if link.startswith(("http://", "https://", "title:", "mailto:")):
                resolved.append(link)
            else:
                target = (path.parent / link.split("#")[0]).resolve()
                if self.root in target.parents:
                    resolved.append(target.relative_to(self.root).as_posix())
        principals = meta.get("groups") or meta.get("principals") or self.config.get("default_principals") or ["*"]
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        rel_parts = Path(external_id).parts[:-1]
        base_url = self.config.get("base_url")
        return NormalizedDocument(
            external_id=external_id,
            title=title,
            url=(f"{base_url.rstrip('/')}/{external_id}" if base_url else path.as_uri()),
            path=list(rel_parts),
            parent_external_id=None,
            sections=sections,
            source_format=fmt,
            language=str(meta.get("language", "en")),
            author=meta.get("author"),
            owner=meta.get("owner"),
            created_at=_as_dt(meta.get("created")),
            updated_at=_as_dt(meta.get("updated")) or mtime,
            source_version=self._version(path),
            document_type=meta.get("type"),
            links=resolved,
            principals=[str(p) for p in principals],
            raw_metadata={k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list))},
        )

    def validate_path(self) -> Path:  # pragma: no cover - convenience
        self.validate()
        return self.root
