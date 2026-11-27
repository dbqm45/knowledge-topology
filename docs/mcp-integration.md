# Integracja z istniejącym agentem (MCP)

## Konfiguracja (stdio)

```json
{
  "mcpServers": {
    "knowledge-topology": {
      "command": "C:\\knowledge-topology\\backend\\.venv\\Scripts\\kt.exe",
      "args": ["mcp"],
      "env": {
        "KT_MCP_API_KEY": "<klucz agenta z data/api-keys.json>",
        "KT_DATA_DIR": "C:\\knowledge-topology\\backend\\data",
        "KT_DATABASE_URL": "sqlite:///C:/knowledge-topology/backend/data/kt.db"
      }
    }
  }
}
```

Przy stacku Docker: `KT_DATABASE_URL=postgresql+psycopg://kt:kt@127.0.0.1:5432/kt`,
`KT_VECTOR_BACKEND=qdrant`, `KT_QDRANT_URL=http://127.0.0.1:6333`.
Wspólny serwer dla wielu agentów: `kt mcp --http` (Streamable HTTP).

**Tożsamość** agenta pochodzi wyłącznie z klucza połączenia (`KT_MCP_API_KEY`) — nie z argumentów
narzędzi. Agent widzi dokładnie to, co pozwalają jego grupy (np. `dev-agent-key` = `group:engineering`).

## Narzędzia

| Grupa | Narzędzie | Kiedy |
| --- | --- | --- |
| Retrieval | `search_knowledge` | zawsze jako pierwsze; zwraca fragmenty-dowody, URL-e, encje, obszary, ostrzeżenia, zużycie tokenów |
| | `get_document_context` | rozszerzenie jednego trafienia o sąsiednie chunki (tanio) |
| | `get_document` | pełna strona (obcinana do `max_tokens`) — fallback |
| | `get_related_knowledge` | linki, podobne dokumenty, duplikaty, konflikty |
| Struktura | `list_knowledge_domains`, `get_knowledge_area` | zawężenie wyszukiwania do obszaru (`domain_id`) |
| | `find_entities`, `get_entity` | systemy/procesy/identyfikatory i ich dokumenty |
| Intelligence | `check_knowledge_conflicts` | gdy liczy się dokładna wartość (timeouty, limity, polityki) |
| | `get_knowledge_health`, `get_knowledge_gaps` | „jak dobrze wiemy” o danym obszarze |
| | `get_knowledge_evidence` | weryfikacja cytatu po `chunk_id` |
| Ewolucja | `get_knowledge_changes`, `compare_knowledge_snapshots`, `list_knowledge_snapshots` | co się zmieniło |

Zasoby: `knowledge://workspace/overview`, `knowledge://domains/{domain_id}`.

## Polityka do system promptu agenta

```text
Knowledge Retrieval Policy
1. For questions about internal documentation, architecture, APIs, processes or decisions, call
   search_knowledge first. It returns only the most relevant evidence with source URLs.
2. Do not enumerate or read whole pages if the evidence answers the question. Use
   get_document_context to expand a single hit; get_document only when the full page is required.
3. If the result contains warnings (conflict / stale / duplicate), say so, cite both sources, and use
   check_knowledge_conflicts when an exact value matters.
4. Use list_knowledge_domains / get_knowledge_area to narrow the search (domain_id) for broad questions.
5. Always cite document titles and URLs. Never invent information retrieval did not return.
6. Use the legacy Confluence integration only as a fallback when these tools cannot satisfy the request.
```

(Ta sama polityka jest wysyłana przez serwer jako `instructions` MCP.)

## Migracja bez przebudowy agenta (strangler pattern)

1. **Faza 1 — dodanie.** Dopisz serwer `knowledge-topology` obok obecnego Confluence MCP. Nic nie usuwasz.
   Porównuj odpowiedzi i zużycie tokenów na tych samych pytaniach.
2. **Faza 2 — przekierowanie.** Dodaj politykę powyżej: `search_knowledge` jako pierwsze, stary MCP jako
   fallback (pełne strony, operacje zapisu, przestrzenie jeszcze nieindeksowane).
3. **Faza 3 — optymalizacja.** Ogranicz stare narzędzia wyszukiwania; strój `top_k`, `max_tokens`,
   progi retrieval; dodawaj kolejne przestrzenie i źródła.

## Jak działa `search_knowledge`

1. ACL: zbiór dokumentów, które wywołujący może czytać (zawężony do `domain_id`, jeśli podano).
2. Kandydaci: wyszukiwanie wektorowe + BM25 (po 30), połączone przez Reciprocal Rank Fusion; progi
   odrzucają trafienia tylko-wektorowe o niskim podobieństwie.
3. **Reranker** (gdy `KT_RERANKER=cross-encoder`): cross-encoder czyta pytanie razem z każdym z najlepszych
   `KT_RERANKER_CANDIDATES` fragmentów (tytuł > sekcja > treść); jego prawdopodobieństwo zastępuje wynik RRF,
   fragmenty poniżej `KT_RERANKER_MIN_SCORE` odpadają. Reranker widzi wyłącznie fragmenty już przepuszczone przez ACL.
4. Grupowanie po dokumentach (≤ 2 fragmenty na dokument), deduplikacja identycznych treści, budżet tokenów.
5. Ostrzeżenia jakości z topologii (konflikty, duplikaty, nieaktualne źródła).

`usage` w odpowiedzi pokazuje `reranker`, `reranked` i `rerank_ms`; w REST reranking można wyłączyć
per zapytanie (`"retrieval": {"rerank": false}`), np. do porównań A/B.

## Pomiar oszczędności

Każda odpowiedź `search_knowledge` zawiera `usage`:

```json
{"candidates": 17, "returned_chunks": 4, "estimated_tokens": 167, "budget_tokens": 2500}
```

Plan pomiaru (A/B na 30–50 rzeczywistych pytaniach):

| Metryka | Stary MCP | Knowledge Topology |
| --- | --- | --- |
| wywołania narzędzi / pytanie | pomiar | pomiar |
| tokeny wejściowe LLM | pomiar | pomiar (`usage.estimated_tokens` + odpowiedź) |
| czas odpowiedzi | pomiar | pomiar |
| trafność źródeł (Recall@5, MRR) | pomiar | pomiar |
| poprawność odpowiedzi (ocena ekspercka) | pomiar | pomiar |

Koszt embeddingów ponosisz przy indeksowaniu i zmianach treści (zmiana samego ACL nie powoduje
re-embeddingu), a przy pytaniu — jeden embedding zapytania. Główna oszczędność wynika z tego, że
agent dostaje kilka fragmentów zamiast całych stron i nie musi „chodzić” po Confluence.
