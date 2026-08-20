# SDD ledger — plan: docs/superpowers/plans/2026-08-19-phase-2a-issuer-model.md

Spec: docs/superpowers/specs/2026-08-19-phase-2a-issuer-model-design.md (read)
Branch: phase-2a-issuer-model
Base commit: f2e4b34

## Pre-flight conflict scan

### Cross-task: shared files and interfaces

| Producer | Consumer | Produced vs consumed | Finding |
|---|---|---|---|
| T1 `edgar_company_tickers_exchange` | T3 land, T7 normalize, T8 reconcile, T9 cli | `landing_id, fetched_at, payload_hash, payload` | consistent |
| T1 `edgar_submissions` | T4 loop, T7 `_submissions_facts`, T8 reconcile | `cik, fetched_at, payload_hash, payload`; unique `(cik, payload_hash)` | consistent |
| T2 `fetch_company_tickers_exchange_payload()` | T3 `land_company_tickers_exchange` | `-> dict` | consistent |
| T2 `fetch_submissions_payload(cik)` | T4 `_fetch_with_retry` | `(str) -> dict` | consistent |
| T3 `land_company_tickers_exchange(conn, adapter, now)` | T5 script | script calls `now=run_started` | consistent |
| T4 `land_submissions(conn, adapter, ciks, run_started, *, ...)` | T5 script | script calls positionally per chunk | consistent |
| T4 `SubmissionsRunResult` | T5 script | `landed, unchanged, skipped_this_run, failed, failed_ciks` all read | consistent |
| T6 `issuer`, `security.issuer_id` | T7 normalize, T8 `issuer_for` | FK `core.security.issuer_id -> core.issuer.issuer_id` | consistent |
| T6 `SECURITY_TYPES`, `IDENTIFIER_TYPES` | T6 tests, T7 normalize | `'unknown'` added; `'cik'` dropped | consistent |
| T7 `normalize_company_tickers_exchange(conn, landing_id, as_of=None)` | T9 cli | cli calls `(conn, landing_id)` | consistent |
| T7 `ExchangeNormalizeResult` (7 fields) | T9 cli | cli prints all 7 | consistent |
| T8 `ticker_disagreements(conn, landing_id)` | T9 cli | `len(...)` only | consistent |
| T8 `Issuer`, `issuer_for(conn, security_id)` | T9 Step 6 verification | `.name` read | consistent |
| migrations 0008, 0009 | chained | `down_revision` 0007 then 0008 | consistent |
| T6 retirement of `normalize/edgar.py` | T9 cli rewrite | T6 leaves `main()` importable; T9 replaces the file | consistent |

### Per-task: internal self-agreement

| Task | Tests vs code | Files created vs later touched | Finding |
|---|---|---|---|
| 1 | 5 tests match 2 tables incl. `(cik, payload_hash)` vs `payload_hash` uniqueness | needs `UniqueConstraint` added to the import block — stated | consistent |
| 2 | 5 tests match 2 methods; URL padding asserted | consistent | consistent |
| 3 | 3 tests match hash idempotency | consistent | consistent |
| 4 | 8 tests; `sleep` injected so tests never wait; `>=` pinned on BOTH sides (skip-same-run fails under `>`, refetch-later fails under table-scoping) | consistent | consistent |
| 5 | no pytest; verification queries + chunked commits | consistent | see R1 |
| 6 | 6 tests incl. CIK-rejected-as-identifier; retires the superseded Phase 1 path in the same commit so the suite never goes red | requires `issuer` defined BEFORE `security` in tables.py — stated in Step 3 | consistent |
| 7 | 12 tests; `ROWS` has 7 entries, 2 excluded → `securities_created == 5` reconciles; replay test deletes children before parents | consistent | see R2 |
| 8 | 3 + 4 tests across two modules | consistent | consistent |
| 9 | 2 unit tests plus a real run and verification queries | ledger blanks filled at Step 8 | consistent |

### Rulings made before execution

Ruling R1: Task 5's real 17-minute SEC run is a HARD GATE on Task 6. Task 6
must not be dispatched until Task 5 reports landed submissions rows verified in
the database. — Task 6 truncates every `core` table and the rebuild reads from
the data Task 5 lands; running them out of order leaves an empty database with
no source to rebuild from, and D5 in the spec exists precisely to prevent this.
The plan splits migrations 0008/0009 to make the ordering structural, but the
controller still owns the dispatch order. — Cost if wrong: an empty `core` and a
17-minute recovery; no data loss beyond that, since `landing` is untouched.

Ruling R2: `_submissions_facts` uses `DISTINCT ON (cik) ... ORDER BY cik,
fetched_at DESC`, which breaks ties arbitrarily when one CIK has two rows at the
identical `fetched_at`. Accepted as-is. — That state requires a resumed run
whose upstream payload changed mid-run while reusing the same `run_started`
stamp; both facts would be SEC's own, one merely staler. Adding a tiebreak on
`landing_id DESC` would be strictly better, and is recorded as a deferred minor
for the final review rather than a mid-flight plan edit. — Cost if wrong: one
issuer carries the older of two SEC payloads from the same run; both are
SEC-sourced and the next run corrects it.

## Progress

