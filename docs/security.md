# Bezpieczeństwo i uprawnienia

## Model

- **Principal** = użytkownik, service account lub agent: `id`, `groups`, `roles`, `tenant_id`.
  Tokeny dostępu: `{"*", id, ...groups}`. Rola `admin` = audytor (uprzywilejowana topologia).
- **ACL dokumentu** (`document_acl`) = efektywni czytelnicy wyliczeni przez connector:
  - filesystem: `groups:` we front matter lub `default_principals` źródła, domyślnie `*`;
  - Confluence: uprawnienia przestrzeni (`space_principals`) zawężone restrykcjami odczytu strony
    **i każdego przodka z restrykcją** (część wspólna — konserwatywnie; pusta część wspólna ukrywa stronę).
- Uwierzytelnianie: klucze API (`data/api-keys.json`, porównanie w stałym czasie). SSO/OIDC — etap 8.

## Trzy warstwy kontroli

1. **Ingestion ACL** — uprawnienia ze źródła zapisywane przy każdej synchronizacji; zmiana ACL działa
   natychmiast (DB + payload Qdrant) bez re-embeddingu.
2. **Query-time authorization** (`kt.access.AccessService`) — każda ścieżka odczytu (REST i MCP)
   przecina wyniki z autorytatywną listą czytelnych dokumentów z bazy. Payload w Qdrant to tylko pre-filtr.
3. **Visualization authorization** (`kt.topology.views`):
   - obszar bez czytelnych dokumentów **nie istnieje** dla wywołującego (brak etykiety, krawędzi, liczby);
   - obszar widoczny częściowo: neutralny okrąg, brak metryk, health, issues i nici; etykieta liczona
     tylko z czytelnych dokumentów; wagi krawędzi ukryte;
   - issues widoczne tylko, gdy wywołujący widzi **wszystkie** dokumenty-dowody;
   - encje istnieją dla wywołującego tylko przez czytelne dokumenty.

## Brak „wyroczni istnienia”

Brak uprawnień i brak zasobu zwracają identyczne `404 NOT_FOUND` („The requested resource is
unavailable.”). Wyniki wyszukiwania nie ujawniają liczby odfiltrowanych dokumentów.

## Audyt

`audit_events`: synchronizacje, przebudowy topologii, zmiany statusu/przypisania issues (aktor, zmiany,
komentarz). Endpoint `GET /api/v1/audit` (admin).

## Scenariusze testowe (`backend/tests/test_security.py`)

1. Użytkownik bez dostępu nie dostaje dokumentów HR w trybie vector, lexical i hybrid.
2. Obszar HR nie istnieje w topologii, mapie, health i krawędziach dla inżyniera.
3. Znane ID poufnego dokumentu → 404 w `get_document`, `context`, `related`, `evidence`.
4. Issues i encje są filtrowane.
5. Częściowa widoczność obszaru nie ujawnia metryk ani geometrii (także po przebudowie).
6. Agenci (MCP) widzą dokładnie zakres swojej tożsamości.
7. Zmiana ACL i usunięcie dokumentu działają od następnej synchronizacji.

## Wdrożenie

- Porty w docker-compose wiązane tylko do `127.0.0.1`.
- Sekrety (token Confluence, klucze OpenAI) tylko w zmiennych środowiskowych; konfiguracja źródła
  przechowuje nazwę zmiennej, nie wartość; `GET /sources` maskuje pola `*token*`, `*secret*`, `*password*`.
- Embeddingi `sentence-transformers` (BGE-M3) działają lokalnie — treść nie opuszcza infrastruktury.
- Klucze deweloperskie (`kt init --dev-keys`, `kt demo`) są tylko do lokalnego demo.
