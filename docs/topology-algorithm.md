# Algorytm Knowledge Topology

Implementacja: `backend/kt/topology/`. Każdy przebieg zapisuje `algorithm_version`, model embeddingów
i parametry (`topology_snapshots.params`), więc mapa jest odtwarzalna.

## 1. Korpus

`corpus.load_corpus` — aktywne dokumenty, bieżące chunki, wektor dokumentu = średnia wektorów chunków
ważona liczbą tokenów (znormalizowana), encje, rozwiązane linki, twierdzenia liczbowe (*claims*) i
shingle (do duplikatów).

## 2. Graf wielosygnałowy

```
W_ij = α·S_semantic + β·S_entity + γ·S_link + δ·S_context      (α,β,γ,δ = 0.55, 0.20, 0.15, 0.10)
```

- `S_semantic` — cosinus **względem tła korpusu**: `clip((cos − (μ + 0.5σ)) / (1 − (μ + 0.5σ)))`.
  Dzięki temu wagi są porównywalne między różnymi modelami embeddingów.
- `S_entity` — ważony IDF Jaccard wspólnych encji.
- `S_link` — jawny link w źródle (krawędź zawsze zostaje).
- `S_context` — wspólny prefiks ścieżki w tym samym źródle (space/folder).

Kandydaci to kNN (k=8) + jawne linki; krawędź zostaje, gdy `W ≥ 0.12`. Każda krawędź przechowuje
wszystkie sygnały — widok „Explain this connection” pokazuje dokładnie ten rozkład.
Duplikaty: cosinus ≥ 0.95 lub Jaccard 5-wyrazowych shingli ≥ 0.6.

## 3. Klasteryzacja hybrydowa

1. **Leiden** (jeśli zainstalowano `[leiden]`) lub **Louvain** na grafie `W` — granice obszarów.
2. **HDBSCAN** na macierzy odległości `1 − cos` — niezależny widok gęstości.
3. Pewność klastra = `0.5·zgodność(HDBSCAN) + 0.5·średnia przynależność`.
4. Przynależność dokumentu = udział wagi jego krawędzi wewnątrz klastra → `core / peripheral / low_confidence`.
5. Społeczności mniejsze niż 3 dokumenty → dokumenty **nieprzypisane** (sieroty, nie są wciskane na siłę).
6. Klastry ≥ 8 dokumentów są dzielone na **podobszary** (ponowna detekcja społeczności, wyższa rozdzielczość).
7. Nazwa: najbardziej charakterystyczne encje (c-TF-IDF) — LLM może w przyszłości tylko *nazywać*, nigdy wyznaczać granic.

## 4. Lineage — stabilna tożsamość obszarów

`lineage.match_clusters`: zachłanne dopasowanie po Jaccardzie zbiorów dokumentów (≥ 0.3) do obszarów
z poprzedniego snapshotu:

- dopasowany → `continued` (dziedziczy `stable_key`),
- dopasowany i zawiera ≥ 50% innego starego obszaru → `merged_from`,
- niedopasowany, ale ≥ 40% dokumentów z jednego starego obszaru → `split_from` (nowy klucz),
- w pozostałych przypadkach → `new`.

Pozycje na mapie są inicjowane poprzednim snapshotem i tłumione (65% stara pozycja), więc mapa nie „skacze”.

## 5. Metryki jakości (0–100 + confidence + sample size + measured/estimated + sygnały)

| Metryka | Obliczenie | Typ |
| --- | --- | --- |
| Cohesion | kontrast podobieństwa wewnątrz obszaru vs najbliższy inny obszar (silhouette) − kara za rozrzut | measured |
| Connectivity | udział największej składowej, izolowane dokumenty, jawne linki, połączenia z innymi obszarami | measured |
| Coverage | *observed*: kluczowe encje z dedykowanym tytułem/sekcją + głębokość; *required*: checklista z `coverage_templates` | estimated / measured |
| Consistency | sprzeczne twierdzenia liczbowe wśród porównywalnych (≥3 wspólne terminy, ta sama jednostka) | measured |
| Clarity | struktura nagłówków, długość zdań, strony-zalążki | estimated |
| Freshness | `Σ exp(−ln2·age/half_life)`; half-life zależny od typu (runbook 180 dni, ADR 900 dni …) | measured |
| Duplication | odsetek dokumentów w parach near-duplicate | measured |
| Traceability | właściciel, URL źródła, wersja, data modyfikacji | measured |

