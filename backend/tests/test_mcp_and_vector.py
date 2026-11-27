import anyio
import numpy as np


def test_mcp_server_lists_and_calls_tools(demo):
    from kt.mcp.server import build_server
    from kt.mcp.tools import KnowledgeTools
    from kt.runtime import principal_from_api_key

    server = build_server(KnowledgeTools(principal_from_api_key("eng")))

    async def run():
        tools = {t.name for t in await server.list_tools()}
        assert {"search_knowledge", "get_document", "get_knowledge_area", "check_knowledge_conflicts",
                "get_knowledge_health", "get_knowledge_changes", "compare_knowledge_snapshots"} <= tools
        result = await server.call_tool("search_knowledge", {"query": "payment retry attempts", "top_k": 3})
        payload = result.structured_content
        assert payload["results"] and payload["usage"]["estimated_tokens"] > 0
        text = result.content[0].text
        assert "\n" not in text and ": " not in text[:200] and "null" not in text  # compact for token economy
        domains = await server.call_tool("list_knowledge_domains", {})
        assert domains.structured_content
        conflicts = await server.call_tool("check_knowledge_conflicts", {"query": "how many payment retries"})
        assert conflicts.structured_content["conflicts"]
        missing = await server.call_tool("get_document", {"document_id": "nope"})
        assert missing.is_error and missing.structured_content["error"]["code"] == "NOT_FOUND"
        resources = {str(r.uri) for r in await server.list_resources()}
        assert "knowledge://workspace/overview" in resources

    anyio.run(run)


def test_qdrant_backend_local_mode():
    from qdrant_client import QdrantClient

    from kt.storage.vector import QdrantVectorStore, VectorPoint

    store = QdrantVectorStore("", "test", 4, client=QdrantClient(":memory:"))
    ids = ["00000000-0000-0000-0000-00000000000%d" % i for i in range(3)]
    vecs = [np.array(v, dtype=np.float32) for v in ([1, 0, 0, 0], [0.9, 0.1, 0, 0], [0, 1, 0, 0])]
    store.upsert([VectorPoint(ids[i], vecs[i] / np.linalg.norm(vecs[i]),
                              {"tenant_id": "t", "document_id": f"d{i}", "principals": ["*"] if i < 2 else ["group:hr"]})
                  for i in range(3)])
    hits = store.search("t", np.array([1, 0, 0, 0], dtype=np.float32), 5, {"*"})
    assert [h.payload["document_id"] for h in hits] == ["d0", "d1"]
    store.set_document_acl("t", "d2", ["*"])
    assert len(store.search("t", np.array([0, 1, 0, 0], dtype=np.float32), 5, {"*"})) == 3
    store.delete_document("t", "d0")
    assert ids[0] not in store.fetch(ids) and ids[1] in store.fetch(ids)
