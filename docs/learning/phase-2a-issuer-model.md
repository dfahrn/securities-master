# Phase 2a: the issuer model, explained

This document is a study guide for defending the design of `core.issuer` and
the rebuilt `core.security` / `core.security_identifier` / `core.security_listing`
in an interview. It assumes the reader has read `docs/learning/phase-1-identity.md`
and knows what Phase 1 shipped. Each section answers one question someone
could reasonably push back on, checked against the code and the real re-seed
run recorded below.

## Why CIK identifies an issuer, not a security — and what that misplacement cost

CIK (Central Index Key) is the identifier SEC assigns once, at registration,
to the legal filer. It is not assigned per class of stock. Alphabet Inc. is
one CIK, `0001652044`, and — as of the real data this phase landed — **four**
listed ticker classes under that one CIK: `GOOGL`, `GOOG`, `GOOGM`, `GOOGN`,
all on Nasdaq. Berkshire Hathaway is one CIK with two: `BRK-A` and `BRK-B`.

Phase 1's `core.security_identifier` stored CIK as just another identifier
type, under the same exclusion constraint that also governs tickers: at most
one security may claim a given `(id_type, id_value)` pair on any date. That
constraint is correct for tickers — a ticker genuinely can point at only one
company at a time. It is wrong for CIK, because a CIK genuinely *can* — and
routinely does — own more than one security. Applying a one-owner constraint
to a many-owned identifier didn't just under-count; it made the correct
representation structurally impossible. The normalizer's only legal move was
"first ticker for this CIK wins, everything else is a skip," which is why
Phase 1 measured 2,401 of 10,396 tickers (23%) unrepresented — not a bug in
that normalizer, a consequence of where CIK lived in the schema.

Phase 2a's fix is not a bigger exclusion list or a smarter tie-break. It
moves CIK off `security_identifier` entirely, onto its own table,
`core.issuer`, and gives `security` a `issuer_id` foreign key. One issuer, as
many securities as it actually has. `tests/normalize/test_exchange.py::test_one_issuer_owns_two_securities`
pins the Alphabet case directly; `test_cik_is_no_longer_a_security_identifier`
(`tests/core/test_issuer.py`) pins that the old placement is now rejected.

## Why `issuer.cik` needs no date range while tickers do

`core.issuer.cik` is a plain `UNIQUE NOT NULL` text column — no `valid_from`,
no `valid_to`, no exclusion constraint. `core.security_identifier`'s ticker
rows carry both, under a GiST exclusion constraint on overlapping date
ranges. The asymmetry is not stylistic; it follows from what each identifier
actually is.

A CIK is issued once by SEC at registration and never reassigned to a
different filer, and a retired filer's CIK is never handed to someone else.
`cik → issuer` is a function of the identifier alone — for all time, not
"as of a date." There is no query "who was CIK 0001652044 in 2015" with a
different answer than "who is it today," so a temporal column would carry a
range that never varies and never needs querying.

