# securities-master

A securities master database for US cash equities, built to support
quantitative research and backtesting. It exists to answer questions like
"what did ticker `XYZ` refer to on 2013-06-01" and "which securities existed
on that date" correctly, including for companies that have since been
delisted, renamed, or recycled their ticker.

Three properties drive the design:

- **Survivorship-bias freedom.** Delisted companies stay in the database with
  their delisting dates.
- **Point-in-time correctness.** The system answers what was knowable on a
  given date, not only what is known now.
- **Corporate action correctness.** Splits and dividends are modeled as events
  and price adjustment is derived from them, never trusted from a vendor.

## Status

| Phase | Content | State |
|---|---|---|
| 0 | Repo, `uv`, Docker Compose Postgres, Alembic, pytest | done |
| 1 | Landing schema, identity core, SEC EDGAR seed, `resolve()` | done |
| 2a | Issuer model, exchange listings, SEC submissions crawl | done |
| 2b | Identity closure via OpenFIGI: natural keys and real instrument types | designed, not built |
| 2c | Trading calendar, yfinance adapter, daily bars | not started |
| 3–8 | Corporate actions, delistings, backfill, Parquet/DuckDB client, quality suite, survivorship demo | not started |

The live database currently holds 6,072 issuers and 7,696 listed securities
derived from SEC EDGAR. Every known gap between what the schema claims and
what the data delivers is recorded in the Approximation Ledger at the end of
[docs/notes/phase-2a-issuer-model.md](docs/notes/phase-2a-issuer-model.md),
with the phase expected to close it.

## Design in one paragraph

Identifiers are time-ranged relationships, not columns. `core.security` has no
ticker; `core.security_identifier` maps `(id_type, id_value)` to a security
over a half-open date range, and a GiST exclusion constraint makes it
impossible for one ticker to point at two securities on the same day. CIK
lives on `core.issuer`, because SEC assigns it to a filer, not to a share
class. Raw vendor payloads land verbatim in the `landing` schema and `core`
is a pure function of them, so any normalization bug can be fixed by replay
rather than by re-downloading through a rate-limited API. Every run reports
what it excluded and why.

The full rationale is in [docs/design/securities-master.md](docs/design/securities-master.md).
Per-phase designs and explanatory notes:

- [docs/design/phase-2a-issuer-model.md](docs/design/phase-2a-issuer-model.md)
- [docs/design/phase-2b-identity-closure.md](docs/design/phase-2b-identity-closure.md)
- [docs/notes/phase-1-identity.md](docs/notes/phase-1-identity.md)
- [docs/notes/phase-2a-issuer-model.md](docs/notes/phase-2a-issuer-model.md)

## Layout

```
src/securities_master/
  core/        table definitions and resolve() / issuer_for() lookups
  landing/     append-only raw payload tables
  ingest/      SEC EDGAR adapter, landing writers, rate-limited fetch loop
  normalize/   landing -> core derivation
  quality/     cross-source reconciliation
  cli.py       seed-phase2a
migrations/    Alembic revisions 0001..0010
scripts/       land_phase2a.py, the long-running EDGAR bootstrap
tests/         100 tests, run against a real Postgres test database
```

## Running it

Requirements: Python 3.12, `uv`, Docker.

```bash
cp .env.example .env    # set SEC_USER_AGENT to your name and email
make up                 # start Postgres on localhost:5433
make migrate            # migrate the application and test databases
make test
```

To populate `core` from SEC EDGAR (the submissions crawl takes about 40
minutes at 8 requests per second and is resumable):

```bash
uv run python scripts/land_phase2a.py
uv run python -m securities_master.cli seed-phase2a
```

The seed prints its own coverage counts. Look at them.
