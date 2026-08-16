# Securities Master Database — Design

**Date:** 2026-08-16
**Status:** Approved for planning

## 1. Purpose and context

A securities master for US cash equities, built to support quant research and
backtesting. It is also a portfolio project intended to demonstrate competence
in financial data modeling for quant internship applications.

That second purpose is not decoration. It sets a bar: every non-obvious design
decision must be explainable and defensible, and the system must make its own
correctness visible rather than merely claimed.

Three properties drive the design:

- **Survivorship-bias freedom.** Delisted companies are present, with delisting
  dates. A universe query for a past date returns what existed then.
- **Point-in-time correctness.** The system can answer what was knowable on a
  given date, not only what is known now.
- **Corporate action correctness.** Splits and dividends are modeled as events,
  and price adjustment is derived from them rather than trusted from a vendor.

## 2. Scope

**In scope:** US-listed cash equities — common stock, ETFs, and ADRs — on NYSE,
Nasdaq, and NYSE American. Daily end-of-day OHLCV. Corporate actions. Entity
identity and identifier history. Point-in-time universes.

**Out of scope:** intraday and tick data; derivatives, futures, options, FX,
crypto; non-US listings; real-time streaming; fundamentals beyond what identity
and universe construction require; order management or execution.

**Deferred but designed for:** paid vendors (Polygon, Tiingo) behind the same
adapter interface; additional asset classes reusing the identity layer.

## 3. Governing principles

These constrain everything below.

**P1 — Never store adjusted prices as the source of truth.** Store raw OHLCV as
traded, plus corporate actions. Derive adjustment factors on read. Adjusted
prices are a function of observation date; storing them as truth means every new
corporate action silently invalidates history with no way to detect it.

**P2 — Identifiers are time-ranged relationships, not columns.** No `ticker`
column on the security table. Ticker resolution is a function of
`(ticker, as_of_date) -> security_id`. Tickers are reassigned to unrelated
companies after delisting; a ticker column produces silently corrupt joins.

**P3 — Ticker is a lookup key, never a join key.** Research code carries
`security_id`. Tickers appear only at human-facing edges.

**P4 — `core` must be fully derivable from `landing`.** No hand-edited fixes in
`core`. Corrections enter as sourced records in `landing` so a rebuild
reproduces them. This is what makes the pipeline reproducible.

**P5 — Derived artifacts are caches, never sources of truth.** Parquet panels
may contain adjusted prices because they are rebuilt from `core` and stamped
with the `as_of` they were built under. This does not contradict P1.

**P6 — Report coverage honestly.** Free-tier data will be incomplete. The system
measures and reports its own coverage rather than implying completeness.

## 4. Architecture

One-directional flow:

```
vendor -> ingest/ -> landing (Postgres) -> core (Postgres) -> Parquet -> client/ -> research/
```

| Component | Responsibility | Must not |
|---|---|---|
| `ingest/` | Fetch raw vendor records; attach vendor, fetch timestamp, payload hash | Normalize, clean, or interpret |
| `landing` schema | Append-only storage of raw vendor payloads | Be edited or deleted |
| `core` schema | Normalized, constrained system of record | Contain anything not derivable from `landing` |
| `transform/` | Adjustment engine, PIT universe logic, Parquet materialization | Write to `core` |
| `quality/` | Validation rules, per-run reports | Mutate data |
| `client/` | Read-only Python API over DuckDB + Parquet | Write anything |

**Why landing is separate from core (ELT, not ETL):** normalization bugs are
discovered late. Replaying from `landing` avoids re-downloading years of data
through rate-limited free APIs, and keeps competing vendor claims visible
side-by-side for reconciliation.

**Storage split (Postgres + DuckDB/Parquet):** Postgres is the system of record —
it provides foreign keys, exclusion constraints, and transactional writes that
the identity layer genuinely requires. DuckDB over Parquet is the research read
path, because row-store scans are too slow for wide analytical pulls
(~15M rows for 20 years x 3,000 tickers).

## 5. Data model

### 5.1 Identity

