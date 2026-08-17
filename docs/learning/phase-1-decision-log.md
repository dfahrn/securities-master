# SDD ledger — plan: docs/superpowers/plans/2026-08-16-phase-0-1-foundations-and-identity.md

Spec: docs/superpowers/specs/2026-08-16-securities-master-design.md (read)
Branch: phase-0-1-foundations-identity
Base commit: 93c7e55

## Pre-flight conflict scan

### Cross-task: shared files and interfaces

| Producer | Consumer | Produced vs consumed | Finding |
|---|---|---|---|
| T1 `Settings` | T2 `make_engine`, T3 conftest, T10 cli | `Settings(database_url, sec_user_agent)` frozen dataclass; consumers construct positionally by keyword | consistent |
| T2 `make_engine(settings)->Engine` | T3 conftest, T10 cli | same signature both sites | consistent |
| T3 `metadata`, `exchange` | T4, T5, T6 append to same file; T7 imports `metadata` | one `MetaData` spanning `core` + `landing` schemas | consistent; see R1 |
| T3 `conn` fixture | T4, T5, T6, T7, T9, T10 | function-scoped, transaction rolled back | consistent |
| T2 `tests/test_db.py` local `engine` fixture | T3 `conftest.py` session `engine` fixture | local shadows session-scoped after T3 lands | see R4 |
| T4 `security` | T5 FK, T6 FK, T9 insert, T10 test helper | `security_id` bigint identity PK | consistent |
| T5 `security_identifier` | T9 insert, T10 `resolve`/`identifiers_for` | cols `security_id,id_type,id_value,valid_from,valid_to` | consistent |
| T3 `exchange` | T6 FK `exchange_mic -> core.exchange.mic` | `mic` text PK | consistent |
| T7 `edgar_company_tickers` | T9 `land_company_tickers`, `normalize_company_tickers` | `landing_id, fetched_at, payload_hash, payload` | consistent |
| T8 `payload_hash` | T9 `land_company_tickers` | `payload_hash(Any)->str` | consistent |
| T8 `EdgarAdapter.fetch_company_tickers_payload` | T9 `land_company_tickers` | returns raw dict | consistent |
| T8 `EdgarAdapter.fetch_company_tickers` | T8 tests only | unused by T9/T10 | consistent (typed accessor, tested) |
| T9 `land_company_tickers`, `normalize_company_tickers` | T10 cli | `(conn, adapter, now)`, `(conn, landing_id, as_of)` | consistent |
| migrations 0001..0006 | chained | each `down_revision` matches predecessor | consistent |

### Per-task: internal self-agreement

| Task | Tests vs code | Files created vs later touched | Finding |
|---|---|---|---|
| 1 | 3 config tests match `Settings.from_env` raises | creates compose + `scripts/init-test-db.sql` referenced by it | see R3 |
| 2 | 3 tests match `make_engine` + migration 0001 | alembic `env.py` reads `Settings.from_env()` | consistent |
| 3 | 2 tests assert migration-seeded rows survive rollback fixture | consistent | consistent |
| 4 | 4 tests incl. `test_has_no_ticker_column` (P2) | appends to T3 file | see R1 |
| 5 | 7 tests; each `pytest.raises` is the final statement, so aborted txn never blocks a later statement | appends to T3 file | consistent |
| 6 | 3 tests match FK + check constraints | appends to T3 file | consistent |
| 7 | 2 tests match unique payload_hash | imports T3 `metadata` | consistent |
| 8 | 4 tests via `httpx.MockTransport`, no network | consistent | consistent |
| 9 | 5 tests; hardcodes `security_type="common_stock"` for every EDGAR row | consistent | see R2 |
| 10 | 6 tests match `resolve` half-open semantics | Step 6 hits real SEC network | consistent |

### Rulings made before execution

Ruling R1: `tables.py` imports are consolidated at the top of the file rather
than appended mid-file as the plan's Task 4/5/6 snippets show. — The plan's
append-style snippets are presentation shorthand, not a style mandate; mid-file
imports would be flagged by any reviewer. — Cost if wrong: none; purely
cosmetic, no behaviour change.

Ruling R2: Task 9 assigning `security_type='common_stock'` to every EDGAR row
is accepted for Phase 1, and a new Approximation Ledger entry is added to the
plan recording it, closed by Phase 2. — `company_tickers.json` carries no
instrument-type field, so classification genuinely cannot be derived here;
leaving it unrecorded would violate spec P6 (report coverage honestly). — Cost
if wrong: ETFs and ADRs carry a wrong `security_type` until Phase 2 corrects
them; no data is lost, since type is re-derivable.

Ruling R3: Task 1 implementer must verify `securities_master_test` exists after
`make up` and create it manually if absent. — Docker only runs
`/docker-entrypoint-initdb.d` scripts when initialising an empty data volume; a
pre-existing `pgdata` volume silently skips it, and every later task's tests
depend on that database. — Cost if wrong: Task 2 onward fails at fixture setup
with a confusing connection error rather than a clear one.

Ruling R4: `tests/test_db.py` keeping its own `engine` fixture after Task 3
introduces the session-scoped one in `conftest.py` is accepted. — Shadowing is
explicit and keeps Task 2 self-contained; consolidating is churn without
benefit. — Cost if wrong: one redundant engine per test in a single file.

## Progress

