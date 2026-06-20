import os
from functools import lru_cache


DEFAULT_SCHEDULER_JOBS = ["market", "feature", "regime", "orderflow", "smc"]
DEFAULT_LIVE_MARKET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]


class Settings:
    app_name = "QuantPulse AI"
    version = "3.0"

    def __init__(self):
        self.environment = os.getenv("QUANTPULSE_ENV", "development")
        self.start_scheduler = _env_bool("QUANTPULSE_START_SCHEDULER", True)
        self.start_live_market = _env_bool("QUANTPULSE_START_LIVE_MARKET", True)
        self.live_market_symbols = _env_list(
            "QUANTPULSE_LIVE_MARKET_SYMBOLS",
            DEFAULT_LIVE_MARKET_SYMBOLS,
        )
        self.scheduler_job_ids = _env_list(
            "QUANTPULSE_SCHEDULER_JOBS",
            DEFAULT_SCHEDULER_JOBS,
        )
        self.database_url = os.getenv("QUANTPULSE_DATABASE_URL") or _build_sqlserver_url()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_sqlserver_url() -> str:
    server = os.getenv("QUANTPULSE_SQLSERVER", r"(localdb)\MSSQLLocalDB")
    database = os.getenv("QUANTPULSE_DATABASE", "QuantPulseAI")
    driver = os.getenv("QUANTPULSE_SQL_DRIVER", "ODBC Driver 17 for SQL Server")
    trusted_connection = os.getenv("QUANTPULSE_SQL_TRUSTED_CONNECTION", "yes")
    encrypt = os.getenv("QUANTPULSE_SQL_ENCRYPT", "no")
    trust_server_certificate = os.getenv(
        "QUANTPULSE_SQL_TRUST_SERVER_CERTIFICATE",
        "yes",
    )

    return (
        f"mssql+pyodbc://@{server}/{database}"
        f"?driver={driver.replace(' ', '+')}"
        f"&trusted_connection={trusted_connection}"
        f"&Encrypt={encrypt}"
        f"&TrustServerCertificate={trust_server_certificate}"
    )


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
