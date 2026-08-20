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
deletes them, re-normalizes from the same `landing_id`, and asserts an
ordered projection of every derived fact — `(cik, name, entity_type,
sic_code, security_type, ticker, exchange_mic, valid_from)` across all four
`core` tables — is identical the second time. Its first version compared
`first_seen_date` alone, which is the same constant for every row: deleting
the issuer-facts join, the MIC mapping, and every ticker write would not have
moved it. A property claimed in three documents deserves an assertion that
can tell a correct rebuild from an empty one with the right dates.

What would have made this migration require a backfill instead of a
truncate: anything in `core` that isn't a pure function of `landing` —
manually corrected rows, external annotations, or (starting in Phase 2b)
downstream tables like daily bars that reference `security_id` by value.
The design spec (§4, D6) names this directly: "nothing depends on
`security_id` yet; after Phase 2b lands bars, nothing like this is free
again." This is the last phase in this project that gets to
truncate-and-rebuild for free.

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
`7,696` securities, `7,696` ticker identifiers, `7,696` listings. On this
run, every included row produced exactly one security, one listing, and one
ticker identifier — but that 1:1:1 shape is a fact about this payload, not a
guarantee of the normalizer: `skipped_blank_ticker` was `0` here, and the
code path exists (`normalize/exchange.py`) for a row with a blank ticker to
create its `security` and `security_listing` rows with no matching
`security_identifier` at all, which would break the count-for-count parity
without touching `securities_created` or `listings`. `893` issuers own more
than one security (Alphabet among them, with four); `5,962` securities are
`common_stock`, `1,734` are `unknown`.

`resolve()` and `issuer_for()` confirm the case this phase exists for —
**using `as_of = date(2026, 8, 20)`, the UTC date the landing row was
fetched, not `date.today()`**: `GOOGL` and `GOOG` resolve to different
`security_id`s (`3` and `6026`) under the same issuer, `Alphabet Inc.`;
`BRK-A` and `BRK-B` resolve to different `security_id`s (`6028` and `10`)
under the same issuer, `BERKSHIRE HATHAWAY INC`. All four were unresolvable
or wrong under Phase 1's one-security-per-CIK schema.

**The `date.today()` trap.** `as_of` for every identifier this run wrote
comes from `fetched_at.date()`, and `fetched_at` is stored as a UTC-aware
timestamp — so `valid_from` for every ticker and listing seeded this run is
the **UTC** calendar date of the fetch, `2026-08-20`. `date.today()` returns
the **local** calendar date. On the host this re-seed ran on, local time was
still `2026-08-19` when UTC had already rolled over to `2026-08-20` —
several hours of the day where the two dates disagree. Calling
`resolve(conn, "GOOGL", date.today())` during that window returns `None`,
and not just for GOOGL: every one of GOOGL, GOOG, GOOGM, BRK-A, BRK-B, SPY,
and AAPL comes back unresolved, because `_valid_on()`'s `valid_from <= as_of`
rejects all of them at once. This is `resolve()` doing exactly what it's
built to do — refuse to vouch for a date it has no data for — but a reader
who runs the snippet above with `date.today()` in place of the explicit date,
at the wrong hour, will see seven `None`s and reasonably suspect the re-seed
failed rather than suspect the clock. Research code that calls `resolve()`
against freshly-seeded data should anchor `as_of` to UTC
(`datetime.now(timezone.utc).date()`), not to local `date.today()`, for
exactly this reason.

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
| A ticker that moves between CIKs, or is renamed, is not tracked over time: each rebuild opens ranges at the current fetch date and closes none, because the shipped normalizer is rebuild-only and has no rename path | Phase 2a | Phase 4 |
| `normalize_company_tickers_exchange` is REBUILD-ONLY: it always inserts, so a second run against a populated `core` raises `UniqueViolation` on `issuer.cik`. A re-seed must truncate first | Phase 2a | Phase 2b (incremental normalization) |
| Blank-ticker rows create the security but no ticker identifier — measured: 0 in this run | Phase 1 | Phase 4 |
| `core.exchange` seeded with three MICs (`BATS`, `XNAS`, `XNYS`) — verified against the live table; Phase 1's `ARCX` was deleted by migration 0009 | Phase 2a | Phase 2b |
| A ticker claimed by more than one included row is dropped for BOTH claimants and counted as `skipped_duplicate_ticker`; nothing in the file says which filer owns it — measured: 0 in this run | Phase 2a | Phase 3 |

No claim above generalizes beyond what was actually measured this run: the
missing-submissions and blank-ticker rows both happened to be `0` for this
particular landed payload, which is a fact about this run's data, not a
guarantee the counters can never be positive on a future re-seed.
