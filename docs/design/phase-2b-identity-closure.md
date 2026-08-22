# Phase 2b — Identity Closure

**Date:** 2026-08-21
**Status:** Approved for planning
**Builds on:** the project spec (`securities-master.md`) and Phase 2a as merged
at `061b45f`

## 1. Purpose

Phase 2a placed CIK correctly — on the issuer, where it belongs — and closed a
23% coverage gap. It left two things unfinished, and both block price data.

**`security_id` is not reproducible.** `core` is derivable from `landing` (P4),
but a rebuild assigns fresh surrogate ids with no way to relate them to the old
ones. Any dependent data is orphaned. The moment Phase 2c keys daily bars to
`security_id`, a rebuild silently re-points every price at the wrong instrument.

**`security_type` is mostly a placeholder.** SEC's `entityType` separates
operating companies from everything else but cannot distinguish a fund from an
ADR, so 1,734 of 7,696 securities carry `unknown`.

Phase 2b closes both by introducing a second vendor, OpenFIGI, which supplies a
genuine security-level identifier and a real instrument classification.

## 2. Scope

**In scope:** OpenFIGI integration (landing table, adapter, rate-limited fetch
loop); a `natural_key` column on `core.security`; `figi_security_type` stored
verbatim; a derived `security_type` with real values; FIGI rows in
`core.security_identifier`; one final re-derivation of `core`.

**Out of scope, and deliberately deferred to Phase 2c:** the trading calendar,
the yfinance adapter, and `daily_bar`. Phase 2b was split from 2c because the
bar schema's design depends on identity being settled first, and a plan whose
back half is speculation produces bad tasks.

**Also out of scope:** recovering FIGIs for preferreds, warrants, and units
(see §3); any change to the issuer model.

## 3. Findings that shaped this design

Measured during design against the live OpenFIGI API and the live database, not
assumed. Several contradict what was believed when Phase 2b was first sketched.

**OpenFIGI is free, unauthenticated, and batched.** Live response headers:
`ratelimit-policy: 25;w=60` — 25 requests per minute, 10 jobs per request, so
250 mappings/minute. About 31 minutes for 7,696 securities.

**`securityType` supplies the classification SEC could not.** Observed:
`AAPL`/`GOOGL`/`GOOG` → `Common Stock`; `SPY` → `ETP`; `BABA`/`TSM`/`NVO`/`BUD`
→ `ADR`. `SHOP` → `Common Stock`, correctly, because Shopify lists directly
rather than through a depositary receipt.

**Ticker format diverges, and translation does not fix it.** SEC writes
`BRK-A`; OpenFIGI wants `BRK/A`. Measured against `core`: **541 of 7,696
tickers (7%) contain a dash; zero contain a dot.** A sample of ten dashed
tickers mapped **0/10 as written and 0/10 after dash→slash translation**, while
a control sample of ten plain alphanumeric tickers mapped **10/10**.

`BRK/A` works because it is a genuine share class. `F-PC` is Ford preferred
series C, and Bloomberg's convention for preferreds, warrants, and units is a
different naming scheme per instrument type, not a slash.

**The unmappable set is the out-of-scope set.** The dashed tickers are
preferred series (`ABR-PD`, `ACP-PA`), warrants (`ACHR-WT`), and SPAC units
(`AAC-UN`) — instruments the project spec excludes when it scopes itself to
"common stock, ETFs, and ADRs". They are peripheral in every reference-data
system, which is why their identifiers are least standardised.

**Ticker shape does not determine instrument type.** `KTWOR` is plain
alphanumeric and maps as `Right`. `securityType` catches out-of-scope
instruments that ticker shape alone would miss.

## 4. Governing decisions

**D1 — FIGI is the natural key; a namespaced composite is the fallback.**
`natural_key` is the FIGI when one exists, otherwise `cik:{cik}:{ticker}`. A
FIGI is always twelve characters beginning `BBG`, so the two forms cannot be
confused.

**D2 — a natural key delivers re-mappability, not immutability.** It does not
promise `security_id` never changes. It promises there is always a join back:
rebuild `core`, join old ids to new by `natural_key`, update dependents. That is
a migration path instead of data loss, and it is the weaker, true claim.

