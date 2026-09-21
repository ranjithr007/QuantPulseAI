"""Report the smallest symbol/date scope needed for Regime Trend replay."""

import json
import os

from sqlalchemy import create_engine, text

from app.database.runtime import normalize_database_url


def main():
    url = os.getenv("QUANTPULSE_DATABASE_URL")
    if not url:
        raise SystemExit("QUANTPULSE_DATABASE_URL is required")
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True)
    query = text(
        """
        SELECT symbol, MIN(opened_at) AS first_entry,
               MAX(opened_at) AS last_entry, COUNT(*) AS trades
        FROM paper_trades
        WHERE strategy_id = 'REGIME_TREND'
        GROUP BY symbol
        ORDER BY trades DESC, symbol
        """
    )
    with engine.connect() as connection:
        rows = [
            {
                "symbol": row.symbol,
                "first_entry": row.first_entry.isoformat() if row.first_entry else None,
                "last_entry": row.last_entry.isoformat() if row.last_entry else None,
                "trades": int(row.trades),
            }
            for row in connection.execute(query)
        ]
    print(json.dumps({"strategy": "REGIME_TREND", "symbols": rows}, indent=2))


if __name__ == "__main__":
    main()
