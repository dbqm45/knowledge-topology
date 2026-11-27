"""Knowledge Topology MCP server (stdio by default, Streamable HTTP optional).

Configure in your agent, e.g.::

    {"mcpServers": {"knowledge-topology": {
        "command": "kt", "args": ["mcp"],
        "env": {"KT_MCP_API_KEY": "<agent key>", "KT_DATABASE_URL": "...", "KT_VECTOR_BACKEND": "qdrant"}}}}
"""

from __future__ import annotations

import json
import os

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from kt.config import get_settings
from kt.db.session import init_db
from kt.mcp.tools import KnowledgeTools
from kt.runtime import principal_from_api_key

INSTRUCTIONS = """Knowledge Topology: an indexed, quality-aware map of the organisation's documentation.
Policy for answering questions about internal documentation:
1. Use search_knowledge first; it returns only the most relevant evidence chunks with source URLs.
2. Do not enumerate or read whole pages unless needed; use get_document_context to expand one chunk,
   get_document only when the full page is really required.
3. If results carry warnings (conflict/stale/duplicate), mention the uncertainty and cite both sources;
   use check_knowledge_conflicts when exact values matter.
4. Use list_knowledge_domains / get_knowledge_area to narrow the search to an area (domain_id).
5. Always cite document titles and URLs. Never invent information that retrieval did not return.
6. Fall back to the legacy source integration only when these tools cannot satisfy the request."""


def _prune(obj):
    if isinstance(obj, dict):
        return {k: _prune(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_prune(v) for v in obj]
    return obj


def _result(data: dict) -> CallToolResult:
    """Compact JSON (no indentation, no nulls): every token returned to the agent costs money."""
    data = _prune(data)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data,
                          is_error="error" in data)


def build_server(tools: KnowledgeTools) -> MCPServer:
    server = MCPServer(name="knowledge-topology", instructions=INSTRUCTIONS, version="0.1.0")

    @server.tool(structured_output=False, description="Hybrid (semantic + keyword) search over the knowledge base. Returns the most relevant "
                             "evidence chunks with source URLs, related entities/areas and quality warnings, within "
                             "a token budget.")
    def search_knowledge(query: str, domain_id: str | None = None, top_k: int = 6, include_evidence: bool = True,
                         include_related: bool = True, max_tokens: int = 2500, mode: str = "hybrid"):
        return _result(tools.search_knowledge(query, domain_id, top_k, include_evidence, include_related, max_tokens, mode))

    @server.tool(structured_output=False, description="Full content of one document (truncated to max_tokens). Prefer get_document_context.")
    def get_document(document_id: str, max_tokens: int = 4000):
        return _result(tools.get_document(document_id, max_tokens))

    @server.tool(structured_output=False, description="A chunk plus its neighbouring chunks — cheap context expansion around a search hit.")
    def get_document_context(document_id: str, chunk_id: str | None = None, window: int = 1):
        return _result(tools.get_document_context(document_id, chunk_id, window))

    @server.tool(structured_output=False, description="Documents related to a document (links, semantic similarity, duplicates, conflicts) "
                             "and the entities it mentions.")
    def get_related_knowledge(document_id: str, limit: int = 8):
        return _result(tools.get_related_knowledge(document_id, limit))

    @server.tool(structured_output=False, description="Knowledge areas (clusters) visible to you, with size, health index and shape class.")
    def list_knowledge_domains(include_subareas: bool = False):
        return _result(tools.list_knowledge_domains(include_subareas))

    @server.tool(structured_output=False, description="Details of a knowledge area: description, sub-areas, documents, quality metrics.")
    def get_knowledge_area(domain_id: str, include_documents: bool = True):
        return _result(tools.get_knowledge_area(domain_id, include_documents))

    @server.tool(structured_output=False, description="Find entities (systems, processes, concepts, identifiers) by name.")
    def find_entities(name: str, limit: int = 10):
        return _result(tools.find_entities(name, limit))

    @server.tool(structured_output=False, description="An entity with its aliases and the documents that mention it.")
    def get_entity(entity_id: str):
        return _result(tools.get_entity(entity_id))

    @server.tool(structured_output=False, description="Quality profile of an area (8 metrics with confidence), trend and open issues.")
    def get_knowledge_health(domain_id: str):
        return _result(tools.get_knowledge_health(domain_id))

    @server.tool(structured_output=False, description="Suspected contradictions among documents relevant to a question (e.g. different "
                             "values for the same setting), with the conflicting quotes and sources.")
    def check_knowledge_conflicts(query: str, domain_id: str | None = None, top_k: int = 10):
        return _result(tools.check_knowledge_conflicts(query, domain_id, top_k))

    @server.tool(structured_output=False, description="Known gaps of an area: unexplained concepts, missing required topics, stale/orphan docs.")
    def get_knowledge_gaps(domain_id: str):
        return _result(tools.get_knowledge_gaps(domain_id))

    @server.tool(structured_output=False, description="Exact quoted evidence for chunk ids (verification of a claim).")
    def get_knowledge_evidence(chunk_ids: list[str]):
        return _result(tools.get_knowledge_evidence(chunk_ids))

    @server.tool(structured_output=False, description="Document and topology changes since an ISO-8601 timestamp.")
    def get_knowledge_changes(since: str, domain_id: str | None = None, limit: int = 50):
        return _result(tools.get_knowledge_changes(since, domain_id, limit))

    @server.tool(structured_output=False, description="Compare two topology snapshots: new, split, merged, removed and changed areas.")
    def compare_knowledge_snapshots(from_snapshot_id: str, to_snapshot_id: str | None = None):
        return _result(tools.compare_knowledge_snapshots(from_snapshot_id, to_snapshot_id))

    @server.tool(structured_output=False, description="Recent topology snapshots (ids for compare_knowledge_snapshots).")
    def list_knowledge_snapshots(limit: int = 10):
        return _result(tools.list_knowledge_snapshots(limit))

    @server.resource("knowledge://workspace/overview", name="overview", mime_type="application/json",
                     description="Areas, health and open issue counts visible to this client.")
    def overview() -> str:
        domains = tools.list_knowledge_domains().get("items", [])
        return json.dumps({"areas": domains, "principal": tools.principal.id}, ensure_ascii=False)

    @server.resource("knowledge://domains/{domain_id}", name="domain", mime_type="application/json",
                     description="One knowledge area.")
    def domain_resource(domain_id: str) -> str:
        return json.dumps(tools.get_knowledge_area(domain_id, include_documents=True), ensure_ascii=False)

    return server


def main(transport: str = "stdio") -> None:
    settings = get_settings()
    init_db()
    principal = principal_from_api_key(settings.mcp_api_key or os.environ.get("KT_API_KEY"))
    server = build_server(KnowledgeTools(principal))
    if transport == "http":
        server.run("streamable-http")
    else:
        server.run()
