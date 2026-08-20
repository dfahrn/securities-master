import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import Connection, select

from securities_master.ingest.base import payload_hash
from securities_master.ingest.edgar import EdgarAdapter
from securities_master.landing.tables import edgar_submissions

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class SubmissionsRunResult:
    landed: int
    unchanged: int
    skipped_this_run: int
    failed: int
    failed_ciks: tuple[str, ...]


def _landed_this_run(conn: Connection, run_started: datetime) -> set[str]:
    """CIKs already fetched during THIS run.

    Scoped to the run, never to the table. A rule of 'already exists in
    landing' would make the first run correct and every later run a no-op,
    permanently hiding renames, new tickers, and Form 25 filings.
    """
    return set(
        conn.execute(
            select(edgar_submissions.c.cik).where(
                edgar_submissions.c.fetched_at >= run_started
            )
        )
        .scalars()
        .all()
    )


def _fetch_with_retry(
    adapter: EdgarAdapter,
    cik: str,
    max_attempts: int,
    sleep: Callable[[float], None],
) -> dict:
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            return adapter.fetch_submissions_payload(cik)
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in RETRYABLE_STATUS
            if not retryable or attempt == max_attempts:
                raise
        except httpx.TransportError:
            if attempt == max_attempts:
                raise
        sleep(delay)
        delay *= 2
    raise AssertionError("unreachable: loop either returns or raises")


def land_submissions(
    conn: Connection,
    adapter: EdgarAdapter,
    ciks: Iterable[str],
    run_started: datetime,
    *,
    requests_per_second: float = 8.0,
    max_attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> SubmissionsRunResult:
    """Fetch and land one submissions payload per CIK.

    Rate limited to `requests_per_second` against SEC's stated limit of 10 —
    headroom rather than optimism. Pacing is deadline-based, not
    sleep-after-work: sleeping a fixed `interval` once the fetch and its DB
    round trip are done makes the achieved period `interval + latency`, which
    is how a nominal 8 req/s ran at a measured 3.2 (41 minutes against a
    17-minute estimate). Advancing a deadline by `interval` and sleeping only
    the remainder holds the nominal rate without ever exceeding it: a missed
    deadline resets to the current time instead of accumulating credit that
    would later be spent as a burst of unpaced requests.

    A CIK that fails outright, or that exhausts its retries, is recorded and
    counted, never fatal — one bad filer or one malformed response cannot
    cost 8,000 good fetches.

    Resumability is scoped to rows this run actually inserted, not to CIKs
    it merely observed. A killed run restarts and skips every CIK whose
    payload was landed (a new row) before the kill; a CIK whose payload was
    observed *unchanged* leaves no durable trace and will be re-fetched on
    restart, because the unchanged path writes no row and there is no
    `last_seen_at` column to record the observation (deferred to Phase 5 —
    see `test_an_unchanged_observation_leaves_no_durable_resume_state`).

    Transaction discipline is the caller's responsibility: this function
    does not commit. The resume property above only holds if the caller
    commits incrementally (e.g. per batch), so that inserted rows survive a
    kill. A caller that wraps an entire multi-thousand-CIK run in one
    uncommitted transaction gets no resumability at all — a kill loses
    everything back to the start, silently, because nothing was ever
    durable enough for `_landed_this_run` to see on restart.
    """
    done = _landed_this_run(conn, run_started)
    interval = 1.0 / requests_per_second
    next_at = monotonic()

    def pace() -> None:
        """Hold the deadline for the next request, then sleep to reach it."""
        nonlocal next_at
        next_at += interval
        now = monotonic()
        delay = next_at - now
        if delay > 0:
            sleep(delay)
        else:
            # Behind schedule (a slow fetch, or a retry backoff). Reset the
            # deadline to now rather than carrying the debt forward: an
            # accumulated deficit would be repaid as a burst of unpaced
            # requests the moment upstream sped up, which is exactly the
            # limit-exceeding behaviour the pacing exists to prevent.
            next_at = now

    landed = unchanged = skipped = failed = 0
    failures: list[str] = []

    for cik in ciks:
        if cik in done:
            skipped += 1
            continue

        try:
            payload = _fetch_with_retry(adapter, cik, max_attempts, sleep)
        except Exception:
            # Deliberately broad: an HTTP error, a malformed 200 (e.g. SEC's
            # HTML block/maintenance page, which raises json.JSONDecodeError
            # out of response.json() with no HTTP-level signal at all), or
            # any other per-CIK failure must be counted, never allowed to
            # abort the run. KeyboardInterrupt/SystemExit are BaseException,
            # not Exception, so they still propagate.
            failed += 1
            failures.append(cik)
            pace()
            continue

        digest = payload_hash(payload)
        exists = conn.execute(
            select(edgar_submissions.c.landing_id).where(
                edgar_submissions.c.cik == cik,
                edgar_submissions.c.payload_hash == digest,
            )
        ).scalar_one_or_none()

        if exists is None:
            conn.execute(
                edgar_submissions.insert().values(
                    cik=cik,
                    fetched_at=run_started,
                    payload_hash=digest,
                    payload=payload,
                )
            )
            landed += 1
        else:
            unchanged += 1

        done.add(cik)
        pace()

    return SubmissionsRunResult(
        landed=landed,
        unchanged=unchanged,
        skipped_this_run=skipped,
        failed=failed,
        failed_ciks=tuple(failures),
    )