**D3 — vendor assertions are stored verbatim; our interpretation is derived.**
`figi_security_type` holds OpenFIGI's word unmodified. `security_type` is
derived from it. This is Phase 2a's D2 applied to a second vendor, and it means
a later phase can re-derive the classification without re-fetching.

**D4 — `securityType2` gets no column.** The full OpenFIGI response lands in
`landing.openfigi_mapping`, so P4 guarantees any additional field is derivable
later without a single re-fetch. A `core` column for it now would be YAGNI.

**D5 — out-of-scope instruments are typed, not deleted.** Preferreds, warrants,
units, and rights stay in `core` with `security_type = 'other'`. Research code
filters on type; nothing is silently discarded, and the counts are reported.

**D6 — `other` and `unknown` are different facts.** `other` means *we know what
this is and it is not cash equity*. `unknown` means *we could not find out*.
Collapsing them discards what OpenFIGI bought.

**D7 — everything lands before anything truncates.** The OpenFIGI mappings must
be durably landed before the migration empties `core`. Same hard gate as Phase
2a's D5.

## 5. Schema

### 5.1 Changed

```
core.security
  security_id         bigint GENERATED BY DEFAULT AS IDENTITY  PK   (unchanged)
  issuer_id           bigint NOT NULL REFERENCES core.issuer        (unchanged)
  natural_key         text NOT NULL UNIQUE                          -- NEW
  figi_security_type  text NULL                                     -- NEW, verbatim
  security_type       text NOT NULL                                 -- now derived
  status              text NOT NULL                                 (unchanged)
  first_seen_date     date NOT NULL                                 (unchanged)
```

The `security_type` CHECK widens to
`('common_stock', 'etf', 'adr', 'other', 'unknown')`.

`natural_key` is undated by design. It is an internal rebuild mechanism, not a
market identifier — `cik:0000320193:AAPL` is not a value anyone would hand to a
vendor.

### 5.2 Derivation

| OpenFIGI `securityType` | `security_type` |
|---|---|
| `Common Stock` | `common_stock` |
| `ETP` | `etf` |
| `ADR` | `adr` |
| anything else (`Preferred`, `Warrant`, `Right`, `Unit`, …) | `other` |
| no FIGI returned | `unknown` |

### 5.3 New landing table

```
landing.openfigi_mapping
  landing_id    bigint GENERATED BY DEFAULT AS IDENTITY  PK
  fetched_at    timestamptz NOT NULL
  payload_hash  text NOT NULL UNIQUE
  request       JSONB NOT NULL
  payload       JSONB NOT NULL
```

**The request is landed alongside the response, and this is load-bearing.**
OpenFIGI returns a positional array with no echo of what was asked, so
`[{...}, {"warning": "No identifier found."}]` is uninterpretable without the
request that produced it. Landing only the response would make `core`
underivable from `landing` — a direct P4 violation of the kind that surfaces
only when someone attempts a replay.

### 5.4 Identifiers

A mapped security gains a `core.security_identifier` row with
`id_type = 'figi'` — already legal in the existing CHECK — dated like every
other identifier, `valid_from` from the landing row's `fetched_at` date.

FIGI is stored in both `natural_key` and `security_identifier`, and the
redundancy is intentional. They are different kinds of thing that share a value
for the ~93% that map: one is an internal rebuild mechanism present on every
security, the other is a market identifier reachable through the same uniform
interface as every other identifier. Reading FIGI out of `natural_key` would
require every consumer to first determine whether that column holds a FIGI or a
fallback string — a type union hidden in a text column.

## 6. Ingestion

One adapter method, batched:

```python
OpenFigiAdapter.fetch_mapping(jobs: list[dict]) -> list[dict]
```

The fetch loop reuses the machinery Phase 2a built: run-scoped resume (never
table-scoped), exponential backoff on retryable statuses, per-CIK failure
isolation, per-chunk commits, and deadline-based pacing. Two additions:

- a request carries ten jobs, so a failed batch records all ten tickers rather
  than a count
- unmapped tickers are counted, not treated as failures — a `warning` response
  is a successful request reporting absence

Rate limiting targets 25 requests/minute. Deadline pacing matters here for the
same reason it mattered in Phase 2a: sleeping a fixed interval *after* each
request makes the achieved rate `1/(interval + latency)`, which measured 2.4×
slower than nominal on the SEC crawl.

## 7. Normalization

