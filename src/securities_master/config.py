import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    sec_user_agent: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy .env.example to .env."
            )
        sec_user_agent = os.environ.get("SEC_USER_AGENT")
        if not sec_user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is not set. SEC EDGAR blocks requests that do "
                "not identify a contact email."
            )
        return cls(database_url=database_url, sec_user_agent=sec_user_agent)