```
security
  security_id      bigserial PK
  security_type    enum(common_stock, etf, adr, ...)
  status           enum(active, delisted)
  first_seen_date  date

security_identifier
  security_id   FK -> security
  id_type       enum(ticker, cusip, isin, figi, cik)
  id_value      text
  valid_from    date NOT NULL
  valid_to      date NULL          -- NULL = currently valid
```

`security` deliberately holds no mutable attributes. It exists to own a stable
surrogate key.

`security_identifier` carries an `EXCLUDE` constraint using `daterange` and
GiST, preventing the same `(id_type, id_value)` from mapping to two securities
on overlapping dates. The database, not application code, enforces P2.

CIK is the anchor identifier: SEC-assigned, permanent, never recycled.

### 5.2 Reference

```
exchange                  mic PK, name, country, timezone
security_listing          security_id, exchange_id, valid_from, valid_to,
                          delisting_reason
security_profile_history  security_id, name, sector, shares_outstanding,
                          valid_from, valid_to
trading_calendar          exchange_id, trade_date, is_open
```

`trading_calendar` is required, not optional: it is the only way to distinguish
a missing bar from a market holiday.

### 5.3 Corporate actions

```
corporate_action
  security_id        FK
  action_type        enum(split, cash_dividend, spinoff, merger, symbol_change)
  ex_date            date
  announcement_date  date
  ratio              numeric NULL
  cash_amount        numeric NULL
  vendor             text
  ingested_at        timestamptz
  superseded_at      timestamptz NULL
```

`announcement_date` is the point-in-time hook: a backtest positioned on
2020-07-15 must not see a split announced 2020-07-30.

`ingested_at` / `superseded_at` give transaction-time history where restatements
actually occur.

### 5.4 Prices

```
daily_bar
  security_id   FK
  trade_date    date
  vendor_id     FK
  open, high, low, close   numeric
  volume                   bigint
  ingested_at              timestamptz
  PRIMARY KEY (security_id, trade_date, vendor_id)
```

Keyed by vendor so disagreements are representable and measurable. Partitioned
by year on `trade_date`.

### 5.5 Universe

```
index_membership  index_id, security_id, valid_from, valid_to
```

Supports point-in-time index universes (e.g. S&P 500 constituents as of a date).

### 5.6 Bitemporality scope

Full bitemporal modeling everywhere is rejected as disproportionate. Applied
selectively:

- **Valid-time ranges:** identity, listings, profiles, index membership
- **Transaction-time:** corporate actions, where restatement genuinely happens
- **`ingested_at` only:** daily bars, sufficient to detect silent vendor revision

## 6. Ingestion

**Adapter interface:** `fetch_bars`, `fetch_actions`, `fetch_listings`. Each
returns raw records tagged with vendor and timestamp. Adding a paid vendor is
one class, no schema change.

**Sources:**

| Source | Provides |
|---|---|
| SEC EDGAR submissions API | Entity universe incl. defunct companies; CIK; CIK↔ticker |
| SEC Form 25 / 25-NSE | Delisting dates and reasons |
| yfinance | Daily OHLCV; splits and dividends |
| Wikipedia S&P 500 change history | Point-in-time index membership |
| `exchange_calendars` | Trading calendars |

**Known limitation:** free-tier coverage of thinly-traded delisted names is
incomplete. Per P6, the system measures coverage against expected universe
counts and reports a completeness percentage rather than implying completeness.

**Ingestion properties:** rate-limited, retried with exponential backoff, and
idempotent — re-running an unchanged window must produce no changes.

## 7. Adjustment engine

Given raw bars plus corporate actions, compute a cumulative adjustment factor at
read time, as of a specified date.

- **Split-only adjustment** — price continuity across splits
- **Total-return adjustment** — splits plus reinvested dividends; the default
  for backtesting

Split-only series systematically understate returns by approximately the
dividend yield, compounding across a backtest. Both variants are exposed and the
distinction is documented at the API surface.

Correctness is established by golden tests against hand-verified fixtures
(Apple 4:1 in 2020, NVIDIA 10:1 in 2024), not by trusting vendor-adjusted
fields.