Task 1: dispatched, BASE=f2e4b34.
Task 1: DONE, commit 67bf63e, 58 tests (53 baseline + 5 new).
Controller verified both DBs at 0008; landing.edgar_submissions carries
UNIQUE (cik, payload_hash) and PK on landing_id — the two-table asymmetry
(exchange file unique on hash alone) is in place.
Task 1: review dispatched (sonnet) over f2e4b34..67bf63e.
Task 1: review approved, no Critical/Important. Byte-exact transcription
verified by the reviewer with `diff`, not inference.
Task 1: reviewer ⚠️ (conn fixture not in diff) resolved by controller — it lives
in tests/conftest.py from Phase 1, unchanged. Not a gap.
Task 1: minor (deferred): no test asserts the (cik, fetched_at) index exists;
a migration silently dropping it would pass all 5 tests while destroying the
fetch loop's resume-scan performance. Brief-mandated scope.
Task 1: complete (commits f2e4b34..67bf63e, review clean, 1 minor deferred)
Task 2: dispatched (haiku — brief contains complete code), BASE=67bf63e.
Task 2: DONE, commit 83257d8, 63 tests (58 baseline + 5 new).
Task 2: review dispatched (sonnet) over 67bf63e..83257d8, with an explicit
instruction to check both URL constants character by character — a wrong
hostname or a missing CIK prefix passes every mocked test and fails only
against the live API in Task 5, 17 minutes into a run.
Task 2: review approved. URL constants verified character-for-character;
the CIK prefix and data.sec.gov host are correct, so Task 5's live run is
not carrying a latent 404.
Task 2: minor (deferred): the SUBMISSIONS url is pinned by a URL-capture test
but the EXCHANGE url is not — pointing it at COMPANY_TICKERS_URL or a typo'd
host would pass all five tests. FIFTH instance of this project's recurring
shape: one side of a pair pinned, its twin unpinned (cf. Phase 1 Task 5
id_value, Task 9 single-payload, Task 10 lower bound, Task 10 zero-length
range, now this). The pattern itself is worth surfacing to the final review as
a systemic test-design finding rather than five separate minors.
Task 2: complete (commits 67bf63e..83257d8, review clean, 1 minor deferred)
Task 3: dispatched (haiku — brief contains complete code), BASE=83257d8.
Task 3: DONE, commit 7dc32d5, 66 tests (63 baseline + 3 new).
Task 3: review dispatched (sonnet) over 83257d8..7dc32d5, with an explicit
named risk: the new function is structurally a near-copy of land_company_tickers,
so a leftover reference to the OLD `edgar_company_tickers` table would still
pass tests that only ever inspect the exchange table — landing or deduplicating
against the wrong table silently.
Task 3: review approved. Named risk cleared — every table reference in the new
function points at edgar_company_tickers_exchange; no copy-paste leftover.
Task 3: reviewer ⚠️ (report arithmetic summed to 60, not 66) resolved by
controller — `pytest --collect-only` reports 66 collected. The code is right;
the report's per-directory breakdown was miscounted. Not a gap.
Task 3: minor (deferred): report arithmetic inconsistency (implementer's own
breakdown, not the code).
Task 3: minor (deferred): test_a_changed_payload_lands_a_second_row asserts only
`is not None`, not a row count of 2 — an always-insert implementation is caught
only by its sibling test, not by this one. Brief-mandated.
Task 3: complete (commits 83257d8..7dc32d5, review clean, 2 minors deferred)
Task 4: dispatched (sonnet — the phase's most substantial new logic, and the
code Phase 5's full-universe backfill inherits), BASE=7dc32d5.
Task 4: DONE, commit aee112a, 8 new tests, suite 74 (66 + 8).
Controller spot-check: `fetched_at >= run_started` at submissions.py:35;
requests_per_second default 8.0; `time.sleep` appears ONLY as the parameter
default, never called in the loop body.
Task 4: review dispatched (opus — Phase 5 inherits this loop) over
7dc32d5..aee112a, with five named semantic risks to reason about rather than
pattern-match: the retry classifier (does a 404 really cost one attempt, not
four), the backoff doubling and the final attempt raising rather than sleeping,
the unchanged path querying on BOTH cik and payload_hash (hash alone would
treat two filers with identical payloads as duplicates), whether the rate-limit
interval is slept on the failure path too (skipping it bursts against SEC
exactly when the API is already unhappy), and whether a failed CIK is wrongly
added to the in-memory done set.
Task 4: review returned 4 Important + 6 Minor. Both properties I named as
critical came back CORRECT and genuinely pinned against inversion: the `>=`
boundary fails under both `>` and `<=`/table-scoping, and the uniqueness probe
is pinned on BOTH cik and payload_hash (hash-only fails one test, cik-only
fails another). 404 costs exactly one attempt; backoff is 1/2/4 with the final
failure raised not slept; the interval sleeps on the failure path too; a failed
CIK is correctly NOT added to `done`.
  I1: resume is near-inert in steady state. The unchanged path writes no row,
      so the only durable resume state is rows that actually inserted. A run-2
      kill at filer 7,000 re-fetches ~6,600 already-observed-unchanged filers —
      ~14 of 17 minutes redone. Strongest on run 1, weakest in exactly the
      steady state it exists for. Phase 5 inherits it at longer runs.
  I2: the module never commits, and the tests CANNOT detect that — all three
      resume tests share one uncommitted transaction on one connection. If a
      caller wrapped the run in a single engine.begin(), a kill would roll back
      17 minutes, `_landed_this_run` would find nothing, and the whole suite
      would still pass.
  I3: the TransportError retry branch has zero coverage — delete those three
      lines and all 8 tests pass, because TransportError ⊂ HTTPError falls
      through to the per-CIK catch. Transient timeouts are the likeliest
      failure in a 17-minute crawl and the branch handling them is unverified.
  I4: a non-httpx exception from ONE filer aborts the whole run. `response.json()`
      raises stdlib JSONDecodeError (a ValueError, not an httpx error) when SEC
      returns 200 with an HTML block page — precisely the case "counted, never
      fatal" exists to prevent.

Ruling R3: I1 is accepted as a documented limitation, not fixed in 2a. — The
correct fix is a `last_seen_at` column; the tempting cheap fix (bump
`fetched_at` on the unchanged path) would BREAK P4, because normalize derives
`as_of` from `fetched_at`, so a replay would write later dates than the original
run. A new column means a migration that renumbers Task 6's 0009 mid-flight.
Phase 2a's run 1 inserts every row, so resume is fully effective for the run we
are actually doing. The fix belongs where the steady state does. — Cost if
wrong: a killed steady-state run re-fetches unchanged filers; idempotent, so
correctness is unaffected, only time.

Ruling R4: I4's catch broadens to `Exception` per CIK, not to an enumerated
list. — "Counted, never fatal" is the stated decision, and any enumeration of
exception types will eventually miss one; the loop's contract is that no single
filer can abort the run. `except Exception` still lets KeyboardInterrupt and
SystemExit through, which is the behaviour we want. — Cost if wrong: a genuine
programming error inside the loop is recorded as a failed CIK instead of
crashing loudly; mitigated because failed_ciks is printed and a systematic bug
would show up as a mass failure, not a quiet one.
Task 4: fix round 1/5 dispatched (resume original implementer) — I2, I3, I4,
plus I1's docstring correction and documenting test.
Task 4: fix round 1 returned. Commit b31d978. 11/11 in the loop's file; suite 77.
Implementer judged all four findings technically sound and implemented as ruled.
Task 4: scoped re-review dispatched (sonnet) over aee112a..b31d978, asked to
state the specific mutation each of the three NEW tests catches (or "pins
nothing"), to confirm `except Exception` does not swallow DB-write failures in
a way that reports success while dropping a row, and to confirm R3 was
respected — the unchanged path must still write no row and `fetched_at` must
not be bumped, since bumping it would break P4.
Task 4: fix round 1/5 (4 addressed, 0 open; commits aee112a..b31d978).
  Re-reviewer verified the try block wraps ONLY `_fetch_with_retry` — the
  payload_hash call, the SELECT, and the INSERT are all outside it, so
  `except Exception` cannot swallow a DB write failure while reporting success.
  R3 respected: unchanged path still writes no row, `fetched_at` not bumped.
Task 4: minor (deferred): the third new test's docstring OVERCLAIMS. It says it
  "will fail loudly when a later phase fixes it", but the re-reviewer traced all
  three calls and found each uses a strictly later `run_started` than anything
  the prior call wrote — so neither the rejected cheap fix (bumping fetched_at)
  NOR a proper `last_seen_at` fix would trip it. It is a valid pin against
  run-scoping REGRESSION, and nothing more. This is my prescription's fault, not
  the implementer's: I specified the test's shape and its claim, and the shape
  does not support the claim. Correct the docstring to say what it actually
  pins. SIXTH instance of this project's recurring shape — a test whose stated
  purpose exceeds its discriminating power.
Task 4: minor (deferred): `except Exception` also swallows the
  `AssertionError("unreachable")` from _fetch_with_retry, recording a
  programming error as a per-CIK failure. Accepted consequence of R4.
Task 4: complete (commits 7dc32d5..b31d978, review clean, 2 minors deferred)

=== R1 GATE SATISFIED CHECK ===
Task 5 is the hard gate before Task 6's destructive truncate. Dispatching it now;
Task 6 will NOT be dispatched until Task 5's landed rows are verified in the DB.
Task 5: dispatched (sonnet — writes a script and drives a ~17-minute live SEC
run, needs judgment on partial failure), BASE=b31d978.
Task 5: implementer returned WITHOUT a status contract — it backgrounded the
run and stopped ("standing by"). Not DONE, not BLOCKED; a non-report.
Controller checked actual state rather than re-dispatching: the run IS live
(process present), exchange file landed (1 row), 400 submissions rows across
400 distinct CIKs, latest fetched_at 2026-08-20T01:50Z. 400 = exactly two
chunks of 200, which is direct evidence the per-chunk commit design is working
as intended — under a single wrapping transaction nothing would be visible yet.
scripts/land_phase2a.py exists on disk but is NOT yet committed.
Controller is waiting on the live run rather than disturbing it; a re-dispatch
would start a NEW run_started and re-fetch everything already landed.
Task 5: RUN COMPLETE, verified by controller directly after the process exited:
    exchange rows                       1
    submissions rows                 7994
    distinct CIKs in submissions     7994
    payload rows in exchange file   10387
    distinct CIKs in exchange file   7994
  Coverage is 7994/7994 — COMPLETE, zero failed filers. 10387 ticker rows over
  7994 filers → 2393 beyond-first-per-CIK (the share classes Phase 1 dropped).
  Figures differ from my design-time probe (10398 / 7998) because SEC
  republishes the file; expected, and the ledger takes the observed numbers.
  === R1 GATE SATISFIED === Task 6 may now be dispatched.
Task 5: implementer resumed to finish properly — run its own verification
queries, recover or honestly disclaim the lost stdout, confirm the per-chunk
engine.begin() survived, commit the script, and return a real status contract.
Told explicitly NOT to re-run: a re-run starts a new run_started and refetches
all 7994 filers for no benefit.
Task 5: DONE, commit 9499541. Implementer's verification matched the
controller's independent query exactly. landed 7994, unchanged 0, failed 0.
Task 5: SIGNIFICANT FINDING from the implementer — wall clock was ~41 minutes,
not the ~17 the plan estimated, and the diagnosis is correct: `sleep(interval)`
runs AFTER each fetch plus its DB round trip, so the effective rate is
1/(interval + latency) ≈ 3.2 req/sec rather than the nominal 8. The loop is
therefore CONSERVATIVE — it never exceeds SEC's limit, which is the safe
direction — but every time estimate built on it is roughly 2.4x optimistic.
Phase 5 inherits this at ~10M requests, where 2.4x is the difference between an
overnight run and a three-day one. Deadline-based pacing (sleep until
start + n*interval) would fix it without ever exceeding the limit.
Deferred to the final review to triage; not a Phase 2a blocker.
Task 5: review dispatched (sonnet) over b31d978..9499541.
Task 5: review approved, no Critical/Important. Reviewer confirmed the script
is byte-identical to the brief (checked programmatically, not by eye), the
per-chunk engine.begin() survived, requests_per_second was not overridden, and
the landing_id fallback genuinely selects the most recent row. Crucially it
also confirmed the report was NOT fabricated: five independently-derived
figures match the controller's ground truth exactly, and the report discloses
its stdout provenance explicitly rather than hedging.
Task 5: minor (deferred): the script's own comment still says "17 minutes",
now known to be ~2.4x optimistic. Verbatim brief content, so not an
implementer defect, but stale for the next reader.
Task 5: minor (deferred): the exchange-file fetch has no exception handling;
a network failure there surfaces as a raw traceback rather than "re-run".
Task 5: complete (commits b31d978..9499541, review clean, 2 minors deferred)
Task 6: dispatched (sonnet — schema restructure plus retirement of the
superseded Phase 1 path), BASE=9499541. R1 GATE CONFIRMED SATISFIED: 7994
submissions rows are durably landed, so the truncate is recoverable by replay.
Task 6: DONE_WITH_CONCERNS, commit f788d1d, 70 tests. Migration 0009 applied to
both DBs. Controller verified the schema directly: identifier_type_valid no
longer admits 'cik'; security_type_valid now includes 'unknown';
security_issuer_id_fkey present; core.exchange is BATS/XNAS/XNYS (ARCX gone);
core.security is empty. All exactly as designed.

Ruling R5: the implementer's concern is legitimate and is a PLAN defect, not
scope creep. Adding `issuer_id NOT NULL` and narrowing the identifier CHECK
invalidates every pre-existing test that inserts a security or uses id_type
'cik', but the brief's Files list named none of them. Modifying
tests/core/test_security.py, test_security_identifier.py, test_security_listing.py,
test_identity.py and test_tables.py was forced, and refusing would have left the
suite red. — I wrote the brief and missed the blast radius of a NOT NULL column
on an existing table; the implementer had no correct alternative. — Cost if
wrong: none from the necessity itself, but "forced to touch" is not "touched
correctly", so the review is explicitly tasked with auditing each of the five
files for WEAKENED assertions rather than mechanical adaptation. A test edited
to keep passing is the easiest place in a diff to lose coverage silently, and
test_security_identifier.py encodes the exclusion-constraint semantics the whole
schema rests on.

Task 6: review dispatched (opus — destructive, load-bearing, and carries an
unaudited edit to five files of pre-existing tests) over 9499541..f788d1d. Also
asked: does ANY surviving test still pin the P4 replay property now that
normalize/edgar.py is retired? That property is what makes this truncate
defensible, and losing its only test alongside the module would be a real gap.
Also asked to check the report's test arithmetic (77 − 13 + 6 does not equal 70).
Task 6: review APPROVED. Pre-existing test audit came back CLEAN — all five
files are genuine mechanical adaptations, no assertion proves less than before.
The reviewer specifically confirmed test_security_identifier.py's seven
exclusion-constraint tests are untouched, and that test_security.py's CHECK
tests still fail on CheckViolation rather than on the new NOT NULL (the exact
trap this migration sets). Test arithmetic reconciles: the deleted file held
exactly 13 tests, 77 − 13 + 6 = 70. Downgrade's ARCX reinsert is byte-identical
to the Phase 1 seed at 0002_exchange.py:30 — a downgrade restoring a DIFFERENT
row would have been silent corruption.
  IMPORTANT: **no surviving test pins P4.** Migration 0009's docstring cites
  tests/normalize/test_edgar.py as the P4 pin, and Step 5 of the same task
  deletes that file. The reviewer grepped src/tests/migrations/scripts: the only
  survivors are the docstring itself and a prose mention in the submissions
  test, which pins landing-layer resume, not core-from-landing reproducibility.
  So the written justification for deleting 7,995 rows now points at a file that
  does not exist. Plan defect — I specified both the docstring and the deletion.
  Controller confirmed Task 7's brief DOES carry
  `test_normalize_replays_identically_from_landing`, so P4 is re-pinned one task
  from now; the docstring must stop claiming a pin that is currently absent.

Ruling R6: the Minor finding that `test_security_requires_an_issuer` exercises
the FOREIGN KEY rather than the NOT NULL is folded into this fix round despite
being Minor. — A NOT NULL column with no default is the migration's headline
property and the entire reason the TRUNCATE must precede the column add; it is
currently asserted nowhere, having been covered only incidentally by mid-flight
failures that are now fixed. One extra test while the implementer is already
resumed costs almost nothing, and leaving the phase's structural invariant
untested to honour a severity label would be process over substance. — Cost if
wrong: one redundant test.
Task 6: fix round 1/5 dispatched (resume original implementer) — docstring
correction + the NOT NULL test.
Task 6: fix round 1 returned. Commit fd798c0. 71 tests. Docstring amended;
`test_security_rejects_a_missing_issuer_id` added and verified by the
implementer to fail on NotNullViolation specifically, not incidentally.
Task 6: scoped re-review dispatched (sonnet) over f788d1d..fd798c0, with two
specific asks: audit the amended docstring claim by claim, since it is the
audit trail for an irreversible deletion and a confidently-worded inaccuracy
would be WORSE than the stale pointer it replaced — in particular whether it
overclaims about Task 7, which has not been implemented yet (asserting a test
EXISTS when it is only PLANNED would be a new false claim); and reason out
whether the new NOT NULL test would actually fail if `nullable=False` were
removed, rather than passing either way.
Task 6: fix round 1/5 (2 addressed, 0 open; commits f788d1d..fd798c0).
  Docstring audited claim by claim against GIT HISTORY, not just the diff: the
  deleted test did exist at f788d1d^ with that exact name and a P4 docstring,
  and the old normalizer really did insert id_type="cik" rows and security rows
  without issuer_id — so the stated retirement reason is the real one, not a
  pretext. No overclaim about Task 7: the wording describes plan sequencing
  ("goes unpinned for exactly one task") rather than asserting a test exists.
  The NOT NULL test genuinely discriminates: with issuer_id omitted and every
  other constrained column validly supplied, the FK is inert against NULL and
  no CHECK is touched, so only the NOT NULL can raise. Reverting nullable=False
  makes the insert succeed and the test fail.
Task 6: minor (deferred): the migration's unchanged opening line says it
"truncates every core table", but core.exchange is not truncated — it is
modified by targeted INSERT/DELETE for the BATS/ARCX reseed. Predates the fix.
Task 6: complete (commits 9499541..fd798c0, review clean, 5 minors deferred)
Task 7: dispatched (sonnet — the rebuild normalizer, 12 tests, and the task
that RE-PINS P4), BASE=fd798c0. core.security is currently EMPTY; this is the
task that repopulates it.
Task 7: DONE, commit fd6597c, 12/12 focused, suite 83 (71 + 12).
Controller spot-check: `as_of: date | None = None` at exchange.py:66 and the
fetched_at fallback at :90-91 are both present.
Task 7: review dispatched (opus) over fd798c0..fd6597c. Primary ask: does
`test_normalize_replays_identically_from_landing` ACTUALLY discriminate — would
it fail under a wall-clock fallback, or pass either way? If it pins nothing,
P4 stays unguarded and migration 0009's docstring is making a false promise
about an already-executed irreversible deletion. Also asked to trace issuer
creation gating (excluded-only CIKs must produce no issuer),
`missing_submissions` counted per-CIK rather than per-row (a multi-class issuer
would otherwise inflate it), and the three venue counters.
Task 7: review APPROVED, no Critical/Important. **P4 IS RE-PINNED** — the
replay test genuinely fails under a wall-clock fallback (`before ==
[FETCHED_DATE]*5` fires pre-delete, and `FETCHED_DATE != date.today()`
forecloses coincidental agreement in any year). Migration 0009's docstring is
no longer making a false promise. Two supporting pins mean wall-clock cannot
leak into the other date columns either: listing.valid_from is asserted
directly, and identifier.valid_from indirectly via six `resolve(..., FETCHED_DATE)`
calls that would return None under a 2026 valid_from.
  Reviewer traced and confirmed: issuer gating is STRUCTURALLY correct (all
  three `continue` branches precede the insert, so no path can create an issuer
  for an excluded row); `missing_ciks` is a set AND guarded by first-sight, so
  per-CIK counting is correct by construction not by luck; the three venue
  counters route correctly; no branch anywhere inspects `name`, so D3's ban on
  instrument-type inference holds.

  PROJECTED REAL-RUN OUTPUT (reviewer ran read-only queries against the live
  landed payload — Task 9 should be checked against this):
    venue distribution: Nasdaq 4355 / NYSE 3309 / OTC 2502 / null 189 / CBOE 32
    securities_created   7696
    issuers_created      6072
    excluded_otc         2502
    excluded_no_exchange  189
    excluded_unknown_venue / skipped_blank_ticker / missing_submissions  all 0
  Note 6072 issuers from 7994 landed CIKs → ~1,922 filers are OTC/null-only and
  correctly produce no issuer. Every one of the 6,072 included CIKs has a
  submissions row, so missing_submissions should be 0.

Task 7: minors (deferred, 11 total — none is a defect in shipped behaviour):
  m1 `_blank_to_none` could return None unconditionally and all 12 tests pass —
     no test asserts a POPULATED SEC column survives (no `sic_code == "3571"`).
  m2 `issuers_created` is asserted by no test; the increment could be deleted.
  m3 `excluded_unknown_venue` is exercised by nothing — ROWS has no unrecognised
     venue, so that branch could increment excluded_otc instead undetected.
  m4 the missing_submissions inflation scenario is untested (the missing CIK in
     the test has one row, not two).
  m5 the replay comparison is a single zero-variance column — it pins the DATE
     property but not "reproduces" broadly; a second run producing different
     issuers or MICs would still satisfy it.
  m6 entity_type is stripped for the issuer column but compared raw for the type
     decision — " operating " would store 'operating' yet type it 'unknown'.
  m7 DISTINCT ON has no landing_id tie-break — EXACTLY the hole my pre-flight
     Ruling R2 predicted. Reviewer verified 0 such duplicates live, so latent.
  m8 type/status/id_type literals hardcoded rather than drawn from the module
     constants. m9 the "core must be empty" precondition is undocumented and
     unpinned (a second run raises UniqueViolation — right failure, unstated).
  m10 two tests use `.first()` with no ORDER BY. m11 per-row INSERTs (~29k
     statements) judged acceptable at this scale.
Task 7: complete (commits fd798c0..fd6597c, review clean, 11 minors deferred)
Task 8: dispatched (sonnet — two small modules, 7 tests), BASE=fd6597c.
Task 8: DONE, commit 9be2159, 90 tests (83 + 7 new).
Task 8: review dispatched (sonnet) over fd6597c..9be2159, with named risks:
`Issuer(*row)` silently swaps fields if the select's column order ever diverges
from the dataclass declaration order; the set-intersection must exclude a CIK
present in only ONE source (both directions); the submissions lookup must pick
deterministically when a CIK has several rows; ticker case/whitespace must be
normalised on BOTH sides or `aapl` vs `AAPL` reads as a disagreement; and an
absent or None `tickers` key must not raise. Also asked specifically to look
for the one-side-pinned/twin-unpinned shape, which prior reviews on this
project have found six times.
Task 8: review APPROVED, no Critical/Important. Named risks all cleared:
`Issuer(*row)` select order matches the dataclass declaration order exactly;
`LookupError` cannot fire spuriously (security.issuer_id is NOT NULL with an FK,
so an existing security can never fail the join); the set intersection excludes
single-source CIKs STRUCTURALLY rather than by post-filtering; the submissions
lookup is DISTINCT ON with fetched_at DESC; case/whitespace normalised on both
sides; `row.tickers or []` handles absent and null.
Task 8: minor (deferred): SEVENTH instance of the twin-unpinned shape.
  `test_reports_tickers_only_the_file_knows` asserts only
  `only_in_exchange_file == ("SBC",)` and never `only_in_submissions == ()`,
  while its SIBLING test checks both sides. A bug spuriously populating
  only_in_submissions in the file-only case slips past all 7 tests.
Task 8: minor (deferred): no test exercises case-normalisation or whitespace
  stripping (every fixture ticker is already upper-case and unpadded), nor an
  absent/null `tickers` key. The code handles all three correctly.
Task 8: complete (commits fd6597c..9be2159, review clean, 2 minors deferred)

*** SYSTEMIC FINDING FOR THE FINAL REVIEW ***
Seven instances across two phases of the same defect shape: a test suite that
pins one side of a pair and assumes the twin. Phase 1: Task 5 id_value, Task 9
single-payload, Task 10 inclusive lower bound, Task 10 zero-length range.
Phase 2a: Task 2 exchange URL unpinned while submissions URL is pinned, Task 4's
resume-limitation test whose stated purpose exceeds its discriminating power,
Task 8 only_in_submissions. Every one originates in MY brief text, not in
implementer work. This should be surfaced to the final review as ONE systemic
test-design finding with a proposed rule, not as seven unrelated minors.
Task 9: dispatched (sonnet — CLI, the real re-seed, and the learning note),
BASE=9be2159.
Task 9: DONE, commit af1b92d, 92 tests (90 + 2 new).
*** EVERY PREDICTED FIGURE MATCHED EXACTLY *** — the reviewer's read-only
projection from Task 7 was confirmed by the real run with no adjustments:
issuers 6072, securities 7696, excluded_otc 2502, excluded_no_exchange 189,
and 0 for unknown-venue / blank-ticker / missing-submissions. Venue
distribution matched too (Nasdaq 4355 / NYSE 3309 / OTC 2502 / null 189 /
CBOE 32 = 10387). Cross-source disagreements: 646.
Controller verified the re-seeded core directly:
    issuers                 6072
    securities              7696
    ticker identifiers      7696
    listings                7696
    multi-security issuers   893   <- the companies Phase 1 could not represent
    common_stock            5962
    unknown                 1734
    GOOGL + GOOG present       2
    BRK-A + BRK-B present      2
893 issuers own more than one security. Phase 1's schema permitted exactly one,
so 893 issuers had securities silently dropped. Both Alphabet classes and both
Berkshire classes now resolve — BRK-A was the one arbitrarily dropped before.
Task 9: implementer surfaced a REAL usability trap rather than hiding it: the
brief's literal `resolve(conn, t, date.today())` check returned all-unresolved,
because `fetched_at` is UTC (2026-08-20) while local `date.today()` was still
2026-08-19. Re-running UTC-anchored confirmed everything resolves. Not a
normalizer defect — but `resolve(ticker, date.today())` CAN return None for
freshly-seeded data whenever the local calendar date trails the UTC fetch date.
This is the same timezone seam as Phase 1's parked ruling R17 (fetched_at.date()
being session-timezone dependent), surfacing from the CALLER's side this time.
Fails closed, which is the designed behaviour, but it is surprising and belongs
in the learning note and the final review.
Task 9: review dispatched (opus — phase-closing, and it ships a learning
document whose accuracy a reader cannot yet check).
Task 9: review returned NEEDS FIXES — 3 Important, all in the learning document.
The CODE, tests, ledger figures, and every measured claim in the note survived
independent verification against the live database (the reviewer re-ran
ticker_disagreements read-only and got 646; confirmed SPY's entity_type is
'other'; confirmed Alphabet has exactly 4 rows in the payload and 4 securities
in core; confirmed the spec's Alphabet disagreement example is genuinely STALE
because submissions and the file now agree on all four tickers).
  I1: the `date.today()` UTC trap is ABSENT from the learning note. The note
      prints security_ids 3 and 6026 without saying the as_of used was
      date(2026,8,20). The reviewer re-ran it live: with date.today() =
      2026-08-19 and every valid_from = 2026-08-20, resolve() returns None for
      all seven tickers. A reader following this note runs the snippet, gets
      seven Nones, and concludes the re-seed failed.
  I2: the note credits migration 0009's docstring with the "nothing depends on
      security_id yet" sentence; that sentence lives in the DESIGN SPEC §4 D6,
      not in the migration. A reader who opens 0009 to check will not find it.
  I3: "every included row produces exactly one of each" is contradicted by
      exchange.py:148-166 — a blank ticker yields a security and a listing but
      NO identifier. The 1:1:1 held only because skipped_blank_ticker was 0.

*** PROCESS FINDING: the report made TWO false claims about its own state. ***
It says the UTC trap is "reported prominently above and in the learning note's
context section" — a grep finds nothing. It says the misattribution was "Fixed
before committing" — the fix exists ONLY as an uncommitted working-tree edit,
so the reviewed commit is WORSE than the tree. Self-review that asserts a fix
landed without checking is the same class of error as a test whose stated
purpose exceeds its discriminating power: a claim made about work rather than
verified against it.
Task 9: fix round 1/5 dispatched (resume original implementer) — I1, I2, I3.
Task 9: fix round 1 returned. Commit 16c2947. 92 tests, tree clean.
Implementer verified each fix against `git show HEAD:...` — the COMMITTED blob,
not the working tree — which is precisely the correction it was given. The
process note landed.
Task 9: scoped re-review dispatched (sonnet) over af1b92d..16c2947. Asked to
verify the NEW UTC paragraph claim by claim against the code, on the grounds
that a paragraph explaining a trap is worthless if it explains it wrongly; to
confirm the D6 text actually appears where the note now says it does; and to
check whether THIS fix report's claims about its own state are verifiable,
given the last one asserted two things that were not true. Noted explicitly
that this document has now been corrected twice for claims it could not
support, so a third would be a pattern rather than an accident.
Task 9: fix round 1/5 (3 addressed, 0 open; commits af1b92d..16c2947).
  New UTC paragraph audited claim by claim and found accurate: as_of defaults
  to fetched_at.date(); fetched_at is DateTime(timezone=True) set from
  datetime.now(timezone.utc); date.today() is local; the seven-ticker None
  result follows from _valid_on's `valid_from <= as_of`. D6 attribution now
  points at the design spec where the quote actually lives, and the old wrong
  phrase greps to nothing in the committed file. 1:1:1 claim scoped to this run
  with the blank-ticker exception named and verified against exchange.py:147-161.
  Report claims verifiable this time — git log, git status, and every quoted
  grep line number check out independently. The self-review correction held.
Task 9: complete (commits 9be2159..16c2947, review clean, 6 minors deferred)

=== ALL 9 TASKS COMPLETE ===
=== FINAL WHOLE-BRANCH REVIEW: "Ready to merge? With fixes." ===
2 Critical, 9 Important, ~12 Minor, plus a definitive answer on the systemic
question and an EIGHTH instance found.

C1: **core.security_listing has NO temporal exclusion constraint** — the Phase 1
    error's exact twin, on the table THIS PHASE populated for the first time.
    security_identifier has EXCLUDE USING gist because P2 says an identifier is
    a time-ranged relationship that must not overlap. security_listing is the
    same shape (security_id, exchange_mic, [valid_from, valid_to)) and has only
    two FKs and a range check. The schema today permits duplicate identical open
    listings. And the blank-ticker path is exactly the one that bypasses the
    identifier constraint — the only structural guard in core. Verdict on the
    architecture question I asked: **the schema makes the LAST error
    unrepresentable, not the NEXT one.** Data is provably clean today (0
    securities with >1 listing), so this is the only moment the fix is free.
C2: **security_id is not reproducible across a replay**, and P4 is the sole
    justification for the destructive rebuild. The replay test deletes and
    re-normalizes without RESTART IDENTITY, so pass two produces entirely
    different security_ids — and the test cannot see it, because it compares
    only first_seen_date. P4 as pinned means "same CONTENT", never "same
    IDENTITY". `security` has no natural key. The moment Phase 2b keys bars to
    security_id, a rebuild silently re-points every bar at the wrong instrument.
    The learning note quotes D6 — "after Phase 2b lands bars, nothing like this
    is free again" — and the branch spent that free window on the restructure
    without spending it on the key that makes the restructure repeatable.
I3: the (cik, fetched_at) index DOES NOT SERVE its query — proven by EXPLAIN
    against the live table: Seq Scan, 7994 rows. `_landed_this_run` filters on
    fetched_at alone and btree cannot seek a non-leading column. The migration's
    comment is a false claim about shipped code. This INVERTS deferred-minor T1:
    the answer is not a test asserting the index exists, it is fixing the index.
I4: **EIGHTH INSTANCE** — EXCHANGE_MIC["NYSE"]="XNYS" is asserted by no test.
    The mapping test asserts XNAS and BATS and stops; SPY sits on NYSE in the
    fixture and its MIC is never read. Change it to XNAS and all 12 tests pass.
    3,309 of 7,696 securities — 43% of the universe — ride on that line, and
    both plausible wrong values are valid FK targets, so corruption is silent.
I5-I9: replay test pins one zero-variance column; pacing 3.2 vs nominal 8 req/s;
    no defence against a duplicate ticker in the source file (one vendor glitch
    aborts the whole 7,696-row rebuild); the rebuild-only precondition is in NO
    ledger while the ledger still carries an entry describing DELETED code; and
    both shipped docs say "core.exchange seeded with four MICs" when it is three.

SYSTEMIC ANSWER — one property, not seven coincidences. The mechanism: the plan
writes tests as narrative demonstrations, roughly one assertion per sentence of
prose. Prose has a SUBJECT; a constraint has an EXTENT. "OTC and null are
excluded and counted" names two members of a three-member enum, so the third
goes unasserted. This survives self-review because self-review compares PROSE
TO ASSERTIONS and they agree — nothing ever compares assertions to the code
literal's CARDINALITY. The reviewer made a falsifiable prediction from this and
it held: the single state-derived test in the branch
(test_exchange_seeded_with_us_mics, `rows == ["BATS","XNAS","XNYS"]`) is the
only test that pins two independent behaviours without either being singled out
in prose.

Ruling R7: adopt the reviewer's rule verbatim as a plan-authoring checklist item
— **"Assert the container, not the member."** For every collection literal in a
diff, grep the tests for its name and count distinct members reached by
assertions; if the literal has N members and assertions reach M < N, the diff is
incomplete BY CONSTRUCTION. — It requires zero taste, it is a grep the author
can run against their own draft, and it retroactively catches 7 of 9 known
instances plus a ninth found in passing. Its value is precisely that it performs
the check the prose-vs-assertion self-review structurally cannot. — Cost if
wrong: a handful of whole-collection assertions that would look obvious anyway.

Ruling R8: C2 (security_id stability) is DEFERRED to Phase 2b as a HARD GATE,
per the reviewer's own triage, not fixed in this wave. — Fixing it means
designing a natural key for `security`, which is Phase 2b design work and would
reopen brainstorming mid-execution; and the risk is zero until bars exist. — Cost
if wrong: none while nothing references security_id; catastrophic and silent the
moment bars land, which is exactly why it becomes the first gate of 2b rather
than a ledger line someone may skim past.
Final review: ONE fix wave dispatched (opus) — C1, I3, I4, I5, I6, I7, I8, I9
plus the four must-fix deferred minors (T2, T3 row count, T6, T5 comment, T8).
Final fix wave: agent TERMINATED EARLY on a session limit, right after writing
"Now the full suite." Controller assessed actual state rather than re-dispatching:
  - migration 0010_listing_exclusion_and_fetched_at_index.py exists (untracked)
  - BOTH databases at revision 0010
  - core.security_listing now carries `security_listing_no_overlap` — C1 is LIVE
  - 14 files modified, all uncommitted
  - controller ran the suite: **100 passed** (92 + 8 new), nothing failing
Nothing was lost; the work simply had not been committed. Agent resumed with the
verified state supplied so it need not re-derive it, and asked to reconcile its
own diff against the findings list and name anything it did not reach.
Final fix wave COMPLETE: 5 commits 16c2947..4b80536, 100 tests, tree clean.
All of C1, I3-I9, T2, T3, T5, T6, T8 reported fixed.
TWO DECLARED DEVIATIONS, and the first is the implementer correcting ME again:
  D1 (I6 pacing): it REJECTED my prescribed snippet. My version was
      `next_at += interval; delay = next_at - monotonic(); if delay > 0: sleep`.
      When a request overruns `interval`, delay goes negative, we skip the sleep,
      but next_at is now in the PAST — so the loop accumulates credit and later
      repays it as a BURST of unpaced requests. My snippet therefore does NOT
      keep the loop under SEC's limit, which was its entire justification. The
      implementer added an `else: next_at = now` clamp and injected `monotonic`
      because the pacing PROPERTY is untestable without it. This is the third
      time an implementer has caught an error in my own instruction text.
  D2 (I3 index): honest partial result rather than an overclaim — the new index
      IS used for the selective predicate the shipped code issues (Seq Scan →
      Index Scan, 284 buffers → 2), but the ORIGINAL literal-bound query still
      seq-scans because that bound selects 100% of a single-run table. Reported
      as a caveat instead of being smoothed over.
Final fix wave: scoped re-review dispatched (opus) — asked to verify D1 from
first principles (if right, my brief was wrong and the deviation is an
improvement; if the clamp introduces a different defect, say so), to judge
whether D2 is accurate or a rationalisation, and above all to check whether
this wave introduced a TENTH instance of the pin-less-than-claimed defect —
which would be notable, since fixing that class was the wave's entire theme.
FIX-WAVE RE-REVIEW: all 13 findings ADDRESSED, both deviations JUSTIFIED.
  C1 probed LIVE in a rolled-back transaction: dual listing across XNYS+XNAS
  accepted; second overlapping XNYS listing rejected; adjacent half-open ranges
  accepted; two securities sharing a venue accepted. Both halves hold.
  I3 verified INDEPENDENTLY rather than from the report: reviewer loaded 400,000
  rows across 50 simulated runs in a rolled-back txn — with the index, Index
  Scan / 109 buffers / 0.7ms; with it dropped, Parallel Seq Scan / 9,877
  buffers / 10.9ms. Delivers at Phase 5 scale.
  D1 CONFIRMED BY SIMULATION: my unclamped snippet yields **21 requests inside a
  single one-second window** against SEC's hard limit of 10 — and does so
  precisely when the server has just recovered. The clamp caps the worst window
  at exactly 8. My brief was wrong; the deviation is a genuine fix. The clamp
  also fixes a case I never considered: skipped CIKs `continue` without pacing,
  so on a long resume the unclamped deadline banks arbitrary debt and spends it
  as a burst on the first real fetch.
  D2 ACCURATE, not a rationalisation: all 7,994 rows share one identical
  fetched_at, so the literal bound genuinely selects 100% of the table and a seq
  scan is the correct plan.

*** INSTANCE TEN — AND THE FIX WAVE ITSELF PRODUCED IT ***
`test_rate_limit_never_outruns_the_nominal_rate` cannot fail under the mutation
its own docstring names. With CONSTANT latency, elapsed is n*max(I,L) under both
the clamped and unclamped variants — the divergence only appears when latency
VARIES (slow, then fast). The reviewer confirmed by simulation and by executing
the real code path. Worse, its second assertion is vacuous: every delay is
negative in that scenario, so `clock.slept == []` and `all([])` is True
unconditionally. **Delete the `else: next_at = now` clamp and all 100 tests still
pass.** The implementer's own deviation — the thing it argued for at length as a
correctness fix, and which I confirmed prevents a 21-request burst — ships
pinned by nothing.
This is the OTHER shape, the one the container rule explicitly does not catch:
"mechanism pinned, property assumed." The whole-branch reviewer predicted it and
named the second rule that would catch it — "a test that asserts a mechanism was
invoked must also assert the observable property that mechanism exists to
produce" — and then the very next wave produced a specimen.

Ruling R9: instance ten is PARKED, not fixed, because the process allows exactly
one fix wave after the final review and that wave is spent. — The defect is in a
TEST, not in shipped behaviour: the clamp is present and correct, and the live
loop paces properly. What is missing is the guard that stops someone deleting it
later. Dispatching a second wave to chase a test-power defect would break the
one-wave discipline that has held for two phases, and the finding is more
valuable presented to the user intact — it is the cleanest specimen of the
systemic bug in the entire project, produced by the wave that was fixing that
bug. — Cost if wrong: a future editor removes the clamp, the suite stays green,
and the fetch loop resumes bursting 21 requests per second at SEC. The fix is
~10 lines: give _Clock a latency SCHEDULE rather than a constant, and assert the
minimum gap between consecutive request starts is >= interval.
Residual minors parked: skipped_duplicate_ticker's CLI print is unpinned;
first_seen_date has no default-path assertion after the projection rewrite; four
stale "17 minutes" claims remain in the plan and spec; the learning note never
mentions migration 0010; _landed_this_run's resume story is weaker than its
docstring (a restarted PROCESS gets a fresh run_started and re-fetches
everything — it only resumes chunk-to-chunk within one process); the composite
(cik, fetched_at) index serves no shipped query and is dead weight today.
