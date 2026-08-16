# Phase 0-1: the identity layer, explained

This document is a study guide for defending the design of `core.security` /
`core.security_identifier` in an interview. It assumes the reader knows SQL
and basic Postgres, but has not read the code. Each section answers one
question someone could reasonably push back on.

## Why `core.security` has no ticker column

`core.security` is deliberately thin:

```
security_id      bigserial PK
security_type    text
status           text
first_seen_date  date
```

No `ticker`, no `name`, nothing that changes over the life of a company. The
table exists to own one thing: a stable surrogate key that nothing else in
the system needs to know the history of.

The reason is that a ticker is not a permanent attribute of a company — it's
a temporary lease on a symbol issued by an exchange. Companies rename their
tickers on their own initiative, exchanges reassign a delisted company's old
ticker to a completely unrelated new listing, and the same company can even
carry multiple tickers at once (Alphabet trades as both `GOOGL` and `GOOG`).
If `ticker` were a column on `security`, it could hold exactly one value at a
time, which is already wrong for Alphabet, and updating it on a rename would
silently destroy the fact that the security was ever known by the old
symbol.

So identity (the row that says "this specific company/instrument exists")
and naming (the row that says "this identifier pointed at this company
during this time window") are split into two tables. `security` is identity.
`security_identifier` is naming, and it is time-ranged. Every lookup by
ticker therefore has to go through a function of `(ticker, as_of_date)`,
never a plain column equality — that function is `resolve()`.

## What `EXCLUDE ... USING gist` enforces, and why `btree_gist` is required

`security_identifier` looks like this:

```
security_id   FK -> security
id_type       text   (ticker, cusip, isin, figi, cik)
id_value      text
valid_from    date NOT NULL
valid_to      date NULL   -- NULL = still valid
```

The invariant the whole design depends on is: **for a given `(id_type,
id_value)` pair — e.g. `('ticker', 'XYZ')` — at most one row's date range may
be active on any single day.** If two different securities both claimed
`XYZ` on the same day, `resolve('XYZ', that_day)` would be ambiguous, and the
schema would have silently allowed the exact corruption P2 exists to
prevent.

A `UNIQUE` constraint can't express this, because uniqueness only compares
whole-row equality, not overlap between two date ranges on otherwise-equal
columns. What's needed is: reject an insert if there is already a row with
the same `id_type` and `id_value` whose `[valid_from, valid_to)` range
overlaps the new row's range. That's exactly what an `EXCLUDE` constraint
does — it's a generalization of `UNIQUE` that lets you specify, per column,
which comparison operator counts as a "conflict" instead of assuming `=`.

```sql
ALTER TABLE core.security_identifier
ADD CONSTRAINT security_identifier_no_overlap
EXCLUDE USING gist (
    id_type  WITH =,
    id_value WITH =,
    daterange(valid_from, valid_to, '[)') WITH &&
);
```

Read it as: two rows conflict if `id_type` is equal AND `id_value` is equal
AND their date ranges overlap (`&&`). If any new row would conflict with an
existing row under all three conditions simultaneously, Postgres raises an
`IntegrityError` at insert time. This is what turns "a reassigned ticker
should never point at two companies at once" from a code review convention
into a database-enforced fact.

`EXCLUDE` constraints require a GiST index, because GiST (Generalized Search
Tree) is the index type that knows how to efficiently answer "does this new
range overlap any existing range" — a B-tree only knows how to answer
equality and ordering questions, not overlap. Postgres ships GiST support
for range types like `daterange` out of the box, but the exclusion clause
here also needs `id_type` and `id_value` — plain text — to work as GiST
operators using ordinary equality. Text columns don't get a GiST opclass by
default; that's what the `btree_gist` extension provides. It supplies GiST
operator classes for the ordinary scalar types (text, integers, etc.) so
they can sit inside the same multi-column GiST index as a range column.
Without `CREATE EXTENSION btree_gist`, the `EXCLUDE USING gist (id_type WITH
=, id_value WITH =, ...)` clause fails at migration time — Postgres has no
GiST-compatible way to compare `id_type` or `id_value` for equality inside a
GiST index.

## Why ranges are half-open

`valid_to` is `NULL`-able, and the range constraint is built with
`daterange(valid_from, valid_to, '[)')` — square bracket on the left, meaning
`valid_from` is included; parenthesis on the right, meaning `valid_to` is
excluded. So an assignment is valid from `valid_from` up to but not
including `valid_to`.

The concrete reason: on the day a symbol changes hands, exactly one row per
day must be correct. If ranges were closed on both ends (`[valid_from,
valid_to]`), then the old owner's row covering `..., 2013-06-01]` and a new
owner's row starting `[2013-06-01, ...` would both include June 1st — an
overlap, which the exclusion constraint would reject even though this is
the single most common real-world case (a company delists and something
else gets the ticker, or a company simply migrates its own ticker to a new
symbol on a clean cutover date). Half-open ranges let the closing row's
`valid_to` equal the opening row's `valid_from` with no overlap and no gap:
the old assignment's exclusive upper bound is the new assignment's inclusive
lower bound.

This is also why the test `test_end_date_is_exclusive` pins `resolve(conn,
'XYZ', date(2013, 6, 1))` returning `None` for a security whose range ends
at `valid_to = date(2013, 6, 1)` — the boundary date belongs to whatever
comes next, not to the row being closed out.

A `NULL` `valid_to` means "no known upper bound yet" — the assignment is
still active as of today. The `_valid_on()` predicate expresses the whole
condition as `valid_from <= as_of AND (valid_to IS NULL OR valid_to >
as_of)`.

## Why CIK anchors identity instead of ticker

CIK (Central Index Key) is the identifier SEC EDGAR assigns to a filer when
it first registers. It has three properties a ticker does not:

- **Permanent.** SEC never reassigns a CIK to a different company.
- **Never recycled.** A defunct filer's CIK stays retired forever.
- **Independent of exchange listing status.** A company keeps its CIK
  whether it's listed, delisted, private, or bankrupt.

Ticker fails on all three counts — it's leased from an exchange, gets
recycled, and can change multiple times over a company's life. That makes
CIK the natural anchor for "have I seen this issuer before," which is
exactly the question `normalize_company_tickers()` has to answer on every
run to stay idempotent: it loads the set of CIKs already present, and any
incoming row whose CIK is already known is treated as already-ingested
rather than a new company.

There's a wrinkle worth naming honestly: CIK identifies an *issuer*, not a
*security*. Alphabet has one CIK and two share classes (`GOOGL`, `GOOG`).
The current schema has no `issuer` table, only `security`, and the exclusion
constraint forbids two securities from sharing the same `(id_type='cik',
id_value)` range. So today, the first ticker seen for a CIK wins and becomes
`security`; every later row for the same CIK is counted in
`skipped_duplicate_cik` rather than silently dropped or incorrectly merged
into the first security. That counter is a coverage-honesty mechanism (the
project's principle P6), not a bug — it's a deliberate, measured gap that
an `issuer` table in Phase 2 is expected to close.

## Why landing is separate from core

`landing.edgar_company_tickers` stores the raw JSON payload SEC returns,
verbatim, keyed by a hash of its content. `core.security` /
`core.security_identifier` store the normalized, constrained result of
interpreting that payload. These are two different schemas with two
different write disciplines: `landing` is append-only and never edited;
`core` is the derived system of record.

The reason for the split is that normalization logic has bugs, and those
bugs are discovered after the data has already been written — sometimes
much later, once downstream analysis surfaces something wrong. If raw
payloads were discarded after parsing, fixing a normalization bug would
mean re-fetching everything from the vendor again, which for a rate-limited
free API can mean days of throttled requests to reconstruct years of
history. Keeping the raw payload means a normalization fix can be replayed
straight from what's already on disk in Postgres — `normalize_company_tickers()`
takes a `landing_id`, not a network call.

It also means idempotency can be judged honestly at two different layers.
`land_company_tickers()` is idempotent by payload hash: if SEC republishes
the exact same file, nothing new lands. `normalize_company_tickers()` is
idempotent by CIK: if the same landing row is normalized twice, no
duplicate securities get created, because the known-CIK set is loaded fresh
from `core` on every call. Neither idempotency check needs to trust the
other, because they operate on different schemas with different guarantees.

## What the Approximation Ledger means for `resolve()` on past dates

The Approximation Ledger is a running list of known gaps between what this
phase claims and what it actually delivers, each with the phase expected to
close it. Several entries bear directly on what `resolve()` can honestly
promise about the past, as opposed to today:

- **Seeded ranges start at fetch date, not at reality.** `company_tickers.json`
  is a snapshot with no history attached — it just says "this ticker
  currently maps to this CIK," not "since when." So every identifier row
  created by the seed run has `valid_from = as_of` (the date the seed ran),
  with no way to know how far back that assignment actually goes.
  Concretely: `resolve(conn, 'AAPL', date(2015, 1, 1))` returns `None` today,
  even though Apple obviously traded as `AAPL` in 2015, because as far as
  this database currently knows, the `AAPL` -> Apple mapping only started on
  the seed date in 2026. Phase 4's EDGAR former-names and Form 25 filing
  backfill is what's expected to push `valid_from` back to the true
  assignment date.

- **Only currently-listed companies are seeded.** `company_tickers.json`
  omits anything SEC no longer considers an active filer, so delisted or
  acquired companies from the past simply don't exist in this database yet
  — another reason a query about the past can come back empty rather than
  wrong. That's Phase 4's job too.

- **Every seeded security is labeled `common_stock`.** The source JSON
  carries no instrument-type field, so ETFs and ADRs are currently
  mislabeled. That's a Phase 2 fix and separate from date-correctness.

- **Ticker reassignment onto the same CIK isn't handled yet.** If a company
  keeps its CIK but changes its own ticker, or a delisted ticker gets
  reassigned to a different CIK on a later seed run, this schema either
  raises an `IntegrityError` against the exclusion constraint or leaves the
  stale ticker row open-ended with no `valid_to`. Range close-out logic —
  actively detecting "this ticker used to point here, now it points
  elsewhere, close the old row" — doesn't exist yet. Phase 4 closes this
  too.

The unifying theme, and the answer to why this matters for `resolve()`
specifically: **the system is designed to fail closed.** Returning `None`
for a date the seed can't actually vouch for is the safe failure mode.
Returning Apple's `security_id` for 2015 just because Apple happens to be
the security *currently* mapped to `AAPL` would be worse than returning
nothing — it would assert a fact (the assignment held in 2015) that nobody
has actually verified, and a caller has no way to distinguish "verified true
for this date" from "true today and we're assuming it held historically."
An incorrect `None` is a visible gap that a caller notices and can
investigate. An incorrect `security_id` is a wrong answer that looks exactly
like a right one, and in a system whose whole purpose is preventing exactly
that class of silent corruption (see: the ticker-recycling problem this
document opened with), guessing backward from present state is not a
shortcut worth taking.
