# Roadmapa i stan realizacji

| Etap | Zakres | Stan |
| --- | --- | --- |
| 1. Platform foundation | monorepo, FastAPI, PostgreSQL/SQLite, Alembic, Qdrant, model tenantów, auth kluczami, trace_id, audyt, docker-compose | ✅ (Celery/Temporal i OpenTelemetry — później) |
| 2. Connector & ingestion | Confluence Cloud (v2 + CQL + restrykcje), filesystem, wersje, ACL, przyrost, usunięcia, reconciliation, webhook | ✅ |
| 3. Semantic foundation | chunking strukturalny, embeddingi (hashing/BGE-M3/OpenAI), hybrid retrieval, dowody, budżet tokenów, MCP | ✅ (reranker cross-encoder — do dodania) |
| 4. Knowledge graph | encje, aliasy-kandydaci, graf wielosygnałowy, Leiden/Louvain + HDBSCAN, hierarchia, lineage | ✅ (ekstrakcja encji przez LLM — opcjonalny plugin) |
| 5. Knowledge intelligence | 8 metryk z confidence, konflikty liczbowe (też cross-area), duplikaty, sieroty, luki, Issue Explorer z workflow | ✅ (sprzeczności semantyczne z LLM, coverage templates w UI — dalej) |
| 6. Topology visualization | Universe 3D, Graph 2D, mapa obszaru, Explain this connection, macierz Health, wyjaśnialne deformacje | ✅ (LOD dla >10k dokumentów — dalej) |
| 7. Evolution & hybrid | snapshoty, lineage, porównanie, zmiany od daty | ✅ ewolucja; ⏳ wydzielony Knowledge Edge + Ingestion Gateway |
| 8. Production hardening | testy ACL (są), SSO/OIDC, rate limiting, backup, monitoring, testy wydajności | ⏳ |

## Najbliższe kroki (rekomendowane)

1. **Pilot na jednej przestrzeni Confluence** (100–500 stron) z BGE-M3; 50–100 pytań referencyjnych,
   pomiar A/B tokenów względem obecnego Confluence MCP (docs/mcp-integration.md).
2. Kalibracja progów (`KT_RETRIEVAL_*`, `GraphParams`) i coverage templates dla 2–3 domen.
3. Reranker (cross-encoder) w `RetrievalService` dla górnych 30 kandydatów.
4. Detekcja sprzeczności semantycznych (LLM na parach chunków z wysokim podobieństwem — tylko kandydaci
   wskazani przez graf, z cache) + feedback „to nie jest konflikt” zapisywany w issue.
5. Knowledge Edge: `kt worker` w trybie edge wysyłający zdarzenia (`document.updated`, `document.access_changed`)
   do centralnego API — polityka, które pola opuszczają infrastrukturę.
6. SSO (OIDC) dla UI, tożsamości agentów z rotacją kluczy, rate limiting MCP/REST.
7. Kolejne connectory (Notion, SharePoint, Google Drive, GitHub) — implementacja `KnowledgeConnector`.