Ruling R2 applied to plan (Approximation Ledger entry added), commit 273bb88.
Briefs generated for tasks 1-10.
Task 1: dispatched (sonnet), BASE=273bb887f3a560831425eedfbeb39e0b637c7bf3.
Task 1: DONE_WITH_CONCERNS, commit efaf4ff. Implementer found a real plan
defect: `Settings.from_env()` calls `load_dotenv()` unconditionally, which
repopulates vars `monkeypatch.delenv()` removed, so 2 of 3 config tests fail
whenever a real `.env` exists. Correctness concern — addressed before review.

Ruling R5: `load_dotenv()` is removed from `Settings.from_env()`, making it a
pure read of `os.environ`; the side effect moves to the three entry points that
own process startup — `tests/conftest.py` (already specified in Task 3),
`migrations/env.py` (Task 2), and `cli.py` (Task 10). — A config reader that
mutates the process environment from a file as a side effect is both untestable
and surprising; the plan's own conftest already calls `load_dotenv()` at module
scope, so the plan was internally inconsistent on this point. — Cost if wrong:
if a Task 2/Task 10 entry point misses its `load_dotenv()` call, alembic or the
CLI fails with a clear "DATABASE_URL is not set" error rather than anything
silent. Carried into the Task 2 and Task 10 dispatches.
Task 1: fix applied, commit 8116b1f, 3/3 config tests pass with real `.env`.
Controller verified independently: postgres container running; both
`securities_master` and `securities_master_test` databases exist (R3 satisfied).
Task 1: review dispatched (sonnet) over 273bb88..8116b1f.
Task 1: minor (deferred): Makefile `up` runs `pg_isready` with no wait/retry
after `docker compose up -d`; flaky against a cold volume. Plan-mandated recipe,
not an implementer deviation. Surface to final review.
Task 1: complete (commits 273bb88..8116b1f, review clean, 1 minor deferred)
Task 2: dispatched (sonnet), BASE=8116b1f.
Task 2: DONE, commit eecd52d, 6/6 tests pass; migration 0001 applied to both
databases. R5 carry-forward (`load_dotenv()` in migrations/env.py) applied.
Task 2: review dispatched (sonnet) over 8116b1f..eecd52d. Approved.
Task 2: reviewer ⚠️ (migration applied to both DBs) resolved by controller —
verified directly: both `securities_master` and `securities_master_test` have
schemas core+landing, btree_gist=1, alembic_version=0001. Not a gap.
Task 2: complete (commits 8116b1f..eecd52d, review clean)
Task 3: dispatched (sonnet), BASE=eecd52d.
Task 3: DONE, commit 456c369, 8/8 tests pass, both DBs at revision 0002.
Task 3: review dispatched (sonnet) over eecd52d..456c369. Approved, no issues.
Task 3: reviewer ⚠️ resolved by controller — both DBs at revision 0002 with 3
rows in core.exchange. Not a gap.
Task 3: complete (commits eecd52d..456c369, review clean)
Task 4: dispatched (haiku — brief contains complete code, transcription task),
BASE=456c369.
Task 4: DONE, commit 2d1c2a3, 12/12 tests pass.
Task 4: review dispatched (sonnet) over 456c369..2d1c2a3, with an explicit
instruction to verify transcription fidelity given the cheaper implementer model.
Task 4: approved; transcription confirmed faithful (cheap-model gamble paid off).
Task 4: reviewer ⚠️ resolved by controller — both DBs at revision 0003;
core.security carries security_pkey, security_status_valid, security_type_valid.
Task 4: minor (deferred): `tests/core/test_security.py` imports `select` but
never uses it. Originates in plan text. No linter configured, so nothing fails
today; fold into the final review's fix wave.
Task 4: minor (deferred): `SECURITY_TYPES`/`SECURITY_STATUSES` in tables.py are
defined but unreferenced in Phase 1. See Ruling R6.

Ruling R6: The literal duplication between the `SECURITY_TYPES`/
`SECURITY_STATUSES` constants and the hardcoded SQL in migration 0003 is
deliberate and stays. Migrations must be frozen historical artifacts: if
migration 0003 imported the constant and a later phase appended
'preferred_stock' to it, replaying 0003 from scratch would build a different
schema than it originally built, and the migration history would stop being
reproducible. The same rule binds Task 5's `IDENTIFIER_TYPES`. — The constants
remain unreferenced through Phase 1 and are consumed by Phase 2 validation; the
final review may triage that as dead code. — Cost if wrong: two small constant
tuples sit unused until Phase 2, which is visible and trivially removable.
Task 5: dispatched (sonnet), BASE=2d1c2a3.
Task 5: DONE, commit da729cd, 7/7 new + 19/19 suite pass, both DBs at 0004.
Task 5: controller verified stored constraint directly:
  security_identifier_no_overlap :: EXCLUDE USING gist (id_type WITH =,
  id_value WITH =, daterange(valid_from, valid_to, '[)'::text) WITH &&)
  — correct operators, correct half-open bound. Plus identifier_range_valid,
  identifier_type_valid, PK, and FK to core.security.