A ticker is not owned by a company; it's a symbol an exchange leases to
whoever it currently lists. Exchanges reclaim and reissue it — a delisted
company's old ticker becomes some unrelated new listing's ticker. So
`ticker → security` is only a function once a date is supplied; without one,
`AAPL` is ambiguous over enough history. That's why `resolve(conn, ticker,
as_of)` takes a date and `issuer.cik` lookups don't need to.

## Why the migration could safely truncate `core`

Migration `0009` opens with `TRUNCATE core.security_identifier,
core.security_listing, core.security RESTART IDENTITY CASCADE` before it even
creates `core.issuer`. That is destructive — every downstream `security_id`
gets a new value — and it is safe for exactly one reason: **`core` is fully
derivable from `landing`** (the project's principle P4). Nothing in `core` is
manually curated; every row is the output of a pure function of a `landing`
row plus the CIK-keyed submissions facts. If that property holds, truncating
`core` loses nothing that a re-run of the normalizer can't reproduce.

The property doesn't hold by assertion — it's pinned by a test. Phase 1 had
`test_normalize_replays_identically_from_landing` guarding its own
normalizer; migration `0009`'s docstring explicitly retires that test in the
same commit, because the narrowed `identifier_type_valid` CHECK and the new
`issuer_id NOT NULL` on `security` make that old normalizer's inserts illegal
against the post-migration schema. P4 is unpinned for exactly one commit:
`normalize/exchange.py`'s own
`test_normalize_replays_identically_from_landing` (`tests/normalize/test_exchange.py`)
re-pins it immediately against the new rebuild path — it lands core rows,
deletes them, re-normalizes from the same `landing_id`, and asserts the
`first_seen_date` values are identical the second time.

What would have made this migration require a backfill instead of a
truncate: anything in `core` that isn't a pure function of `landing` —
manually corrected rows, external annotations, or (starting in Phase 2b)
downstream tables like daily bars that reference `security_id` by value.
`0009`'s own design note calls this out: "nothing depends on `security_id`
yet; after Phase 2b lands bars, nothing like this is free again." This is
the last phase in this project that gets to truncate-and-rebuild for free.

## Why OTC and null-venue rows are excluded, and what was actually excluded

`normalize_company_tickers_exchange` reads `company_tickers_exchange.json`
and, per row, checks the file's `exchange` field before doing anything else:
a `None` venue is counted and skipped (`excluded_no_exchange`); the literal
string `"OTC"` is counted and skipped (`excluded_otc`); anything else not in
the known `{Nasdaq, NYSE, CBOE}` map is counted and skipped
(`excluded_unknown_venue`) rather than silently dropped or guessed at.

The real re-seed, against the file landed for this phase (10,387 rows across
the exchange values below), measured:

| venue | rows |
|---|---|
| Nasdaq | 4,355 |
| NYSE | 3,309 |
| OTC | 2,502 |
| *(null)* | 189 |
| CBOE | 32 |
| **total** | **10,387** |

`excluded_otc = 2,502`, `excluded_no_exchange = 189`, `excluded_unknown_venue
= 0` — every non-excluded row's venue string was one the normalizer already
maps. `2,502 + 189 = 2,691` rows excluded; `10,387 - 2,691 = 7,696` securities
created, which matches the run's reported `securities_created` exactly.

The reason OTC and null-venue rows are excluded rather than kept: they are
mostly illiquid shells, pink-sheet ADR duplicates, and foreign secondary
lines that would pollute a research universe meant for US listed equities.
Excluding them is not free, and it is not hidden — it's a reported number in
every run and a line in the Approximation Ledger below, revisable if a future
phase's research needs OTC coverage.

## Why `entity_type` and SIC are stored as SEC's assertions, and `security_type` is derived

`core.issuer.entity_type`, `sic_code`, and `sic_description` are written
verbatim from SEC's submissions payload for that CIK — whatever SEC asserts
is stored as-is, including a blank SIC being stored as SQL `NULL` rather than
an empty string (`_blank_to_none`, pinned by
`test_empty_sic_is_stored_as_null`). Nothing on `issuer` is inferred.

`core.security.security_type`, by contrast, is never taken from any single
source field — it's computed: `"common_stock"` when that CIK's `entity_type
== "operating"`, `"unknown"` otherwise
(`test_entity_type_drives_security_type`). This split matters because SEC's
`entityType` doesn't actually distinguish a fund from a foreign private
issuer — the design's measurement during Phase 2a found Apple `operating`,
SPDR S&P 500 ETF Trust `other`, Alibaba's ADR also `other`. A single `other`
bucket covers both an ETF and an ADR, so it can separate operating companies
from everything-else, but cannot itself tell an ETF from an ADR. Storing
`entity_type` verbatim keeps that raw signal available for whatever finer
classification a later phase builds; deriving `security_type` from it today
means the derivation can be revised later — mapping `other` to `etf` or `adr`
once a richer source exists — without re-fetching anything from SEC, only
re-running the derivation against data already in `landing`.

The real run: `5,962` securities classified `common_stock`, `1,734`
classified `unknown` (verified directly against `core.security` after the
re-seed). SPY is among the `1,734`: its `entity_type` is `other`, so it is
honestly `unknown` rather than the `common_stock` label Phase 1 gave it.

## Why a filer with no submissions payload gets NULLs and `unknown`, not a guess

Submissions are fetched per CIK in a separate, resumable job (§6 of the
design spec), and a CIK's fetch can fail and exhaust retries. When that
happens, that CIK has no row in `landing.edgar_submissions` by the time
normalization runs. `_submissions_facts` builds its `{cik: (entity_type,
sic_code, sic_description)}` map from whatever landed; a CIK absent from
that map gets `(None, None, None)` on `issuer`, and since `entity_type` is
`None`, the derived `security_type` falls out of the same `common_stock` /
`unknown` branch as `other` — it becomes `unknown`. The CIK is also added to
a `missing_ciks` set, surfaced as `missing_submissions` in the run's printed
counters. `test_a_missing_submissions_payload_yields_nulls_and_unknown`
pins exactly this: entity_type and sic_code both `None` on `issuer`, and
`security_type == "unknown"` on the resulting security — never a guess drawn
from the filer's name or ticker.

On the real re-seed, `missing_submissions = 0`: every CIK that ended up
owning at least one included security had a landed submissions payload.
`landing.edgar_submissions` holds 7,994 rows against the 6,072 issuers this
run created, so submissions coverage was complete for the CIKs that mattered
to this normalization pass. (The gap between 7,994 landed submissions rows
and 6,072 issuers is unsurprising and not itself a problem: many landed
submissions rows belong to CIKs whose only ticker rows were OTC or
null-venue and so never became an issuer at all — coverage of the file's
CIKs, not of this run's issuers, is what that 7,994 figure measures.)

## What the cross-source ticker disagreement count means, and why normalization reads one source anyway

SEC exposes a filer's tickers in two independent places: the row(s) in
`company_tickers_exchange.json`, and the `tickers` array inside that CIK's
own `submissions` payload. `ticker_disagreements()` compares the two, per
CIK, and reports any ticker present in one but not the other. On the real
landed data this measured **646** CIKs with at least one disagreement — this
is the exact number the re-seed printed as `CIKs where SEC's two sources
disagree: 646`.

Two concrete, real examples from that run:

- **Mid-America Apartment Communities** (CIK `0000912595`): the exchange
  file lists `MAA` and `MAA-PI` on NYSE; its submissions payload additionally
  lists `MAAI`, a ticker that appears in no row of the exchange file for that
  CIK.
- **Canon Inc.** (CIK `0000016988`, OTC-venue and therefore excluded from
  `core` entirely): the exchange file lists both `CAJPY` and `CAJFF`;
  submissions lists only `CAJPY`.

The design spec's Section 3 cited Alphabet's own submissions/exchange-file
split (submissions `GOOGL, GOOG, GOOGM, GOOGN` vs. an exchange file that
listed only two) as the motivating example, measured during design. Checked
against the payload this phase actually landed, that specific disagreement
has closed on its own — the exchange file now carries all four Alphabet
tickers, matching submissions exactly, and `ticker_disagreements()` reports
no entry for CIK `0001652044` in this run. This is worth stating plainly
rather than silently repeating a stale example: SEC's own data changes
between when a design is written and when it's re-seeded, and the two
Canon/MAA cases above are the disagreements actually present in the landed
payload this task ran against, not the ones cited when the design was
written.

Normalization reads `company_tickers_exchange.json` only — never
`submissions.tickers` — because the exchange file is the source that also
carries the venue field every exclusion and listing decision depends on;
mixing in tickers from a second source with no venue attached would mean
inventing a venue for them. The disagreement count is not resolved by this
phase; it's measured and reported so the gap is visible, and reading one
source consistently means every `security_id` this phase creates is
reproducible from that one source, which is what the replay test above
depends on. Reconciling the two sources is explicitly deferred — see the
Approximation Ledger, closed by Phase 3.

## The real re-seed run

Against the landed `company_tickers_exchange.json` payload (10,387 rows,
venue distribution in the table above), `python -m securities_master.cli
seed-phase2a` printed:

```
Normalized landing row 1:
  issuers created           6072
  securities created        7696
  excluded (OTC)            2502
  excluded (no venue)       189
  excluded (unknown venue)  0
  skipped (blank ticker)    0
  issuers missing SEC facts 0
  CIKs where SEC's two sources disagree: 646