Brak właściciela obniża *traceability*, nie *consistency* — wymiary są niezależne. Composite health
to tylko średnia ważona (z confidence) do ekranów przeglądowych.

Coverage wymagane (lepsza ocena kompletności) konfiguruje się w ustawieniach tenanta:

```json
{"coverage_templates": {"payment": ["retry policy", "refund", "reconciliation", "fraud", "chargeback"]}}
```

## 6. Issues

Każde zgłoszenie ma typ, metrykę, ważność, confidence (**detekcji**, nie prawdziwości), dowody
(cytaty z chunków), rekomendację i **fingerprint** — status workflow (`investigating`, `accepted`,
`dismissed`…) przetrwa przeliczenie topologii; zgłoszenie, które przestało występować, jest
automatycznie rozwiązywane, a jeśli wróci — otwierane ponownie.

Typy: `conflict` (także *cross-area* między powiązanymi obszarami), `duplicate`, `stale`, `isolated`,
`orphan`, `unowned`, `ambiguous_terminology` (aliasy-kandydaci — nigdy nie scalane automatycznie).

## 7. Geometry Engine (metryki → kształt)

```
r(θ) = r0 · [1 + a·sin(kθ+φ) + 0.45a·sin((k+3)θ+2φ) + b·L(θ) + c·C(θ)]
```

| Element | Źródło |
| --- | --- |
| `r0 = 0.55 + 0.22·√n` | liczba dokumentów (skala, **nie** jakość) |
| `a = 0.26·(1 − cohesion)^1.2` | nieregularność obrysu |
| `L(θ)` | wcięcia w kierunku kątowym dokumentów nieaktualnych / zalążków / izolowanych (pozycja z lokalnego layoutu) |
| `b = 0.12 + 0.28·(1 − min(coverage, freshness))` | głębokość wcięć |
| `C(θ)` | poszarpanie (wysoka częstotliwość) w kierunku dokumentów w konflikcie / duplikatów |
| `c = 0.32·(1 − consistency) + 0.16·(1 − duplication)` | amplituda poszarpania |
| wyspy | dodatkowe składowe spójne (connectivity) |
| nici (kłębek) | `chaos = 1 − (0.15·coh + 0.30·cons + 0.20·dup + 0.10·conn + 0.10·clar + 0.15·trace)`; liczba nici `2 + 30·chaos^1.4` |
| tekstura / przezroczystość granicy | freshness / (clarity + traceability) |

Klasa kształtu: `regular` (chaos < 0.2), `deformed` (< 0.4), `tangled`. Geometria jest deterministyczna
(ziarno = `stable_key`) i zawiera listę `explanations` (cecha → metryka → dokumenty → issues).

## 8. Kalibracja i walidacja

- `tests/test_topology.py` sprawdza na oznaczonym korpusie demo: zgodność klastrów z ground truth,
  kolejność jakości (Identity > Payments > Legacy), klasy kształtów, wykrycie konkretnych konfliktów,
  duplikatów i sierot, stabilność tożsamości i pozycji po przebudowie, determinizm geometrii.
- Przy realnych danych: przygotuj 50–100 pytań referencyjnych (Recall@K, MRR, nDCG) i zestaw
  ręcznie opisanych obszarów; parametry `GraphParams`/`ClusterParams` oraz progi retrieval
  (`KT_RETRIEVAL_*`) kalibruj per model embeddingów.
- Znane ograniczenia MVP: sprzeczności tylko dla twierdzeń liczbowych (negacje i warunki → etap 3 z LLM),
  embedder `hashing` nie jest semantyczny (do realnych danych użyj BGE-M3), wykrywanie konfliktów jest O(n²)
  w liczbie twierdzeń (w dużej skali → blokowanie po jednostce i terminach).
