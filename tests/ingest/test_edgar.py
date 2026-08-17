import httpx
import pytest

from securities_master.ingest.base import payload_hash
from securities_master.ingest.edgar import EdgarAdapter

SAMPLE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}


def _adapter(handler) -> EdgarAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        transport=transport, headers={"User-Agent": "test test@example.com"}
    )
    return EdgarAdapter(user_agent="test test@example.com", client=client)


def test_fetch_company_tickers_parses_records():
    adapter = _adapter(lambda request: httpx.Response(200, json=SAMPLE))
    records = adapter.fetch_company_tickers()
    assert len(records) == 2
    assert records[0].cik == 320193
    assert records[0].ticker == "AAPL"
    assert records[0].title == "Apple Inc."


def test_sends_user_agent_header():
    """SEC blocks requests that do not identify a contact."""
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, json=SAMPLE)

    _adapter(handler).fetch_company_tickers()
    assert seen["ua"] == "test test@example.com"


def test_raises_on_http_error():
    adapter = _adapter(lambda request: httpx.Response(403, text="Forbidden"))
    with pytest.raises(httpx.HTTPStatusError):
        adapter.fetch_company_tickers()


def test_payload_hash_is_stable_and_order_independent():
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})