Task 5: review dispatched (opus — highest-risk task of the phase) over
2d1c2a3..da729cd, with the stored constraint supplied as ground truth and an
instruction to judge each test's RED-phase reason, not just its final pass.
Task 5: review returned 2 Important + 5 Minor. Shipped constraint confirmed
correct; both Importants are test-coverage/evidence gaps in the PLAN's tests.
  I1: none of the 7 tests pins `id_value` as part of the exclusion key. A
      constraint written without `id_value WITH =` passes all seven, yet would
      forbid AAPL and MSFT from both being active tickers on the same day —
      collapsing the master to one identifier per type. Worst plausible
      mis-implementation, entirely unguarded.
  I2: RED evidence was only a collection-time ImportError, so no test was ever
      observed failing because the constraint rejected an insert.
  Minors 3-7 (deferred): IDENTIFIER_TYPES unreferenced (same class as R6);
  SQLAlchemy Table omits the CHECKs that exist in the DB (metadata never drives
  DDL — no create_all anywhere — and matches the `security` pattern); test 1
  subsumed by test 4; tests 6/7 lack `match=`; cosmetic line wrapping.

Ruling R7: An eighth test is added to `tests/core/test_security_identifier.py`,
beyond the brief's seven, pinning that two different `id_value`s under the same
`id_type` may coexist on the same day. The brief's seven stay verbatim; this is
strictly additive. — The plan's test suite is what defines the exclusion
constraint's semantics, and it left the single most destructive
mis-implementation undetectable. Shipping the phase's load-bearing invariant
with no test guarding it fails spec §10, which makes the constraint tests the
proof that the identity layer works. — Cost if wrong: one extra fast test.

Ruling R8: Finding 2's evidence gap is closed by a mutation check rather than
by re-running the original RED phase — drop the exclusion constraint on
`securities_master_test`, observe exactly which tests fail, then restore it and
verify restoration. — Re-deriving RED honestly is impossible now that the code
exists; deliberately removing the constraint and confirming the suite notices is
the stronger evidence, and it distinguishes the tests that genuinely
discriminate from pure negative controls. — Cost if wrong: the test database is
briefly without one constraint; it is fully rebuildable via `alembic upgrade`
and holds no data anything depends on.
Task 5: fix round 1/5 dispatched (resume original implementer) — I1 + I2.
Task 5: fix round 1 returned. Commit 97efc76. 8/8 file, 20/20 suite.
  Mutation check ran; constraint restored and verified identical; application
  database never touched.
  CONTROLLER PREDICTION WAS WRONG, implementer was right: I predicted test 8
  would fail under a full DROP CONSTRAINT. It cannot — test 8 asserts a
  SUCCESSFUL insert, and removing a constraint never causes a permitted insert
  to fail. Test 8 discriminates only against the narrower mutation it was
  written for (`id_value` omitted from the exclusion key), which turns that
  insert into a rejection. Observed: tests 2 and 3 fail on full drop; 6 and 7
  stay green because they are enforced by separate CHECK constraints, not the
  EXCLUDE. All correct.
  Consequence: the full-drop mutation does NOT prove test 8 does its job, so
  R7's fix is so far unverified. Requesting the targeted mutation before
  re-review — see R9.

Ruling R9: Verify test 8 by the precise mutation it was written against —
rebuild the exclusion constraint WITHOUT `id_value WITH =` on the test database
and confirm test 8 fails while the brief's seven still pass. — A test added to
close a coverage hole is worthless until something demonstrates it can fail; the
full-drop mutation was the wrong instrument for an assert-success test. — Cost
if wrong: one more short mutation cycle on a rebuildable test database.
Task 5: R9 mutation ran. Constraint rebuilt WITHOUT `id_value WITH =` →
  test 8 failed, the brief's seven all passed, test 5 unaffected. Exactly
  Finding 1 reproduced as an observation. Test 8 is proven to discriminate.
  Constraint restored; controller re-verified independently:
  EXCLUDE USING gist (id_type WITH =, id_value WITH =,
  daterange(valid_from, valid_to, '[)'::text) WITH &&). 8/8 and 20/20 green.
  No code change this cycle (DDL-only mutation), so the fix diff is the
  eighth test alone.
