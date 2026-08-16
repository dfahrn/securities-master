from dataclasses import dataclass

import httpx

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass(frozen=True)
class CompanyTickerRecord:
    cik: int
    ticker: str
    title: str


class EdgarAdapter:
    """Fetches raw records from SEC EDGAR.

    Adapters fetch only. Normalisation and interpretation happen downstream,
    so that a parsing fix never requires re-downloading.
    """

    def __init__(self, user_agent: str, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=30.0
        )

    def fetch_company_tickers_payload(self) -> dict:
        response = self._client.get(COMPANY_TICKERS_URL)
        response.raise_for_status()
        return response.json()

    def fetch_company_tickers(self) -> list[CompanyTickerRecord]:
        payload = self.fetch_company_tickers_payload()
        return [
            CompanyTickerRecord(
                cik=int(row["cik_str"]),
                ticker=str(row["ticker"]).upper(),
                title=str(row["title"]),
            )
            for row in payload.values()
        ]