`normalize/exchange.py` gains a FIGI lookup and three assignments. Per included
row, in addition to Phase 2a's behaviour:

1. look up the ticker in the landed OpenFIGI mappings
2. `natural_key` = FIGI if mapped, else `cik:{cik}:{ticker}`
3. `figi_security_type` = OpenFIGI's `securityType`, verbatim, or NULL
4. `security_type` = derived per §5.2
5. insert a `figi` identifier row when mapped

`ExchangeNormalizeResult` gains `figi_mapped`, `figi_unmapped`, and a count per
derived `security_type`.

**Expected outcome:** roughly 7,155 securities mapped and ~541 unmapped, with
`unknown` falling from 1,734 to approximately the unmapped count, and the
remainder distributed across `common_stock`, `etf`, `adr`, and `other`. The
exact figures are whatever the run reports and are not predicted here.

## 8. Migration

Migration `0011`, in order:

1. `TRUNCATE core.security_identifier, core.security_listing, core.security,
   core.issuer RESTART IDENTITY CASCADE`
2. `ALTER TABLE core.security ADD COLUMN natural_key text NOT NULL UNIQUE`
3. `ALTER TABLE core.security ADD COLUMN figi_security_type text NULL`
4. Replace the `security_type` CHECK with the five-value form

`NOT NULL` without a default is possible only because step 1 emptied the table,
exactly as in `0009`. The migration is destructive and safe for one reason: P4,
pinned by the replay test in `tests/normalize/test_exchange.py`. The downgrade
is lossy — it restores the schema, not the data — and must say so.

**This is the last free rebuild.** After Phase 2c lands bars, a rebuild costs a
re-mapping pass rather than nothing.

## 9. Testing

- a mapped security's `natural_key` is its FIGI; an unmapped one's is the
  prefixed fallback; asserted together in one whole-object comparison
- the replay test extends to assert `natural_key` is **identical across
  rebuilds** — the property this phase exists to deliver, and the one Phase 2a's
  replay test structurally could not observe
- the `security_type` derivation asserted as a whole mapping, not entry by entry
- an unmapped security gets no `figi` identifier row
- a `warning` response is counted as unmapped, not as a failure
- the fetch loop run twice, pinning the run-scoped resume
- **every collection literal introduced gets one assertion of the same
  cardinality**, per the rule adopted after ten instances of tests pinning less
  than they claimed

## 10. Approximation Ledger changes

| Entry | Change | Closed by |
|---|---|---|
| `security_type` is `common_stock` for operating filers and `unknown` otherwise | **CLOSED** | Phase 2b |
| `security_id` is not reproducible across a rebuild | **CLOSED** — `natural_key` provides a join back | Phase 2b |
| ~7% of securities receive no FIGI; their fallback key breaks if that ticker is ever renamed | **NEW** | Phase 4 |
| Out-of-scope instruments (preferred, warrant, right, unit) retained and typed `other` | **NEW** | Revisit when bars reveal which have usable history |
| OTC and null-venue rows excluded | carried forward | Revisit if research needs OTC |
| Normalization is full-rebuild-only; a second run raises `UniqueViolation` | carried forward | Phase 2c |
| Seeded identifier ranges start at the landing fetch date | carried forward | Phase 4 |

## 11. Build order

| Step | Content | Done when |
|---|---|---|
| 1 | `landing.openfigi_mapping` + migration `0011a` (additive) | Table exists on both databases; re-landing unchanged data is a no-op |
| 2 | OpenFIGI adapter | Mapping parsed from a mocked batch; warnings distinguished from errors |
| 3 | Batched fetch loop | Survives interruption; a second run refetches; failures record all ten tickers |
| 4 | Real mapping run (~31 min) | All 7,696 tickers attempted; mapped and unmapped counts recorded |
| 5 | Migration `0011b` (destructive) | Both databases migrated; `core` empty |
| 6 | Normalizer changes | Natural keys assigned; derivation correct; counters reported |
| 7 | Re-seed, design note, ledger update | Counts match §7; `natural_key` stable across a replay |

**Ordering constraint:** steps 1–4 must complete before step 5. Truncating
`core` before the mappings are landed would leave an empty database and a
31-minute recovery. The migration is split additive/destructive so this is
structural rather than procedural, exactly as `0008`/`0009` were in Phase 2a.