## 8. Research layer

**Materialization:** `transform` reads `core` and writes Parquet partitioned by
year, containing `security_id`, `trade_date`, raw OHLCV, and precomputed
adjusted columns, stamped with the build `as_of`. Any new corporate action
triggers a rebuild of affected partitions.

**Client API** (read-only, deliberately small):

```python
sm.resolve(ticker, as_of)                 -> security_id
sm.universe(as_of, index="SP500")         -> list[security_id]
sm.get_prices(ids, start, end,
              adjustment="total_return")  -> DataFrame
sm.actions(ids, start, end)               -> DataFrame
```

There is intentionally no `get_prices("AAPL")`. Resolution is a separate
explicit call, so P3 is enforced by the API shape rather than by convention.

**Performance target:** 20 years of daily closes for ~3,000 securities returns
in under one second.

## 9. Data quality

Run on every pipeline execution, results persisted per run so quality is trended
rather than merely checked:

- Missing bars, evaluated against `trading_calendar`
- OHLC integrity: `low <= open, close <= high`; non-negative volume
- Unexplained price jumps: `|log return| > 0.4` without a matching corporate
  action on that date — catches both bad ticks and missed actions
- Cross-vendor disagreement beyond tolerance
- Universe coverage vs. expected counts
- Staleness: most recent bar older than the last open trading day

Output is a rendered report plus a persisted summary row per run.

## 10. Testing strategy

- **Golden tests** on adjustment math against hand-computed fixtures
- **Constraint tests** asserting the database rejects overlapping identifier
  ranges
- **Point-in-time test** asserting the universe as of mid-2008 contains Lehman
  Brothers — a single test proving the survivorship machinery works
- **Idempotency tests** asserting a repeated ingestion run produces no changes
- **Property tests** on adjusted-series continuity across action dates

## 11. Deliverables

1. Survivorship-bias demonstration notebook: identical momentum strategy run on
   a survivor-only universe and a point-in-time universe, with the performance
   gap quantified and charted.
2. Data quality report, generated per pipeline run.
3. Python client library.

Excluded: REST API service — lower relevance for quant research roles than the
research-facing artifacts.

## 12. Build phases

Each phase ends with working software, a learning note in `docs/learning/`, and
a comprehension checkpoint.

| Phase | Content | Done when |
|---|---|---|
| 0 | Repo, `uv`, Docker Compose Postgres, Alembic, pytest | One command yields a running, migrated, empty database |
| 1 | Identity core; SEC EDGAR seed | `resolve()` works; DB provably rejects overlapping ranges |
| 2 | Calendar, landing schema, yfinance adapter, normalization (~100 names) | Real bars in `core`; gaps distinguishable from holidays |
| 3 | Corporate actions; adjustment engine | Golden tests pass on hand-verified numbers |
| 4 | Form 25 delistings; PIT universe; coverage measurement | Lehman test passes; coverage reported |
| 5 | Full-universe backfill; rate limiting, retry, idempotency | Full DB populated; re-run is a no-op |
| 6 | Parquet materialization; DuckDB path; client library | Performance target met |
| 7 | Data quality suite and report | Report runs clean; quality trended |
| 8 | Survivorship-bias demo notebook | Bias gap quantified and charted |

**Ordering constraint:** Phase 3 precedes Phase 5 deliberately. Adjustment bugs
are cheap to fix against 100 securities and expensive against 18,000 downloaded
through a rate-limited API. Expensive, hard-to-reverse steps follow proof of
correctness.

## 13. Technology

Python 3.12; `uv` for dependency management; PostgreSQL 16 in Docker Compose;
Alembic for migrations; SQLAlchemy Core; DuckDB and Parquet for the research
path; pandas at the client surface; pytest; `exchange_calendars`.

## 14. Working agreement

Implementation is performed by coding agents. Before each phase, the concept and
the decision at stake are explained; after each phase, a learning note is
committed and a comprehension checkpoint is posed. The objective is that every
design decision recorded here can be defended without reference to this
document.
