"""Second-stage reranking: plumbing, ordering, filtering, ACL and the cross-encoder adapter."""

import sys
import types

from kt.retrieval.rerank import CrossEncoderReranker, Reranker, _to_probabilities

QUERY = "How many times are failed card payments retried?"
HR = {"Leave Policy", "Compensation Bands", "Employee Onboarding", "Performance Reviews"}


class KeywordReranker(Reranker):
    """Deterministic stand-in for a cross-encoder: relevance = does the passage contain the keyword."""

    model_id = "fake-keyword-reranker"

    def __init__(self, keyword: str):
        self.keyword = keyword.lower()
        self.seen: list[str] = []

    def score(self, query, passages):
        self.seen.extend(passages)
        return [0.9 if self.keyword in p.lower() else 0.02 for p in passages]


def _search(key, reranker, **kw):
    from kt.db.session import session_factory
    from kt.runtime import principal_from_api_key
    from kt.semantic.embeddings import get_embedder
    from kt.services import KnowledgeService
    from kt.storage.vector import get_vector_store

    svc = KnowledgeService(session_factory()(), principal_from_api_key(key), get_embedder(), get_vector_store(),
                           reranker=reranker)
    return svc.search(kw.pop("query", QUERY), **kw)


def test_reranker_reorders_and_reports(demo):
    baseline = _search("eng", None, top_k=5)
    assert baseline["usage"]["reranker"] is None
    rr = KeywordReranker("retry orchestrator")
    res = _search("eng", rr, top_k=5)
    assert res["results"][0]["title"] == "Retry Orchestrator"
    assert baseline["results"][0]["title"] != "Retry Orchestrator"
    assert "reranked" in res["results"][0]["retrieval_reasons"]
    assert res["usage"]["reranker"] == "fake-keyword-reranker" and 0 < res["usage"]["reranked"] <= 30
    assert res["results"][0]["evidence"][0]["rerank_score"] == 0.9
    # The cross-encoder reads title + section path + content.
    assert any(p.startswith("Retry Orchestrator > ") for p in rr.seen)


def test_min_score_filters_irrelevant(demo, monkeypatch):
    monkeypatch.setenv("KT_RERANKER_MIN_SCORE", "0.5")
    from conftest import reset_caches

    reset_caches()
    res = _search("eng", KeywordReranker("retry orchestrator"), top_k=10)
    assert res["results"] and res["results"][0]["title"] == "Retry Orchestrator"
    assert all(ev["rerank_score"] >= 0.5 for r in res["results"] for ev in r["evidence"])
    nothing = _search("eng", KeywordReranker("no-such-keyword"), top_k=10)
    assert nothing["results"] == []


def test_reranker_never_sees_forbidden_passages(demo):
    rr = KeywordReranker("leave")
    res = _search("eng", rr, query="annual leave carried over until March", top_k=10)
    assert not {r["title"] for r in res["results"]} & HR
    assert not any(any(t in p for t in HR) for p in rr.seen)


def test_rerank_can_be_disabled_per_request(demo):
    res = _search("eng", KeywordReranker("retry orchestrator"), top_k=5, rerank=False)
    assert res["usage"]["reranker"] is None
    assert all("reranked" not in r["retrieval_reasons"] for r in res["results"])


def test_api_rerank_flag(demo, monkeypatch):
    from fastapi.testclient import TestClient

    from kt.api.main import create_app
    from kt.retrieval import rerank

    monkeypatch.setattr(rerank, "get_reranker", lambda: KeywordReranker("retry orchestrator"))
    c = TestClient(create_app())
    h = {"X-API-Key": "eng"}
    on = c.post("/api/v1/search", headers=h, json={"query": QUERY}).json()
    off = c.post("/api/v1/search", headers=h, json={"query": QUERY, "retrieval": {"rerank": False}}).json()
    assert on["usage"]["reranker"] == "fake-keyword-reranker" and on["results"][0]["title"] == "Retry Orchestrator"
    assert off["usage"]["reranker"] is None


def test_cross_encoder_adapter(monkeypatch):
    calls = {}

    class FakeCrossEncoder:
        def __init__(self, model, max_length=512, device=None):
            calls["init"] = (model, max_length, device)

        def predict(self, pairs, batch_size=16, show_progress_bar=False):
            calls["pairs"] = pairs
            return [4.0 if "retry" in p else -4.0 for _, p in pairs]  # logits

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder))
    rr = CrossEncoderReranker("BAAI/bge-reranker-v2-m3", max_length=256)
    scores = rr.score("q", ["retry policy", "leave policy"])
    assert calls["init"] == ("BAAI/bge-reranker-v2-m3", 256, None)
    assert calls["pairs"] == [("q", "retry policy"), ("q", "leave policy")]
    assert scores[0] > 0.98 and scores[1] < 0.02
    assert rr.score("q", []) == []


def test_probability_normalisation():
    assert _to_probabilities([0.2, 0.9]) == [0.2, 0.9]  # already probabilities
    p = _to_probabilities([0.0, 10.0, -10.0])
    assert abs(p[0] - 0.5) < 1e-9 and p[1] > 0.999 and p[2] < 0.001


def test_settings_build_reranker(monkeypatch):
    from conftest import reset_caches

    from kt.config import get_settings
    from kt.retrieval.rerank import build_reranker

    monkeypatch.setenv("KT_RERANKER", "none")
    reset_caches()
    assert build_reranker(get_settings()) is None
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(
        CrossEncoder=lambda *a, **k: types.SimpleNamespace(predict=lambda *x, **y: [])))
    monkeypatch.setenv("KT_RERANKER", "cross-encoder")
    monkeypatch.setenv("KT_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    reset_caches()
    assert build_reranker(get_settings()).model_id == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    monkeypatch.delenv("KT_RERANKER")
    reset_caches()
