import httpx
import pytest

from securities_master.ingest.edgar import EdgarAdapter

EXCHANGE_SAMPLE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
}
SUBMISSIONS_SAMPLE = {"cik": "320193", "entityType": "operating", "sic": "3571"}


def _adapter(handler) -> EdgarAdapter:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "test test@example.com"},
    )
    return EdgarAdapter(user_agent="test test@example.com", client=client)


def test_fetch_exchange_payload_returns_the_raw_dict():
    adapter = _adapter(lambda r: httpx.Response(200, json=EXCHANGE_SAMPLE))
    assert adapter.fetch_company_tickers_exchange_payload() == EXCHANGE_SAMPLE


def test_fetch_exchange_builds_the_url():
    """Pins the URL the way the submissions test pins its own.

    Unpinned, a typo or a swap to `company_tickers.json` (a real file, with
    a different shape and no exchange column) fetches successfully and is
    caught only by whatever downstream test happens to notice the missing
    venue — or by nothing at all.
    """
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=EXCHANGE_SAMPLE)

    _adapter(handler).fetch_company_tickers_exchange_payload()
    assert seen["url"] == "https://www.sec.gov/files/company_tickers_exchange.json"


def test_fetch_submissions_builds_the_padded_url():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=SUBMISSIONS_SAMPLE)

    _adapter(handler).fetch_submissions_payload("0000320193")
    assert seen["url"] == "https://data.sec.gov/submissions/CIK0000320193.json"


def test_fetch_submissions_returns_the_raw_dict():
    adapter = _adapter(lambda r: httpx.Response(200, json=SUBMISSIONS_SAMPLE))
    assert adapter.fetch_submissions_payload("0000320193") == SUBMISSIONS_SAMPLE


def test_fetch_submissions_raises_on_http_error():
    adapter = _adapter(lambda r: httpx.Response(404, text="not found"))
    with pytest.raises(httpx.HTTPStatusError):
        adapter.fetch_submissions_payload("0000000001")


def test_exchange_fetch_sends_the_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, json=EXCHANGE_SAMPLE)

    _adapter(handler).fetch_company_tickers_exchange_payload()
    assert seen["ua"] == "test test@example.com"
