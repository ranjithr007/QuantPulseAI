import os
from functools import lru_cache


DEFAULT_SCHEDULER_JOBS = [
    "deterministic_pipeline",
    "derivative",
    "candle_completeness",
]
DEFAULT_LIVE_MARKET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
DEFAULT_DEVELOPMENT_ORIGINS = [
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    *[f"http://127.0.0.1:{port}" for port in range(5173, 5180)],
    *[f"http://localhost:{port}" for port in range(5173, 5180)],
]


class Settings:
    app_name = "QuantPulse AI"
    version = "3.0"

    def __init__(self):
        self.environment = os.getenv("QUANTPULSE_ENV", "development").strip().lower()
        self.process_role = _env_choice(
            "QUANTPULSE_PROCESS_ROLE",
            "all",
            {"all", "api", "worker"},
        )
        self.host = os.getenv("QUANTPULSE_HOST", "127.0.0.1").strip()
        self.port = int(os.getenv("PORT") or os.getenv("QUANTPULSE_PORT") or "8000")
        self.start_scheduler = _env_bool("QUANTPULSE_START_SCHEDULER", True)
        self.start_live_market = _env_bool("QUANTPULSE_START_LIVE_MARKET", True)
        self.run_scheduler = self.start_scheduler and self.process_role in {"all", "worker"}
        self.run_live_market = self.start_live_market and self.process_role in {"all", "api"}
        self.allow_sqlite_fallback = _env_bool(
            "QUANTPULSE_ALLOW_SQLITE_FALLBACK",
            self.environment != "production",
        )
        self.allowed_origins = _env_list(
            "QUANTPULSE_ALLOWED_ORIGINS",
            DEFAULT_DEVELOPMENT_ORIGINS if self.environment != "production" else [],
        )
        self.require_admin_auth = _env_bool(
            "QUANTPULSE_REQUIRE_ADMIN_AUTH",
            self.environment == "production",
        )
        self.admin_api_key = os.getenv("QUANTPULSE_ADMIN_API_KEY", "").strip()
        self.require_app_auth = _env_bool("QUANTPULSE_REQUIRE_APP_AUTH", False)
        self.app_username = os.getenv("QUANTPULSE_APP_USERNAME", "").strip()
        self.app_password_hash = os.getenv("QUANTPULSE_APP_PASSWORD_HASH", "").strip()
        self.app_session_secret = os.getenv("QUANTPULSE_APP_SESSION_SECRET", "").strip()
        self.app_session_ttl_seconds = int(
            os.getenv("QUANTPULSE_APP_SESSION_TTL_SECONDS", "43200")
        )
        self.rate_limit_enabled = _env_bool(
            "QUANTPULSE_RATE_LIMIT_ENABLED",
            self.environment == "production",
        )
        self.rate_limit_per_minute = int(
            os.getenv("QUANTPULSE_RATE_LIMIT_PER_MINUTE", "120")
        )
        self.admin_rate_limit_per_minute = int(
            os.getenv("QUANTPULSE_ADMIN_RATE_LIMIT_PER_MINUTE", "30")
        )
        self.trust_proxy_headers = _env_bool(
            "QUANTPULSE_TRUST_PROXY_HEADERS",
            self.environment == "production",
        )
        self.live_market_symbols = _env_list(
            "QUANTPULSE_LIVE_MARKET_SYMBOLS",
            DEFAULT_LIVE_MARKET_SYMBOLS,
        )
        self.scheduler_job_ids = _env_list(
            "QUANTPULSE_SCHEDULER_JOBS",
            DEFAULT_SCHEDULER_JOBS,
        )
        self.database_url = os.getenv("QUANTPULSE_DATABASE_URL") or _build_sqlserver_url()
        self.binance_api_key = os.getenv("QUANTPULSE_BINANCE_API_KEY")
        self.binance_api_secret = os.getenv("QUANTPULSE_BINANCE_API_SECRET")
        self.fred_api_key = (
            os.getenv("FRED_API_KEY")
            or os.getenv("QUANTPULSE_FRED_API_KEY")
            or ""
        ).strip()
        self.fred_timeout_seconds = int(os.getenv("FRED_TIMEOUT_SECONDS", "10"))
        self.fred_cache_seconds = int(os.getenv("FRED_CACHE_SECONDS", "1800"))

    def validate_runtime(self):
        if (
            self.process_role in {"all", "api"}
            and self.require_admin_auth
            and len(self.admin_api_key) < 32
        ):
            raise RuntimeError(
                "QUANTPULSE_ADMIN_API_KEY must contain at least 32 characters "
                "when admin authentication is required."
            )
        if self.rate_limit_per_minute < 1 or self.admin_rate_limit_per_minute < 1:
            raise RuntimeError(
                "QUANTPULSE_RATE_LIMIT_PER_MINUTE and "
                "QUANTPULSE_ADMIN_RATE_LIMIT_PER_MINUTE must be positive integers."
            )
        if self.require_app_auth:
            if not self.app_username:
                raise RuntimeError("QUANTPULSE_APP_USERNAME is required when app authentication is enabled.")
            if not self.app_password_hash.startswith("pbkdf2_sha256$"):
                raise RuntimeError(
                    "QUANTPULSE_APP_PASSWORD_HASH must be a pbkdf2_sha256 hash when app authentication is enabled."
                )
            if len(self.app_session_secret) < 32:
                raise RuntimeError(
                    "QUANTPULSE_APP_SESSION_SECRET must contain at least 32 characters when app authentication is enabled."
                )
            if self.app_session_ttl_seconds < 300:
                raise RuntimeError("QUANTPULSE_APP_SESSION_TTL_SECONDS must be at least 300 seconds.")


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


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {allowed}")
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