Task 5: scoped re-review dispatched (sonnet) over da729cd..97efc76.
Task 5: fix round 1/5 (2 addressed, 0 open — I1 eighth test added and proven
discriminating; I2 closed by two mutation cycles with per-test tables and
character-for-character restoration verification; commits da729cd..97efc76).
Task 5: complete (commits 2d1c2a3..97efc76, review clean, 5 minors deferred)
Task 6: dispatched (haiku — brief contains complete code, transcription task),
BASE=97efc76.
Task 6: DONE, commit fce4c39. Implementer reported "17/17 in tests/core
(3 new + 14 existing)" — arithmetic looks off against the running totals
(20 suite tests before this task); flagged to the reviewer to reconcile.
Controller verified both DBs at revision 0005; core.security_listing carries
listing_range_valid CHECK, PK, and both FKs (to core.security, core.exchange).
Task 6: review dispatched (sonnet) over 97efc76..fce4c39. Approved.
Task 6: test-count query resolved — tests/core holds 14 existing (4+8+2) + 3
new = 17; the other 6 (test_config 3, test_db 3) sit outside tests/core, so the
full suite is 23. Arithmetic reconciles; not a gap.
Task 6: minor (deferred): no test exercises the `security_id` FK, nor the
"currently listed" path (`valid_to IS NULL` with `delisting_reason IS NULL`)
that is central to this table's survivorship purpose. An implementation that
dropped the security_id FK entirely would pass all three brief tests; its
presence in the live DB was verified by controller ground truth, not by the
suite. Brief-mandated scope. Same class of gap as Task 5's Finding 1 — surface
to final review.
Task 6: complete (commits 97efc76..fce4c39, review clean, 1 minor deferred)
Task 7: dispatched (haiku — brief contains complete code, transcription task),
BASE=fce4c39.
Task 7: DONE, commit c0a6ad5, 25 passed (2 new + 23 existing — reconciles).
Controller verified both DBs at revision 0006; landing.edgar_company_tickers
carries PK on landing_id and UNIQUE on payload_hash (the idempotency guarantee).
Task 7: review dispatched (sonnet) over fce4c39..c0a6ad5. Approved.
Task 7: minor (deferred): report pasted only the summary line for the full-suite
run despite using `-v`, and miscounted tables.py as 15 lines vs 14. Report
documentation nits, not code defects.
Task 7: minor (deferred): no test covers NULL insertion into the NOT NULL
columns (`payload_hash`, `payload`, `fetched_at`). Brief-mandated 2-test scope.
Task 7: complete (commits fce4c39..c0a6ad5, review clean, 3 minors deferred)
Task 8: dispatched (haiku — brief contains complete code, transcription task),
BASE=c0a6ad5. First task with no database involvement; HTTP is mocked via
httpx.MockTransport, so no network call is made.
Task 8: DONE, commit 2ed4ab9, 4 new + 29 total (25 baseline + 4 — reconciles).
Task 8: review dispatched (sonnet) over c0a6ad5..2ed4ab9, with an explicit check
that the User-Agent is set on the client the adapter builds when none is
injected — the tests inject their own client, so a header set only in tests
would pass every test and still be blocked by SEC in production at Task 10.
Task 8: approved. Named risk resolved: `edgar.py` sets the User-Agent on the
client it constructs when none is injected, so the header IS sent in production.
Task 8: minor (deferred): that no-injected-client branch has zero direct test
coverage — a typo in the header key would slip through the suite. Task 10's real
SEC request is the de facto test of it; if that request succeeds, the branch is
empirically confirmed. Watch for a 403 there.
Task 8: minor (deferred): `fetch_company_tickers()` upper-cases the ticker,
a normalization step inside an adapter whose contract is "fetch only". Harmless
today because Task 9 consumes the raw `fetch_company_tickers_payload()`, but a
latent tension if anything later sources from the typed method.
Task 8: complete (commits c0a6ad5..2ed4ab9, review clean, 2 minors deferred)
Task 9: dispatched (sonnet — two modules, idempotency logic, most judgment of
any remaining task), BASE=2ed4ab9.
Task 9: DONE, commit 2b162f8, 5 new + 34 total (29 baseline + 5 — reconciles).
Task 9: review dispatched (opus — this is the pipeline's derivation logic and
the code most likely to be quietly wrong) over 2ed4ab9..2b162f8, with a specific
instruction to reason about the SECOND, CHANGED payload: a new company
appearing, or a ticker reassigned between two CIKs. That is the realistic
nightly steady state, and the brief's five tests only exercise first-run and
unchanged-rerun. If a reassignment would hit the EXCLUDE constraint and crash
the pipeline, that is a Phase 2 landmine worth knowing about now.

Task 9: review returned 4 Important + 3 Minor. Implementation matches the brief
and every controller decision exactly; all four Importants are consequences of
the BRIEF's create-or-skip algorithm, i.e. defects in my plan.
  I1: one CIK legitimately appears on several rows (GOOGL/GOOG under CIK
      1652044; BRK-A/BRK-B under 1067983) because company_tickers.json is keyed
      by ticker, not company. `known.add(cik)` skips every row after the first,
      so the real file loses several hundred tickers SILENTLY — the return value
      counts securities, so nothing reveals the loss. Not in the Approximation
      Ledger, so currently an UNRECORDED approximation, violating spec P6.
  I2: a ticker reassigned to a new CIK writes a second open-ended range for the
      same (id_type, id_value), trips the GiST EXCLUDE, and aborts the whole
      transaction — the nightly job fails wholesale, losing thousands of valid
      rows. Never executed: no test presents a second differing payload.
  I3: a ticker change on an unchanged CIK (FB→META) is skipped entirely, leaving
      valid_to=NULL on the stale ticker — an active false assertion that this
      company currently trades as FB. Same root cause: no update path.
  I4: coverage — inverting `_existing_ciks` to query id_type=="ticker" instead
      of "cik" passes all five tests, as does deleting `known.add(cik)`. Both
      controller decisions are unpinned because all five tests replay the SAME
      payload.
  Minors 5-7 (deferred): land returns `int | None` but normalize takes `int`, so
  Task 10 must guard the seam; one round trip per security (~10k) — fine for a
  nightly seed; blank/whitespace ticker unvalidated.

ROOT CAUSE, a schema-design finding rather than a coding one:
**CIK identifies an ISSUER, not a SECURITY.** Alphabet is one filer with one
CIK and two securities. By storing CIK in `security_identifier` under the
EXCLUDE constraint, the schema makes it structurally impossible for two
securities to share a CIK — so create-or-skip is not merely lazy, it is the
only thing the current schema permits. Correct modeling needs an `issuer` table
owning the CIK, with securities referencing it. Real Phase 2 work, out of scope.

