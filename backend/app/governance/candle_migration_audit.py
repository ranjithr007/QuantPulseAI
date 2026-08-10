import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

from sqlalchemy import text

from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.database.sqlserver import engine


AUDIT_VERSION = "r1_canonical_candle_audit_v2"


def build_candle_migration_audit(database_engine=engine):
    if database_engine.dialect.name != "mssql" or USING_SQLITE_FALLBACK:
        raise RuntimeError(
            "The canonical-candle migration audit requires the active SQL Server "
            "database and refuses SQLite fallback."
        )

    with database_engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    ) as connection:
        column_names = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo'
                      AND TABLE_NAME = 'market_candles'
                    """
                )
            )
        }
        summary = dict(
            connection.execute(
                text(
                    """
                    SELECT
                        COUNT_BIG(*) AS total_rows,
                        SUM(CASE WHEN symbol IS NULL OR LTRIM(RTRIM(symbol)) = '' THEN 1 ELSE 0 END) AS null_symbol_rows,
                        SUM(CASE WHEN timeframe IS NULL OR LTRIM(RTRIM(timeframe)) = '' THEN 1 ELSE 0 END) AS null_timeframe_rows,
                        SUM(CASE WHEN candle_time IS NULL THEN 1 ELSE 0 END) AS null_candle_time_rows,
                        SUM(CASE WHEN open_price IS NULL OR high_price IS NULL OR low_price IS NULL OR close_price IS NULL THEN 1 ELSE 0 END) AS null_ohlc_rows,
                        SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) AS null_volume_rows,
                        SUM(CASE WHEN volume < 0 THEN 1 ELSE 0 END) AS negative_volume_rows,
                        SUM(CASE WHEN high_price < low_price THEN 1 ELSE 0 END) AS inverted_high_low_rows,
                        SUM(CASE WHEN high_price < open_price OR high_price < close_price OR low_price > open_price OR low_price > close_price THEN 1 ELSE 0 END) AS invalid_ohlc_envelope_rows,
                        SUM(CASE WHEN candle_time > DATEADD(minute, 1, SYSUTCDATETIME()) THEN 1 ELSE 0 END) AS future_timestamp_rows,
                        MIN(candle_time) AS minimum_candle_time,
                        MAX(candle_time) AS maximum_candle_time
                    FROM market_candles
                    """
                )
            ).mappings().one()
        )
        legacy_duplicate_summary = dict(
            connection.execute(
                text(
                    """
                    SELECT
                        COUNT_BIG(*) AS duplicate_identity_groups,
                        COALESCE(SUM(identity_count - 1), 0) AS duplicate_extra_rows,
                        COALESCE(MAX(identity_count), 0) AS maximum_identity_count
                    FROM (
                        SELECT symbol, timeframe, candle_time, COUNT_BIG(*) AS identity_count
                        FROM market_candles
                        GROUP BY symbol, timeframe, candle_time
                        HAVING COUNT_BIG(*) > 1
                    ) duplicate_identities
                    """
                )
            ).mappings().one()
        )
        canonical_duplicate_summary = (
            dict(
                connection.execute(
                    text(
                        """
                        SELECT
                            COUNT_BIG(*) AS duplicate_identity_groups,
                            COALESCE(SUM(identity_count - 1), 0) AS duplicate_extra_rows,
                            COALESCE(MAX(identity_count), 0) AS maximum_identity_count
                        FROM (
                            SELECT
                                venue,
                                market_type,
                                symbol,
                                timeframe,
                                open_time,
                                COUNT_BIG(*) AS identity_count
                            FROM market_candles
                            WHERE open_time IS NOT NULL
                            GROUP BY
                                venue,
                                market_type,
                                symbol,
                                timeframe,
                                open_time
                            HAVING COUNT_BIG(*) > 1
                        ) duplicate_identities
                        """
                    )
                ).mappings().one()
            )
            if {
                "venue",
                "market_type",
                "open_time",
            }.issubset(column_names)
            else legacy_duplicate_summary
        )
        scopes = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        symbol,
                        timeframe,
                        COUNT_BIG(*) AS row_count,
                        COUNT_BIG(DISTINCT candle_time) AS distinct_open_times,
                        MIN(candle_time) AS minimum_candle_time,
                        MAX(candle_time) AS maximum_candle_time,
                        SUM(CASE WHEN volume = 0 THEN 1 ELSE 0 END) AS zero_volume_rows
                    FROM market_candles
                    GROUP BY symbol, timeframe
                    ORDER BY symbol, timeframe
                    """
                )
            ).mappings()
        ]
        duplicate_scopes = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        symbol,
                        timeframe,
                        COUNT_BIG(*) AS duplicate_identity_groups,
                        SUM(identity_count - 1) AS duplicate_extra_rows
                    FROM (
                        SELECT
                            symbol,
                            timeframe,
                            candle_time,
                            COUNT_BIG(*) AS identity_count
                        FROM market_candles
                        GROUP BY symbol, timeframe, candle_time
                        HAVING COUNT_BIG(*) > 1
                    ) duplicates
                    GROUP BY symbol, timeframe
                    ORDER BY symbol, timeframe
                    """
                )
            ).mappings()
        ]
        indexes = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        i.name AS index_name,
                        i.is_unique,
                        i.is_primary_key,
                        i.type_desc,
                        STRING_AGG(c.name, ',') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
                    FROM sys.indexes i
                    JOIN sys.index_columns ic
                        ON ic.object_id = i.object_id
                        AND ic.index_id = i.index_id
                        AND ic.is_included_column = 0
                    JOIN sys.columns c
                        ON c.object_id = ic.object_id
                        AND c.column_id = ic.column_id
                    WHERE i.object_id = OBJECT_ID('dbo.market_candles')
                    GROUP BY i.name, i.is_unique, i.is_primary_key, i.type_desc
                    ORDER BY i.name
                    """
                )
            ).mappings()
        ]
        canonical_summary = (
            dict(
                connection.execute(
                    text(
                        """
                        SELECT
                            SUM(CASE WHEN open_time IS NULL THEN 1 ELSE 0 END) AS null_open_time_rows,
                            SUM(CASE WHEN close_time IS NULL THEN 1 ELSE 0 END) AS null_close_time_rows,
                            SUM(CASE WHEN is_final = 1 THEN 1 ELSE 0 END) AS final_rows,
                            SUM(CASE WHEN is_final = 0 THEN 1 ELSE 0 END) AS provisional_rows,
                            SUM(CASE WHEN quality_state = 'VERIFIED' THEN 1 ELSE 0 END) AS verified_rows,
                            SUM(CASE WHEN quality_state = 'PROVISIONAL' THEN 1 ELSE 0 END) AS provisional_quality_rows,
                            SUM(CASE WHEN quality_state = 'LEGACY_UNVERIFIED' THEN 1 ELSE 0 END) AS legacy_unverified_rows,
                            SUM(CASE WHEN venue = 'UNKNOWN' THEN 1 ELSE 0 END) AS unknown_venue_rows,
                            SUM(CASE WHEN revision > 1 THEN 1 ELSE 0 END) AS revised_rows,
                            MAX(revision) AS maximum_revision,
                            MAX(updated_at) AS latest_canonical_update
                        FROM market_candles
                        """
                    )
                ).mappings().one()
            )
            if {
                "open_time",
                "close_time",
                "is_final",
                "quality_state",
                "venue",
                "revision",
                "updated_at",
            }.issubset(column_names)
            else None
        )

    duplicate_lookup = {
        (item.get("symbol"), item.get("timeframe")): item
        for item in duplicate_scopes
    }
    for scope in scopes:
        duplicates = duplicate_lookup.get(
            (scope.get("symbol"), scope.get("timeframe")),
            {},
        )
        scope["duplicate_identity_groups"] = int(
            duplicates.get("duplicate_identity_groups") or 0
        )
        scope["duplicate_extra_rows"] = int(
            duplicates.get("duplicate_extra_rows") or 0
        )

    blocking_issues = []
    if int(canonical_duplicate_summary.get("duplicate_extra_rows") or 0) > 0:
        blocking_issues.append("DUPLICATE_CANDLE_IDENTITIES")
    for field in (
        "null_symbol_rows",
        "null_timeframe_rows",
        "null_candle_time_rows",
        "null_ohlc_rows",
        "invalid_ohlc_envelope_rows",
        "future_timestamp_rows",
    ):
        if int(summary.get(field) or 0) > 0:
            blocking_issues.append(field.upper())
    if canonical_summary is not None:
        if int(canonical_summary.get("null_open_time_rows") or 0) > 0:
            blocking_issues.append("NULL_CANONICAL_OPEN_TIME")
        if int(canonical_summary.get("null_close_time_rows") or 0) > 0:
            blocking_issues.append("NULL_CANONICAL_CLOSE_TIME")

    return {
        "audit_version": AUDIT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {
            "database_name": "QuantPulseAI",
            "dialect": database_engine.dialect.name,
        },
        "identity_under_test": [
            "venue",
            "market_type",
            "symbol",
            "timeframe",
            "open_time",
        ],
        "legacy_identity": ["symbol", "timeframe", "candle_time"],
        "summary": summary,
        "canonical_summary": canonical_summary,
        "duplicates": canonical_duplicate_summary,
        "legacy_identity_overlaps": legacy_duplicate_summary,
        "scope_count": len(scopes),
        "scopes": scopes,
        "indexes": indexes,
        "blocking_issues": sorted(set(blocking_issues)),
        "migration_readiness": (
            (
                "CANONICAL_CONTRACT_READY"
                if not blocking_issues
                else "REQUIRES_CANONICAL_CLEANUP"
            )
            if canonical_summary is not None
            else (
                "READY_FOR_ADDITIVE_BACKFILL"
                if not blocking_issues
                else "REQUIRES_PRE_CONSTRAINT_CLEANUP"
            )
        ),
    }


def write_candle_migration_audit(output_path, database_engine=engine):
    audit = build_candle_migration_audit(database_engine)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit, indent=2, default=str),
        encoding="utf-8",
    )
    return audit


def _default_output_path():
    return (
        Path(__file__).resolve().parents[3]
        / "outputs"
        / "r1_canonical_candle_audit_2026-07-27.json"
    )


if __name__ == "__main__":
    result = write_candle_migration_audit(_default_output_path())
    print(
        json.dumps(
            {
                "audit_version": result["audit_version"],
                "migration_readiness": result["migration_readiness"],
                "summary": result["summary"],
                "duplicates": result["duplicates"],
                "scope_count": result["scope_count"],
                "blocking_issues": result["blocking_issues"],
            },
            indent=2,
            default=str,
        )
    )
