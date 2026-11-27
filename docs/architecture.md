# Architektura

## Zasada

Knowledge Topology to **niezależny silnik domenowy**. Connectory, interfejs webowy i agenci AI są jego
klientami. Źródła danych są wymienne; cała logika analizy pracuje na kanonicznym modelu dokumentu.

```
            SOURCE CONNECTORS (kt.connectors)
        Confluence Cloud · Filesystem · (Notion, SharePoint, GitHub …)
                         │  NormalizedDocument (sekcje, linki, ACL, wersja)
                         ▼
   INGESTION (kt.ingestion) ── wersje, hash treści, ACL, linki, usunięcia, reconciliation
                         │
   SEMANTIC LAYER (kt.semantic, kt.storage, kt.entities)
        chunking strukturalny · embeddingi · Qdrant/lokalny store · BM25 · encje · claims
                         │
   TOPOLOGY ENGINE (kt.topology)                 INTELLIGENCE (kt.intelligence)
        graf → klastry → lineage → metryki → issues → geometria → layout → snapshot
                         │
   ACCESS (kt.access) + VIEWS (kt.topology.views) ── autoryzacja wyszukiwania, grafu, mapy, metryk
                         │
              KnowledgeService (kt.services) — jedna fasada
                 ┌───────┴────────┐
          REST API (kt.api)   MCP server (kt.mcp)
                 │                │
             Web UI (web/)    istniejący agent
```

## Jednostki wdrożeniowe

Modularny monolit + osobne procesy (ADR-001):

| Proces | Komenda | Rola |
| --- | --- | --- |
| api | `kt serve` | REST v1 + statyczny Web UI |
| worker | `kt worker` | cykliczny sync (przyrostowy) + przebudowa topologii, gdy `topology_dirty` |
| mcp | `kt mcp` / `kt mcp --http` | serwer MCP dla agentów (stdio domyślnie) |
| CLI | `kt init/source/sync/build/demo/search` | administracja |

Zadania (sync, rebuild) są funkcjami w `kt.jobs` — dziś uruchamiane w procesie (BackgroundTasks,
worker loop), później bez zmian w logice opakowywalne w Celery/Temporal.

## Przechowywanie

| Magazyn | Co | Uwagi |
| --- | --- | --- |
| PostgreSQL (prod) / SQLite (dev) | źródło prawdy: dokumenty, wersje, chunki, ACL, encje, relacje, domeny, snapshoty, metryki, issues, audyt | migracje Alembic (`backend/migrations`) |
| Qdrant (prod) / plik lokalny (dev) | wektory chunków + payload (tenant, dokument, ACL jako pre-filtr) | ACL w payloadzie to tylko filtr pomocniczy |
| `topology_snapshots.payload` | pełna geometria i layout snapshotu | w dużej skali → object storage |

Graf jest w PostgreSQL (`relations` z typami końców). Wydzielenie Neo4j/AGE ma sens dopiero przy
wieloetapowych traversalach i analizach centralności (ADR-004).

### Model danych (najważniejsze tabele)

`tenants` · `sources` · `documents` · `document_versions` · `chunks` · `document_acl` · `document_links` ·
`entities` · `entity_mentions` · `relations` · `knowledge_domains` (stabilny `stable_key`, hierarchia) ·
`cluster_memberships` (dokument może należeć do wielu domen, per snapshot) · `topology_snapshots` ·
`quality_metrics` (score, confidence, sample_size, measured, signals) · `snapshot_cluster_lineage` ·
`issues` (fingerprint → stan workflow przetrwa przeliczenie) · `sync_jobs` · `audit_events`.

Każdy wiersz ma `tenant_id`. MVP obsługuje jednego tenanta (`default`), ale model i zapytania są już
wielotenantowe.

## Przepływ synchronizacji

1. `connector.list_changes(cursor)` — pełne wyliczenie (pierwszy raz / reconciliation co `reconcile_hours`)
   albo zmiany przyrostowe (Confluence: CQL `lastmodified`).
2. Dla każdej zmiany `fetch_document` → `NormalizedDocument` z efektywnymi uprawnieniami.
3. Hash treści bez zmian → aktualizacja tylko metadanych/ACL (ACL także w payloadzie Qdrant).
   Zmiana treści → nowa wersja, nowe chunki, embeddingi, wzmianki encji.
4. Usunięcie → `status=deleted`, wektory usunięte, historia wersji zostaje.
5. Rozwiązanie linków (id, tytuł, URL Confluence) → `document_links.to_document_id`.
6. `topology_dirty = true` → worker buduje nowy snapshot.

Webhook (`POST /api/v1/webhooks/confluence/{source_id}`, nagłówek `X-KT-Webhook-Secret`) tylko
**przyspiesza** synchronizację konkretnej strony; gwarancją spójności jest reconciliation.

## Hybrid deployment

Wszystkie komponenty są procesami Pythona bez zależności od chmury, więc ten sam kod działa w trzech
profilach (ADR-009):

| Profil | Gdzie działa connector + embeddingi | Gdzie UI / analiza |
| --- | --- | --- |
| Fully self-hosted (dzisiejszy docker-compose) | lokalnie | lokalnie |
| Hybrid private | lokalnie (Knowledge Edge = `kt worker` + lokalne BGE-M3) | centralnie, tylko metadane i wyniki dozwolone polityką |
| Hybrid standard | lokalnie lub centralnie | centralnie |

Wydzielenie „Knowledge Edge” jako osobnego procesu wysyłającego zdarzenia do centralnego Ingestion
Gateway jest zaplanowane w roadmapie (etap 7); kontrakt connectora i `kt.jobs` są już do tego przygotowane.

## API

REST `/api/v1` (OpenAPI: `http://127.0.0.1:8000/docs`):

| Grupa | Endpointy |
| --- | --- |
| Wiedza | `POST /search`, `GET /documents/{id}`, `/documents/{id}/context`, `/documents/{id}/related`, `GET /entities`, `/entities/{id}`, `POST /conflicts/check`, `POST /evidence` |
| Topologia | `GET /topology`, `/snapshots`, `/domains`, `/domains/{id}`, `/domains/{id}/health`, `/domains/{id}/gaps` |
| Intelligence | `GET /issues`, `/issues/{id}`, `PATCH /issues/{id}` (audytowane) |
| Ewolucja | `GET /evolution/compare`, `GET /changes?since=` |
| Admin | `GET/POST /sources`, `POST /sources/{id}/sync`, `POST /topology/rebuild`, `GET /audit`, `POST /webhooks/confluence/{id}` |

Wspólny model błędu: `{"error": {"code", "message", "trace_id"}}` + nagłówek `X-Trace-Id`.
Brak uprawnień do zasobu = `404 NOT_FOUND` z identycznym komunikatem jak dla nieistniejącego zasobu.
Uwierzytelnianie: `Authorization: Bearer <key>` lub `X-API-Key` (klucze w `data/api-keys.json`).