Ruling R10: Phase 1 keeps one security per CIK, because the schema cannot
represent anything else without an issuer table that does not exist yet. But
the loss stops being silent: `normalize_company_tickers` returns a
`NormalizeResult(created, skipped_duplicate_cik)` instead of a bare int, and a
new Approximation Ledger row records it, closed by Phase 2. Task 10's brief is
amended to print both numbers. — Spec P6 requires the system to measure and
report its own coverage rather than imply completeness; dropping several hundred
tickers with no trace is exactly the failure P6 names, and this is the smallest
change that makes it honest without restructuring the schema mid-phase. — Cost
if wrong: one extra field on a return value and one ledger row; the alternative
is a "survivorship-bias-free" headline resting on a seed that silently lost data.

Ruling R11: I2 and I3 are deferred to Phase 4 with an Approximation Ledger row
AND a test asserting the CURRENT failure mode. — Fixing them needs range
close-out logic (set the incumbent's valid_to before inserting the successor),
the same machinery Phase 4 builds for Form 25 delistings; doing it twice is
waste. A test pinning today's behavior turns a latent crash into a documented
one and will fail loudly when Phase 4 fixes it, which is the signal we want.
Task 10 is unaffected: it seeds once against an empty core, so no reassignment
can occur. — Cost if wrong: the nightly job fails on the first payload
containing a reassignment; Phase 1 never runs nightly, so exposure is zero
until Phase 2 schedules it.

Ruling R12: I4's two discriminating tests are added — one payload with a
repeated CIK under two tickers, one second payload adding a company. — Same
class as Task 5's Finding 1: a suite that replays only one payload cannot
distinguish the controller's stated design from its inversion, so both
decisions are currently unguarded. — Cost if wrong: two fast tests.
Task 9: fix round 1/5 dispatched (resume original implementer) — R10, R11, R12.
Task 9: fix round 1 returned. Commit 886f8a3. tests/normalize 8 passed; full
suite 37 (34 + 3 new). R12's changed-payload guard surfaced nothing unexpected.
Implementer correctly left the controller's uncommitted plan-doc edit alone as
out of scope; controller committed it separately as bfb1255.
Task 9: scoped re-review dispatched (sonnet) over 2b162f8..886f8a3, with an
instruction to reason about whether each NEW test would actually fail under the
mutation it was written against — the Task 5 lesson, applied pre-emptively.
Task 9: fix round 1/5 (4 addressed, 0 open — R10 NormalizeResult counts skipped
share classes on the correct branch, five original tests touched only at the two
bare-int assertion sites; R11 deferral test genuinely reaches the exclusion
constraint rather than failing incidentally; R12 both new tests traced to fail
under their respective mutations; commits 2b162f8..886f8a3).
Task 9: complete (commits 2ed4ab9..886f8a3, review clean, 3 minors deferred)

Ruling R13: Task 10's `docs/learning/phase-1-identity.md` is written by the
implementer as a study document addressed TO the user, not "in the reader's own
words" as the plan's step 8 says. — The plan was drafted assuming the reader
writes it; the user has chosen an agent-coded workflow, so an agent writing "in
the reader's own words" would be fabricating the user's understanding rather
than transferring it. The comprehension checkpoint at the end of the phase is
where the user's own words actually belong. — Cost if wrong: the doc reads as a
reference rather than a personal summary; the user can rewrite it, and the
checkpoint still tests real understanding either way.
Task 10: dispatched (sonnet — integration, one real network call, prose),
BASE=bfb1255. This is the only task in the phase that touches the live SEC API.
Task 10: DONE, commit 3af6943. 43 tests (37 + 6 new). Live SEC request succeeded
first try — no 403, so Task 8's untested default-client User-Agent path is now
empirically confirmed. Second run idempotent.

SEED RESULT, and the headline number is far worse than estimated:
  Controller verified directly against the database —
    payload entries        10396
    distinct CIKs           7995
    securities created      7995
    cik identifiers         7995
    ticker identifiers      7995
    duplicate-CIK skips     2401
  7995 + 2401 = 10396 and securities == distinct CIKs, so the arithmetic is
  exact. **2,401 tickers — 23% of the universe — are unrepresented**, not the
  "several hundred" I estimated when writing R10. Alphabet, Berkshire, and every
  multi-class issuer keep only one ticker.
  Consequence: the `issuer` table is now the highest-priority item in Phase 2,
  not a cleanup task. Recorded with the measured figure in the plan's
  Approximation Ledger (commit 4037dde).
  This also vindicates R10: had the return stayed a bare int, this 23% gap would
  have been invisible and the phase would have closed claiming ~8k securities
  with no mention of what was dropped.
Task 10: review dispatched (opus — phase-closing task, and it ships a study
document whose technical accuracy the reader cannot yet check for themselves;
inaccuracy there is graded Important, not Minor).
Task 10: review returned Approved, 1 Important + 6 Minor. Every technical claim
in the learning doc was cross-checked against the migration, normalizer, spec
principles, and plan ledger — all hold. Code and both amendments exact.
  Important: the doc's ledger section carries 4 bullets, not 5 — it omits the
  one-security-per-CIK entry, the ONLY one with measured figures, and never
  states the consequence that `resolve("GOOG", date.today())` returns None
  TODAY, on current data. A reader would conclude the gaps are all historical
  when ~23% of tickers do not resolve in the present. P6 violation inside the
  artifact meant to teach P6. → fix round 1.
Task 10: minors (deferred, for final-review triage):
  M1: inclusive lower bound unpinned — `valid_from < as_of` instead of `<=`
      passes all six tests while making the first day of every assignment
      unresolvable. The asymmetric twin of test_end_date_is_exclusive. THIRD
      instance of this pattern (Task 5 I1, Task 9 I4, now here); the plan's
      tests repeatedly pin one side of a boundary and not the other.
  M2: `identifiers_for` date filtering unpinned — deleting `*_valid_on(as_of)`
      from it entirely still passes, since both fixtures are open-ended.
  M3: unused `select` import in test_identity.py (plan-mandated; third such).
  M4: live HTTP fetch happens inside `with engine.begin()`, holding a DB
      transaction open across the network round trip. Brief-mandated, harmless
      at this scale, worth revisiting when the seed grows.
  M5: `_valid_on` lacks a return annotation while the rest of the module has one.
  M6: report overstated the doc's ledger coverage as five bullets.
Task 10: fix round 1/5 dispatched (resume original implementer) — doc only,
no code or test changes.
Task 10: fix round 1 returned. Commit 9bead89. 43 tests unchanged (doc-only).
Task 10: scoped re-review dispatched (sonnet) over 3af6943..9bead89, with the
measured seed figures supplied as ground truth to check the new bullet against,
and an instruction that a confidently-worded NEW wrong sentence in a teaching
document is worse than the omission it replaced.
Task 10: fix round 1/5 (3 addressed, 0 open — fifth ledger bullet added with
figures matching ground truth exactly; bigserial corrected to `bigint GENERATED
BY DEFAULT AS IDENTITY`; report's own overstatement corrected transparently;
commits 3af6943..9bead89).
Task 10: minor (deferred): the fix introduced ONE new overgeneralization at
docs/learning/phase-1-identity.md:222-224 — "Every other entry in this ledger is
a historical gap … resolve() is wrong only about dates in the past, and correct
about today." False for two of the four: the `common_stock` entry is an
instrument-type labelling issue that never makes resolve() wrong, and the
ticker-reassignment entry manifests on a FUTURE re-seed and would make resolve()
wrong about TODAY. Fix: narrow "every other entry" to "the other date-related
entries". Exactly the failure mode I warned the implementer about — worth noting
that the warning did not prevent it; the re-review caught it.
Task 10: re-reviewer's "out-of-scope" note about the plan-doc edit in the fix
range is a misattribution, not implementer scope creep: commit 4037dde is the
CONTROLLER's, landed between 3af6943 and 9bead89 so it fell inside the range.
Task 10: complete (commits bfb1255..9bead89, review clean, 7 minors deferred)

=== ALL 10 TASKS COMPLETE ===
Branch phase-0-1-foundations-identity, 17 commits, 93c7e55..9bead89.
Suite: 43 tests passing. Both DBs at revision 0006. Seed populated: 7,995
securities, 7,995 ticker + 7,995 cik identifiers, 1 landing row.

FINAL REVIEW DISPATCHED (opus) over 93c7e55..9bead89, 17 commits. Carries the
12 deferred minors for triage, the 13 rulings, and an explicit ask for a
yes/no verdict on whether deferring the 23% issuer gap to Phase 2 is defensible.
FINAL REVIEW RETURNED: "Ready to merge? With fixes." 2 Critical, 6 Important,
10 Minor. Verified several claims against the live DB with read-only SELECTs.
  C1: P4 IS NOT ACTUALLY SATISFIED. `as_of` comes from the caller's wall clock
      (cli.py:25 passes datetime.now().date()), so replaying landing row 1
      tomorrow yields different valid_from/first_seen_date than the original
      run. Today's values agree only because the first run did fetch and
      normalize in one go. A rebuild is not a reproduction — and Phase 4's
      backfill rebuilds. The ledger entry "ranges open at as_of" is only a
      closable approximation if as_of IS the fetch date.
  C2: `make migrate` never migrates the TEST database — only DATABASE_URL.
      init-test-db.sql merely CREATEs it. Our test DB is at 0006 only because
      six task steps ran the ad-hoc command by hand. So the plan's own Phase
      Exit Criterion ("make up && make migrate && make test from a clean
      checkout") is FALSE today; a second contributor gets UndefinedTable.
      Plan defect propagated faithfully into the implementation.
  I1: R11 half-applied — only the LOUD bug is pinned. The quiet one (ticker
      rename on an unchanged CIK) hits the skip branch, never creates the new
      ticker, leaves the old one open-ended forever. resolve('ABC') → None and
      resolve('XYZ') → the old security: WRONG ABOUT TODAY, silently. It also
      corrupts the P6 counter, conflating "share class we cannot represent"
      with "rename we dropped". Clean today (first seed into empty core);
      stops being clean on the first re-seed, with nothing saying so.
  I2: one malformed row aborts the whole 7,995-security seed (unvalidated
      ticker → exclusion violation → full rollback). Latent now (current file
      has no blank tickers), live risk at Phase 5's messier sources.
  I3: learning doc false claim at :190-191 AND :223-224 (I had only caught :223).
  I4: the retained share class is ARBITRARY — verified live that BRK-B was kept
      and BRK-A dropped, purely by file order. Docs imply the survivor is the
      main listing. Anyone reading "the 77% we have" as primary listings is
      wrong.
  I5: both shipped public functions are regression-undetectable — flipping
      `<=` to `<` at identity.py:11 passes all 7 tests while making
      resolve('AAPL', seed_date) return None; deleting the date filter from
      identifiers_for also passes.
  I6: no index on security_identifier.security_id — identifiers_for seq-scans
      15,990 rows per call; its dict comprehension also silently collapses a
      second identifier of the same id_type.

VERDICT ON THE 23% QUESTION: defer, do not block. Reviewer's reasoning, which
I accept: Phase 1's done-when is "resolve() works; DB rejects overlaps" (both
hold) and universe coverage is Phase 5's criterion; the failure mode is None
rather than a wrong answer, so nothing is corrupted and it fails closed exactly
where the design predicted; and blocking reduces no risk, since the fix is a
schema redesign that IS Phase 2. What makes it defensible is specifically that
it was measured, printed, and the estimate publicly revised. Condition
attached: issuer-first in Phase 2 BEFORE any bar ingestion — if issuer lands
after bars are keyed to security_id, splitting Alphabet re-keys ingested bars.

Ruling R14: `identifiers_for` fails loud on a duplicate id_type at `as_of`
rather than silently collapsing via dict comprehension. — The exclusion
constraint keys on (id_type, id_value), not (security_id, id_type), so two
tickers for one security at one date is representable; silently returning one
is the same class of quiet wrongness this whole schema exists to prevent.
Verified safe against live data: every seeded security has exactly one ticker
and one cik. — Cost if wrong: a raise on data that today cannot exist.

Ruling R15: adopt the reviewer's rule — **every comparison operator gets one
test that fails if you flip it** — and apply the bounded sweep now, to all four
temporal predicates (`_valid_on`'s two clauses, the exclusion constraint's
`[)`, the `valid_to > valid_from` CHECK). ~30 lines, one sitting. — This is the
fourth recurrence of one-side-pinned boundaries; three point fixes leave the
next one undiscovered, and R7/R12 already applied this discipline elsewhere —
it simply never reached test_identity.py. — Cost if wrong: a handful of fast
tests that will look obvious in hindsight.

Ruling R16: split the P6 counter into `skipped_duplicate_cik` and
`skipped_cik_ticker_changed`. — A single counter that quietly starts meaning
two different things is how a measured gap turns back into an unmeasured one,
which would undo the exact property that made the 23% deferral defensible. —
Cost if wrong: one extra field on a dataclass.

FIX WAVE (one dispatch, per process): C1, C2, I1, I2, I3, I4, I5, I6 + R14/R15/R16.
Minors deferred per the reviewer's triage; items 1-9 and the residue of 10/12
accepted as deferred, items 11 and 12's test gaps folded into I5.
Controller TODO after the wave: fix plan drift — Task 9's Interfaces block still
declares `normalize_company_tickers(...) -> int`; R10 changed it.

FIX WAVE RETURNED: DONE_WITH_CONCERNS. 4 commits 9bead89..55b8ea0, 53 tests
(43 + 10 added, none deleted). All 8 findings fixed. Three declared deviations,
all of which look like the implementer being right:
  D1 (I1/R16): my rule as literally written would classify every extra share
      class in a FRESH seed as a "ticker change", since only a CIK's first
      ticker is ever recorded — re-creating the exact conflation R16 removes,
      and breaking a test I told them not to delete. They implemented: rename
      only when the CIK's RECORDED ticker vanishes from the payload.
  D2 (C1 replay test): my instruction said replay "passing a different explicit
      clock" — self-contradictory, since keeping the override means an explicit
      as_of MUST change the dates. They replayed with the default against a
      fetched_at far from today, and covered the override separately.
  D3 (I5 item 4): the existing inverted-range tests do NOT pin `>` vs `>=` —
      an inverted range fails under both, so only a ZERO-LENGTH range
      discriminates. They added one zero-length test per table rather than
      merely confirming. Correct, and a hole I had not seen.
Controller verified directly: both DBs at 0007; index
`security_identifier_by_security` present; live payload 10,396 rows / 7,995
distinct CIKs / 2,401 beyond-first-per-CIK — so the counter's semantics check
out. NOTE the implementer's summary mis-stated this as "10,396 duplicates";
flagged to the re-reviewer to determine whether the error is confined to the
summary or reaches the report or the code.
Fix wave: scoped re-review dispatched (opus — last gate before merge), over
9bead89..55b8ea0, asked to state the specific operator flip or deletion each of
the 10 new tests catches, and to adjudicate the three deviations on their merits.

RE-REVIEW RETURNED: All 8 findings ADDRESSED. All 3 deviations JUSTIFIED. All 10
added tests discriminate against a named mutation — none pins nothing. No test
deleted or weakened. **Merge-ready: Yes.**
  Notable: the re-reviewer traced D1's rule through four cases and found one
  imprecision — a MIXED re-seed (a rename plus a new share class on the same
  CIK) reports both rows as renames. It judged this acceptable because the rule
  degrades toward OVER-reporting the more severe gap and never toward hiding it
  in the benign counter — the P6-safe direction — and because which row is "the
  rename" is genuinely undecidable per-row without more evidence. The learning
  doc describes the implemented behavior accurately, so doc and code agree.
  Also resolved my flag on "10,396 duplicates": not an error. It is correct for
  the experiment the report describes (a re-normalize of an already-seeded
  landing row, where all 7,995 ingested + 2,401 share classes hit the skip
  branch). The 2,401 figure applies to the original seed, which is what both
  ledgers state. Paraphrase artifact, not a semantics error.

RESIDUALS ADJUDICATED (no second fix wave, per process):

Ruling R17: park the `fetched_at.date()` timezone dependency
(normalize/edgar.py:98) — real but unreachable in this deployment. `fetched_at`
is timestamptz and psycopg renders it in the session TimeZone, so a replay from
a non-UTC session could derive a different `as_of` — inside the very fix that
made P4 structural. But `postgres:16` defaults to `Etc/UTC`, docker-compose sets
no `TZ`, and live row 1's 17:15:36Z is nowhere near a date boundary. — A
one-line hardening (`fetched_at.astimezone(timezone.utc).date()`) is worth doing,
but shipping it unreviewed through the controller violates the review discipline
that produced every finding on this branch. — Cost if wrong: a replay run from a
non-UTC Postgres session on a near-midnight fetch derives dates off by one; no
such session exists in this deployment. FIRST ITEM for Phase 2's opening commit.

Ruling R18: park both learning-doc wording residuals — the stale "every later
row for the same CIK is counted in `skipped_duplicate_cik`" at :151-153, now
overbroad after the counter split, and "date-related" vs the established term
"date gaps" at :251. — Neither makes a false claim in context: :168-176 corrects
the first 15 lines later, and both the intro at :217 and the reassignment entry's
own text disambiguate the second. Editing prose in the controller session is
exactly the unreviewed-fix path this process forbids. — Cost if wrong: a reader
skimming :151 without reaching :168 carries a slightly wrong model of the
counter for 15 lines.

Ruling R19: park the plan-document drift (Task 9/10 code sketches still show
`normalize_company_tickers(...) -> int` and `as_of=now.date()`). — The plan is a
historical record of what was planned, not a description of what shipped; the
Approximation Ledger inside it IS current and is the part anything depends on.
Rewriting executed task steps to match the outcome would destroy the record of
what the rulings actually changed, which is the more valuable artifact. — Cost if
wrong: someone reads a task sketch as current API. Mitigated: the shipped
signature is in the code, the tests, and the learning doc.

=== BRANCH COMPLETE ===
21 commits, 93c7e55..55b8ea0. 53 tests passing. Both DBs at revision 0007.
Final review clean; fix wave verified; 3 residuals parked with rulings above.
Next: superpowers:finishing-a-development-branch.

(prompt archived — the final-review prompt was composed and sent from)
  .superpowers/sdd/2026-08-16-phase-0-1-foundations-and-identity/final-review-dispatch.md
Send it verbatim as Agent(subagent_type="general-purpose", model="opus").
It already carries the spec/plan pointers, the package path, all 12 deferred
minors for triage, all 13 controller rulings, and the 23% issuer question.
No further preparation is needed — one tool call resumes the workflow.

NEXT STEP (not yet started — checkpointed before dispatch):
Final whole-branch review. Package ALREADY BUILT at
  .superpowers/sdd/2026-08-16-phase-0-1-foundations-and-identity/review-93c7e55..9bead89.diff
  (17 commits, 176,956 bytes)
Dispatch on the most capable model using superpowers:requesting-code-review's
code-reviewer.md, and point it at the deferred-minor list below so it can triage
which must be fixed before merge. Then ONE fix dispatch, one scoped re-review,
then superpowers:finishing-a-development-branch.

DEFERRED MINORS ROLL-UP for the final review to triage (12 total):
  T1  Makefile `up` runs pg_isready with no wait/retry; flaky on cold volume.
  T4  unused `select` import in tests/core/test_security.py.
  T4  SECURITY_TYPES/SECURITY_STATUSES unreferenced in Phase 1 (see R6).
  T5  IDENTIFIER_TYPES unreferenced; SQLAlchemy Tables omit CHECKs present in
      the DB (harmless — metadata never drives DDL, no create_all anywhere);
      test 1 subsumed by test 4; tests 6/7 lack `match=`; cosmetic wrapping.
  T6  no test exercises the security_id FK, nor the "currently listed" path.
  T7  no test covers NULL insertion into NOT NULL landing columns.
  T8  adapter's default-client User-Agent branch has no direct test (now
      empirically confirmed by Task 10's successful live request).
  T8  fetch_company_tickers() upper-cases ticker inside a "fetch only" adapter.
  T9  land returns int|None but normalize takes int (Task 10 guards it).
  T9  one round trip per security (~10k) on seed.
  T9  blank/whitespace ticker unvalidated.
  T10 ** inclusive lower bound unpinned — `valid_from < as_of` instead of `<=`
      passes all six resolve tests while making the first day of every
      assignment unresolvable. THIRD instance of the plan pinning one side of a
      boundary and not the other (cf. Task 5 I1, Task 9 I4). Strongest
      candidate for must-fix-before-merge.
  T10 identifiers_for date filtering unpinned; unused `select` import;
      live HTTP inside engine.begin(); `_valid_on` lacks return annotation;
      the new overgeneralization noted above.