```

Verified independently against `core` after the run: `6,072` issuers,
`7,696` securities, `7,696` ticker identifiers, `7,696` listings (one each —
every included row produces exactly one of each), `893` issuers own more
than one security (Alphabet among them, with four), `5,962` securities
`common_stock`, `1,734` `unknown`.

`resolve()` and `issuer_for()` confirm the case this phase exists for:
`GOOGL` and `GOOG` resolve to different `security_id`s (`3` and `6026`)
under the same issuer, `Alphabet Inc.`; `BRK-A` and `BRK-B` resolve to
different `security_id`s (`6028` and `10`) under the same issuer,
`BERKSHIRE HATHAWAY INC`. All four were unresolvable or wrong under Phase
1's one-security-per-CIK schema.

## The Approximation Ledger, updated

Entries carried forward from Phase 1 keep the phase that originally closed
them.

| Approximation | Introduced | Closed by |
|---|---|---|
| ~~One security per CIK; 2,401 tickers (23%) unrepresented~~ | Phase 1 | **CLOSED — Phase 2a** |
| ~~Retained share class is vendor-file order (BRK-B kept, BRK-A dropped)~~ | Phase 1 | **CLOSED — Phase 2a** |
| `security_type` is `common_stock` only for `entityType == 'operating'`; every other filer is `unknown`, because SEC's `entityType` cannot separate a fund from an ADR | Phase 2a | Phase 5 (richer vendor) |
| OTC and null-venue rows excluded — measured: 2,502 OTC + 189 null-venue = 2,691 of 10,387 rows (25.9%) | Phase 2a | Revisit if research needs OTC coverage |
| NYSE American cannot be distinguished from NYSE; the file has no such column | Phase 2a | Phase 4 |
| SEC's submissions and ticker file disagree on some filers' tickers — measured: 646 CIKs; normalization reads the exchange file only | Phase 2a | Phase 3 |
| Issuers whose submissions fetch failed carry NULL SEC facts and `unknown` securities — measured: 0 in this run | Phase 2a | Re-run `scripts/land_phase2a.py` |
| Seeded ticker ranges start at the landing fetch date; earlier history unknown | Phase 1 | Phase 4 |
| Only currently-listed companies are seeded | Phase 1 | Phase 4 |
| Ticker rename on a known CIK leaves the stale range open; reassignment to a new CIK raises | Phase 1 | Phase 4 |
| Blank-ticker rows create the security but no ticker identifier — measured: 0 in this run | Phase 1 | Phase 4 |
| `core.exchange` seeded with four MICs (`XNYS`, `XNAS`, `BATS`, plus Phase 1's set less `ARCX`) | Phase 2a | Phase 2b |

No claim above generalizes beyond what was actually measured this run: the
missing-submissions and blank-ticker rows both happened to be `0` for this
particular landed payload, which is a fact about this run's data, not a
guarantee the counters can never be positive on a future re-seed.
