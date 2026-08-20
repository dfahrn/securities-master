from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from securities_master.ingest.edgar import EdgarAdapter
from securities_master.ingest.submissions import land_submissions
from securities_master.landing.tables import edgar_submissions

RUN_ONE = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
RUN_TWO = RUN_ONE + timedelta(days=1)
CIKS = ["0000000111", "0000000222"]


def _adapter(handler) -> EdgarAdapter:
    return EdgarAdapter(
        user_agent="test test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _ok(body=None):
    return lambda request: httpx.Response(200, json=body or {"entityType": "operating"})


class _Sleeps:
    """Records sleep durations instead of waiting, so tests stay fast."""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def test_lands_every_cik_once(conn):
    result = land_submissions(
        conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=_Sleeps()
    )
    assert result.landed == 2
    assert result.failed == 0
    total = conn.execute(
        select(func.count()).select_from(edgar_submissions)
    ).scalar_one()
    assert total == 2


def test_resuming_the_same_run_skips_what_it_already_landed(conn):
    sleeps = _Sleeps()
    land_submissions(conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=sleeps)
    again = land_submissions(conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=sleeps)
    assert again.skipped_this_run == 2
    assert again.landed == 0


def test_a_later_run_refetches_rather_than_skipping(conn):
    """The resume rule is scoped to a run, never to the table.

    Scoping it to the table would make the first run correct and every later
    run a silent no-op, permanently hiding name changes, new tickers, and
    Form 25 filings.
    """
    sleeps = _Sleeps()
    land_submissions(conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=sleeps)
    later = land_submissions(
        conn, _adapter(_ok({"entityType": "other"})), CIKS, RUN_TWO, sleep=sleeps
    )
    assert later.skipped_this_run == 0
    assert later.landed == 2


def test_an_unchanged_payload_on_a_later_run_lands_nothing(conn):
    sleeps = _Sleeps()
    land_submissions(conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=sleeps)
    later = land_submissions(conn, _adapter(_ok()), CIKS, RUN_TWO, sleep=sleeps)
    assert later.unchanged == 2
    assert later.landed == 0
    total = conn.execute(
        select(func.count()).select_from(edgar_submissions)
    ).scalar_one()
    assert total == 2


def test_retries_a_retryable_status_then_succeeds(conn):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"entityType": "operating"})

    sleeps = _Sleeps()
    result = land_submissions(
        conn, _adapter(handler), ["0000000111"], RUN_ONE, sleep=sleeps
    )
    assert result.landed == 1
    assert attempts["n"] == 3
    assert 1.0 in sleeps.calls and 2.0 in sleeps.calls


def test_a_cik_that_exhausts_retries_is_counted_and_does_not_abort_the_run(conn):
    def handler(request):
        if "0000000111" in str(request.url):
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"entityType": "operating"})

    result = land_submissions(
        conn, _adapter(handler), CIKS, RUN_ONE, sleep=_Sleeps()
    )
    assert result.failed == 1
    assert result.failed_ciks == ("0000000111",)
    assert result.landed == 1


def test_a_non_retryable_status_fails_immediately(conn):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(404, text="no such filer")

    result = land_submissions(
        conn, _adapter(handler), ["0000000111"], RUN_ONE, sleep=_Sleeps()
    )
    assert result.failed == 1
    assert attempts["n"] == 1


def test_rate_limit_sleeps_between_requests(conn):
    sleeps = _Sleeps()
    land_submissions(
        conn, _adapter(_ok()), CIKS, RUN_ONE, requests_per_second=4.0, sleep=sleeps
    )
    assert sleeps.calls.count(0.25) == 2


def test_retries_a_transport_error_then_succeeds(conn):
    """The TransportError retry branch in `_fetch_with_retry`, exercised.

    Deleting that branch would leave every eight tests passing prior to
    this one, because `httpx.TransportError` still falls through to the
    outer per-CIK catch and gets counted as failed with no retries — which
    is silently wrong for the single likeliest failure in a 17-minute
    crawl: a transient connect/read timeout.
    """
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"entityType": "operating"})

    sleeps = _Sleeps()
    result = land_submissions(
        conn, _adapter(handler), ["0000000111"], RUN_ONE, sleep=sleeps
    )
    assert result.landed == 1
    assert attempts["n"] == 3
    assert 1.0 in sleeps.calls and 2.0 in sleeps.calls


def test_a_malformed_200_is_counted_and_does_not_abort_the_run(conn):
    """A single blocked/malformed response must not cost the whole run.

    SEC can return HTTP 200 with an HTML maintenance or automated-traffic
    block page. `EdgarAdapter.fetch_submissions_payload` calls
    `response.json()`, which raises `json.JSONDecodeError` (a `ValueError`,
    not an `httpx.HTTPError`) in that case. The per-CIK catch must be broad
    enough to count this as a failure rather than let it propagate and
    abort every remaining fetch.
    """

    def handler(request):
        if "0000000111" in str(request.url):
            return httpx.Response(200, text="<html>blocked</html>")
        return httpx.Response(200, json={"entityType": "operating"})

    result = land_submissions(
        conn, _adapter(handler), CIKS, RUN_ONE, sleep=_Sleeps()
    )
    assert result.failed == 1
    assert result.failed_ciks == ("0000000111",)
    assert result.landed == 1


def test_an_unchanged_observation_leaves_no_durable_resume_state(conn):
    """Documents a known Phase 2a limitation, deliberately deferred.

    The unchanged path increments a counter but writes no row, so it leaves
    no durable resume state: a kill immediately after an "unchanged"
    observation re-fetches that CIK on restart, even though the payload was
    already seen. The correct fix is a `last_seen_at` column (not yet
    built). The tempting cheap fix — bumping `fetched_at` on the unchanged
    path — is rejected: normalization derives `as_of` from `fetched_at`, so
    a replay would write a later `as_of` than the original observation.

    This test pins the current (imperfect) behaviour so that a future phase
    fixing it does so on purpose: it should start failing the moment
    `run_three.skipped_this_run` becomes nonzero for an unchanged CIK.
    """
    sleeps = _Sleeps()
    land_submissions(conn, _adapter(_ok()), CIKS, RUN_ONE, sleep=sleeps)
    run_two = land_submissions(
        conn, _adapter(_ok()), CIKS, RUN_ONE + timedelta(days=1), sleep=sleeps
    )
    run_three = land_submissions(
        conn, _adapter(_ok()), CIKS, RUN_ONE + timedelta(days=2), sleep=sleeps
    )
    assert run_two.unchanged == 2
    assert run_three.unchanged == 2
    assert run_three.skipped_this_run == 0
