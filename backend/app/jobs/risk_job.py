from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from app.backtesting.walk_forward_validator import is_phase2_official_timeframe
from app.database.models.automation_settings import AutomationSetting
from app.database.sqlserver import SessionLocal
from app.database.models.market_features import MarketFeature

from app.repositories.candle_repository import (
    get_latest_candle as latest_market_candle,
)
from app.repositories.master_signal_repository import MasterSignalRepository
from app.repositories.risk_repository import RiskRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.repositories._db_utils import safe_rollback

from app.risk.risk_engine import RiskEngine

from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


@dataclass(frozen=True)
class RiskJobConfig:
    """
    Runtime configuration for the Risk Job.

    RiskEngine remains responsible for:
    - minimum confidence
    - stop-loss calculation
    - target calculation
    - risk/reward validation
    - position sizing
    - final TAKE_TRADE / REJECT decision

    RiskJob is responsible for:
    - selecting the correct Master AI signal
    - checking signal freshness
    - loading point-in-time candle and ATR data
    - blocking invalid or stale input
    - persistence and lineage
    """

    default_timeframe: str = "1h"

    # Signal is considered stale after this many completed bars.
    master_signal_max_age_bars: int = 3

    # Latest market candle should not be older than this.
    candle_max_age_bars: int = 3

    # ATR/feature snapshot should not be older than this.
    feature_max_age_bars: int = 4

    # A synthetic ATR should normally be disabled in production.
    allow_atr_fallback: bool = False
    default_atr_percent: float = 0.01

    # Used by analyze_trade_plan().
    trade_plan_risk_percent: float = 1.0

    # Set to False when trade-plan validation is moved to a separate job.
    validate_trade_plans: bool = True

    # Prevent repeated risk decisions for the same thesis/source signal.
    skip_duplicate_signals: bool = True


class RiskInputError(Exception):
    """Raised when risk inputs are unavailable, stale, or invalid."""


class RiskJob:
    """
    Orchestrates pre-trade risk decisions.

    Authoritative direction:
        Master AI signal

    Market execution inputs:
        Latest candle price
        Latest ATR feature
        Master AI confidence
        Master AI trade_allowed gate

    Risk output:
        TAKE_TRADE or REJECT
        Entry
        Stop loss
        Targets
        Risk/reward
        Position size
    """

    def __init__(
        self,
        config: RiskJobConfig | None = None,
        session_factory=SessionLocal,
        master_repo: MasterSignalRepository | None = None,
        risk_repo: RiskRepository | None = None,
        trade_plan_repo: TradePlanRepository | None = None,
        engine: RiskEngine | None = None,
    ):
        self.config = config or RiskJobConfig()
        self.session_factory = session_factory

        self.master_repo = master_repo or MasterSignalRepository()
        self.risk_repo = risk_repo or RiskRepository()
        self.trade_plan_repo = trade_plan_repo or TradePlanRepository()
        self.engine = engine or RiskEngine()
        self._active_risk_percent = self.config.trade_plan_risk_percent

    def run(self) -> dict[str, Any]:
        db = self.session_factory()
        summary = self._create_summary()

        try:
            self._active_risk_percent = self._configured_max_risk_percent(db)
            master_signals = self.master_repo.get_latest_signals(
                db,
                timeframe=self.config.default_timeframe,
            )
            master_signals = self._deduplicate_master_signals(master_signals)

            for master_signal in master_signals:
                self._process_master_signal(
                    db=db,
                    master_signal=master_signal,
                    summary=summary,
                )

            if self.config.validate_trade_plans:
                summary["trade_plans"] = self._approve_trade_plans(db)

            print("Risk Engine Completed", summary)
            return summary

        except Exception as ex:
            safe_rollback(db)

            error_message = summarize_network_error(ex)
            summary["errors"].append(error_message)

            if not is_transient_network_error(ex):
                print("Risk job error:", error_message)

            return summary

        finally:
            db.close()

    def _process_master_signal(
        self,
        db,
        master_signal,
        summary: dict[str, Any],
    ) -> None:
        symbol = self._get_required_text(master_signal, "symbol")
        timeframe = (
            self._get_value(master_signal, "timeframe")
            or self.config.default_timeframe
        )

        summary["processed"] += 1

        try:
            normalized_signal = self._normalize_master_decision(
                self._first_value(
                    master_signal,
                    "decision",
                    "signal",
                    "final_decision",
                    "final_signal",
                )
            )

            confidence = self._normalize_confidence(
                self._first_value(
                    master_signal,
                    "confidence",
                    "final_confidence",
                    "score",
                )
            )

            thesis_id = self._get_value(master_signal, "thesis_id")
            master_signal_id = self._first_value(
                master_signal,
                "id",
                "master_signal_id",
            )

            source_timestamp = self._extract_timestamp(
                master_signal,
                "source_timestamp",
                "effective_timestamp",
                "created_at",
                "CreatedAt",
                "generated_at",
                "timestamp",
            )

            if (
                self.config.skip_duplicate_signals
                and self._already_processed(
                    db=db,
                    symbol=symbol,
                    signal=normalized_signal,
                    thesis_id=thesis_id,
                    source_timestamp=source_timestamp,
                )
            ):
                summary["duplicates"] += 1
                return

            trade_allowed = self._resolve_trade_allowed(master_signal)

            if trade_allowed is False:
                result = self._build_rejection(
                    symbol=symbol,
                    signal=normalized_signal,
                    confidence=confidence,
                    timeframe=timeframe,
                    reason="Master AI blocked the trade",
                )

            elif self._is_stale(
                timestamp=source_timestamp,
                timeframe=timeframe,
                maximum_bars=self.config.master_signal_max_age_bars,
            ):
                result = self._build_rejection(
                    symbol=symbol,
                    signal=normalized_signal,
                    confidence=confidence,
                    timeframe=timeframe,
                    reason="Master AI signal is stale",
                )

            else:
                inputs = self._resolve_market_inputs(
                    db=db,
                    symbol=symbol,
                    timeframe=timeframe,
                )

                result = self.engine.analyze(
                    symbol=symbol,
                    signal=normalized_signal,
                    price=inputs["price"],
                    atr=inputs["atr"],
                    confidence=confidence,
                    risk_percent=self._active_risk_percent,
                )

                result["market_price"] = inputs["price"]
                result["atr"] = inputs["atr"]
                result["atr_source"] = inputs["atr_source"]
                result["candle_timestamp"] = inputs["candle_timestamp"]
                result["feature_timestamp"] = inputs["feature_timestamp"]

            self._enrich_result(
                result=result,
                symbol=symbol,
                signal=normalized_signal,
                timeframe=timeframe,
                confidence=confidence,
                thesis_id=thesis_id,
                master_signal_id=master_signal_id,
                source_timestamp=source_timestamp,
                decision_type="MASTER_SIGNAL_RISK",
            )

            self._persist_result(db, result)

            summary["persisted"] += 1

            if result.get("decision") == "TAKE_TRADE":
                # Kept for compatibility with your existing summary.
                summary["saved"] += 1
                summary["approved"] += 1
            else:
                summary["rejected"] += 1

        except RiskInputError as ex:
            safe_rollback(db)

            rejection = self._build_rejection(
                symbol=symbol,
                signal=self._normalize_master_decision(
                    self._first_value(
                        master_signal,
                        "decision",
                        "signal",
                        "final_decision",
                    )
                ),
                confidence=self._normalize_confidence(
                    self._get_value(master_signal, "confidence")
                ),
                timeframe=timeframe,
                reason=str(ex),
            )

            self._enrich_result(
                result=rejection,
                symbol=symbol,
                signal=rejection["signal"],
                timeframe=timeframe,
                confidence=rejection["confidence"],
                thesis_id=self._get_value(master_signal, "thesis_id"),
                master_signal_id=self._first_value(
                    master_signal,
                    "id",
                    "master_signal_id",
                ),
                source_timestamp=self._extract_timestamp(
                    master_signal,
                    "source_timestamp",
                    "created_at",
                    "CreatedAt",
                ),
                decision_type="MASTER_SIGNAL_RISK",
            )

            try:
                self._persist_result(db, rejection)
                summary["persisted"] += 1
                summary["rejected"] += 1
            except Exception as save_error:
                safe_rollback(db)
                summary["skipped"] += 1
                summary["errors"].append(
                    f"{symbol} {timeframe}: "
                    f"{summarize_network_error(save_error)}"
                )

            summary["warnings"].append(
                f"{symbol} {timeframe}: {str(ex)}"
            )

        except Exception as ex:
            safe_rollback(db)

            summary["failed"] += 1
            summary["errors"].append(
                f"{symbol} {timeframe}: "
                f"{summarize_network_error(ex)}"
            )

    def _resolve_market_inputs(
        self,
        db,
        symbol: str,
        timeframe: str,
    ) -> dict[str, Any]:
        candle = latest_market_candle(db, symbol, timeframe)

        if candle is None:
            raise RiskInputError(
                f"No latest market candle for {symbol} {timeframe}"
            )

        price = self._to_positive_float(
            self._first_value(
                candle,
                "close_price",
                "close",
                "Close",
                "ClosePrice",
            )
        )

        if price is None:
            raise RiskInputError(
                f"Invalid candle close price for {symbol} {timeframe}"
            )

        candle_timestamp = self._extract_timestamp(
            candle,
            "close_time",
            "candle_time",
            "open_time",
            "timestamp",
            "created_at",
            "CreatedAt",
        )

        if self._is_stale(
            timestamp=candle_timestamp,
            timeframe=timeframe,
            maximum_bars=self.config.candle_max_age_bars,
        ):
            raise RiskInputError(
                f"Latest market candle is stale for {symbol} {timeframe}"
            )

        feature = self._get_latest_feature(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
        )

        atr = None
        atr_source = "MARKET_FEATURE"
        feature_timestamp = None

        if feature is not None:
            atr = self._to_positive_float(
                self._first_value(
                    feature,
                    "ATR",
                    "atr",
                    "AverageTrueRange",
                    "average_true_range",
                )
            )

            feature_timestamp = self._extract_timestamp(
                feature,
                "CreatedAt",
                "created_at",
                "FeatureTime",
                "feature_time",
                "timestamp",
            )

            if atr is not None and self._is_stale(
                timestamp=feature_timestamp,
                timeframe=timeframe,
                maximum_bars=self.config.feature_max_age_bars,
            ):
                raise RiskInputError(
                    f"ATR feature is stale for {symbol} {timeframe}"
                )

        if atr is None:
            if not self.config.allow_atr_fallback:
                raise RiskInputError(
                    f"No valid ATR available for {symbol} {timeframe}"
                )

            atr = price * self.config.default_atr_percent
            atr_source = "PRICE_PERCENT_FALLBACK"

        if atr <= 0:
            raise RiskInputError(
                f"ATR must be greater than zero for {symbol} {timeframe}"
            )
            atr = price * self.config.default_atr_percent
            atr_source = "PRICE_PERCENT_FALLBACK"

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": price,
            "atr": atr,
            "atr_source": atr_source,
            "candle_timestamp": candle_timestamp,
            "feature_timestamp": feature_timestamp,
        }

    def _get_latest_feature(
        self,
        db,
        symbol: str,
        timeframe: str,
    ):
        query = db.query(MarketFeature).filter(
            MarketFeature.Symbol == symbol,
            MarketFeature.Timeframe == timeframe,
        )

        if hasattr(MarketFeature, "CreatedAt"):
            query = query.order_by(MarketFeature.CreatedAt.desc())
        elif hasattr(MarketFeature, "created_at"):
            query = query.order_by(MarketFeature.created_at.desc())

        return query.first()

    def _approve_trade_plans(self, db) -> dict[str, Any]:
        summary = {
            "processed": 0,
            "persisted": 0,
            "approved": 0,
            "rejected": 0,
            "failed": 0,
            "errors": [],
        }

        trades = [
            trade
            for trade in self.trade_plan_repo.get_open_trades(db)
            if is_phase2_official_timeframe(
                self._get_value(trade, "entry_timeframe")
                or self._get_value(trade, "timeframe")
                or self.config.default_timeframe
            )
        ]

        for trade in trades:
            symbol = self._get_required_text(trade, "symbol")
            side = self._normalize_trade_side(
                self._get_value(trade, "side")
            )
            timeframe = (
                self._get_value(trade, "entry_timeframe")
                or self._get_value(trade, "timeframe")
                or self.config.default_timeframe
            )

            summary["processed"] += 1

            try:
                result = self.engine.analyze_trade_plan(
                    symbol=symbol,
                    side=side,
                    entry=self._to_required_float(
                        self._get_value(trade, "entry_price"),
                        "entry_price",
                    ),
                    stop_loss=self._to_required_float(
                        self._get_value(trade, "stop_loss"),
                        "stop_loss",
                    ),
                    target1=self._to_required_float(
                        self._get_value(trade, "target1"),
                        "target1",
                    ),
                    target2=self._to_optional_float(
                        self._get_value(trade, "target2")
                    ),
                    confidence=self._normalize_confidence(
                        self._get_value(trade, "confidence")
                    ),
                    risk_percent=self._active_risk_percent,
                )

                confidence = self._normalize_confidence(
                    self._get_value(trade, "confidence")
                )

                result["symbol"] = symbol
                result["signal"] = side
                result["confidence"] = confidence

                if not result.get("targets"):
                    result["targets"] = {
                        "t1": self._get_value(trade, "target1"),
                        "t2": self._get_value(trade, "target2"),
                    }

                self._enrich_result(
                    result=result,
                    symbol=symbol,
                    signal=side,
                    timeframe=timeframe,
                    confidence=confidence,
                    thesis_id=self._get_value(trade, "thesis_id"),
                    master_signal_id=None,
                    source_timestamp=self._extract_timestamp(
                        trade,
                        "updated_at",
                        "created_at",
                        "CreatedAt",
                    ),
                    decision_type="TRADE_PLAN_APPROVAL",
                )

                result["trade_plan_id"] = self._first_value(
                    trade,
                    "id",
                    "trade_plan_id",
                )

                self._persist_result(db, result)
                summary["persisted"] += 1

                if result.get("decision") == "APPROVE":
                    summary["approved"] += 1
                else:
                    summary["rejected"] += 1
                    summary["errors"].append(
                        f"{symbol} {side}: "
                        f"{result.get('reason') or 'Risk validation failed'}"
                    )

            except Exception as ex:
                safe_rollback(db)

                summary["failed"] += 1
                summary["rejected"] += 1
                summary["errors"].append(
                    f"{symbol} {side}: "
                    f"{summarize_network_error(ex)}"
                )

        return summary

    def _configured_max_risk_percent(self, db) -> float:
        """Use the persisted paper-trading maximum when a real DB is supplied."""
        try:
            row = (
                db.query(AutomationSetting)
                .filter(AutomationSetting.id == 1)
                .first()
            )
            value = float(row.max_risk_per_trade) if row is not None else None
        except (AttributeError, TypeError, ValueError):
            value = None

        if value is None or not 0 < value <= 100:
            return float(self.config.trade_plan_risk_percent)
        return value

    def _persist_result(self, db, result: dict[str, Any]) -> None:
        """
        RiskRepository must use the supplied session.

        The repository should flush but must not create an unrelated
        database session when called from this job.
        """

        self.risk_repo.save(
            result,
            db=db,
            commit=False,
        )

        db.commit()

    def _already_processed(
        self,
        db,
        symbol: str,
        signal: str,
        thesis_id,
        source_timestamp: datetime | None,
    ) -> bool:
        latest = self.risk_repo.latest_for_symbol(db, symbol)

        if latest is None:
            return False

        latest_thesis_id = self._get_value(latest, "thesis_id")
        latest_signal = self._get_value(latest, "signal")
        latest_created_at = self._as_datetime(
            self._get_value(latest, "created_at")
        )

        if (
            thesis_id is not None
            and latest_thesis_id is not None
            and str(thesis_id) == str(latest_thesis_id)
            and self._normalize_master_decision(latest_signal) == signal
        ):
            return True

        if (
            source_timestamp is not None
            and latest_created_at is not None
            and latest_created_at >= source_timestamp
            and self._normalize_master_decision(latest_signal) == signal
        ):
            return True

        return False

    def _deduplicate_master_signals(self, signals) -> list[Any]:
        """
        Ensures only one Master AI signal per symbol/timeframe is processed.

        This protects the job even when the repository accidentally returns
        more than one row.
        """

        latest_by_key: dict[tuple[str, str], Any] = {}

        for signal in signals or []:
            symbol = self._get_value(signal, "symbol")

            if not symbol:
                continue

            timeframe = (
                self._get_value(signal, "timeframe")
                or self.config.default_timeframe
            )

            key = (str(symbol).upper(), str(timeframe).lower())
            existing = latest_by_key.get(key)

            if existing is None:
                latest_by_key[key] = signal
                continue

            existing_time = self._extract_timestamp(
                existing,
                "source_timestamp",
                "created_at",
                "CreatedAt",
            )

            current_time = self._extract_timestamp(
                signal,
                "source_timestamp",
                "created_at",
                "CreatedAt",
            )

            if existing_time is None:
                latest_by_key[key] = signal
            elif current_time is not None and current_time > existing_time:
                latest_by_key[key] = signal

        return list(latest_by_key.values())

    def _enrich_result(
        self,
        result: dict[str, Any],
        symbol: str,
        signal: str,
        timeframe: str,
        confidence: float,
        thesis_id,
        master_signal_id,
        source_timestamp: datetime | None,
        decision_type: str,
    ) -> None:
        result["symbol"] = symbol
        result["signal"] = signal
        result["timeframe"] = timeframe
        result["confidence"] = confidence
        result["thesis_id"] = thesis_id

        result["source_type"] = "MASTER_AI"
        result["source_signal_id"] = master_signal_id
        result["decision_type"] = decision_type

        result["source_timestamp"] = (
            source_timestamp or self._utc_now()
        )
        result["effective_timestamp"] = self._utc_now()

        context = getattr(self, "_pipeline_context", None)
        if context is not None:
            result["data_generation_id"] = context.generation_id
            result["source_cutoff"] = context.source_cutoff

        result.setdefault("risk_percent", 1.0)
        result.setdefault("targets", {})

    def _build_rejection(
        self,
        symbol: str,
        signal: str,
        confidence: float,
        timeframe: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "signal": signal,
            "decision": "REJECT",
            "entry": None,
            "stop_loss": None,
            "targets": {
                "t1": None,
                "t2": None,
            },
            "position_size": None,
            "risk_reward": None,
            "confidence": confidence,
            "risk_percent": 1.0,
            "timeframe": timeframe,
            "reason": reason,
        }

    def _resolve_trade_allowed(self, master_signal) -> bool:
        """
        If MasterSignal has no trade_allowed column, the decision itself
        remains authoritative.

        If trade_allowed exists, unknown values are rejected conservatively.
        """

        if not hasattr(master_signal, "trade_allowed"):
            return True

        value = getattr(master_signal, "trade_allowed", None)

        if value is None:
            return False

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value > 0

        normalized = str(value).strip().upper()

        allowed_values = {
            "TRUE",
            "YES",
            "Y",
            "1",
            "ALLOW",
            "ALLOWED",
            "APPROVE",
            "APPROVED",
            "TAKE_TRADE",
        }

        blocked_values = {
            "FALSE",
            "NO",
            "N",
            "0",
            "BLOCK",
            "BLOCKED",
            "REJECT",
            "REJECTED",
            "NOT_ALLOWED",
            "WAIT",
            "HOLD",
        }

        if normalized in allowed_values:
            return True

        if normalized in blocked_values:
            return False

        # Unknown values must not accidentally permit a live trade.
        return False

    @staticmethod
    def _normalize_master_decision(decision) -> str:
        normalized = str(decision or "").strip().upper()

        if normalized in {
            "STRONG_LONG",
            "LONG",
            "BUY",
            "BULLISH",
        }:
            return "LONG"

        if normalized in {
            "STRONG_SHORT",
            "SHORT",
            "SELL",
            "BEARISH",
        }:
            return "SHORT"

        return "WAIT"

    @staticmethod
    def _normalize_trade_side(side) -> str:
        normalized = str(side or "").strip().upper()

        if normalized in {"LONG", "BUY"}:
            return "LONG"

        if normalized in {"SHORT", "SELL"}:
            return "SHORT"

        raise RiskInputError(f"Unsupported trade side: {side}")

    @staticmethod
    def _normalize_confidence(value) -> float:
        try:
            confidence = float(value or 0)
        except (TypeError, ValueError):
            return 0.0

        # Support models returning confidence between 0 and 1.
        if 0 < confidence <= 1:
            confidence *= 100

        return max(0.0, min(confidence, 100.0))

    def _is_stale(
        self,
        timestamp: datetime | None,
        timeframe: str,
        maximum_bars: int,
    ) -> bool:
        if timestamp is None:
            # Missing timestamps should be handled by repository/schema
            # hardening, but do not classify them as stale automatically.
            return False

        maximum_age = (
            self._timeframe_to_timedelta(timeframe) * maximum_bars
        )

        return self._utc_now() - timestamp > maximum_age

    @staticmethod
    def _timeframe_to_timedelta(timeframe: str) -> timedelta:
        value = str(timeframe or "").strip().lower()
        match = re.fullmatch(r"(\d+)([mhdw])", value)

        if match is None:
            raise RiskInputError(
                f"Unsupported timeframe format: {timeframe}"
            )

        amount = int(match.group(1))
        unit = match.group(2)

        if unit == "m":
            return timedelta(minutes=amount)

        if unit == "h":
            return timedelta(hours=amount)

        if unit == "d":
            return timedelta(days=amount)

        if unit == "w":
            return timedelta(weeks=amount)

        raise RiskInputError(
            f"Unsupported timeframe unit: {timeframe}"
        )

    def _extract_timestamp(
        self,
        obj,
        *attribute_names: str,
    ) -> datetime | None:
        value = self._first_value(obj, *attribute_names)
        return self._as_datetime(value)

    @staticmethod
    def _as_datetime(value) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(
                    tzinfo=None
                )

            return value

        if isinstance(value, (int, float)):
            timestamp = float(value)

            # Convert milliseconds to seconds.
            if timestamp > 10_000_000_000:
                timestamp /= 1000

            return datetime.utcfromtimestamp(timestamp)

        if isinstance(value, str):
            normalized = value.strip()

            if not normalized:
                return None

            normalized = normalized.replace("Z", "+00:00")

            try:
                parsed = datetime.fromisoformat(normalized)

                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(
                        timezone.utc
                    ).replace(tzinfo=None)

                return parsed
            except ValueError:
                return None

        return None

    @staticmethod
    def _to_positive_float(value) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if result <= 0:
            return None

        return result

    @staticmethod
    def _to_required_float(value, field_name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise RiskInputError(
                f"{field_name} is missing or invalid"
            )

        if result <= 0:
            raise RiskInputError(
                f"{field_name} must be greater than zero"
            )

        return result

    @staticmethod
    def _to_optional_float(value) -> float | None:
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_value(obj, *attribute_names: str):
        for attribute_name in attribute_names:
            value = RiskJob._get_value(obj, attribute_name)

            if value is not None:
                return value

        return None

    @staticmethod
    def _get_value(obj, attribute_name: str):
        if obj is None:
            return None

        if isinstance(obj, dict):
            return obj.get(attribute_name)

        return getattr(obj, attribute_name, None)

    @staticmethod
    def _get_required_text(obj, attribute_name: str) -> str:
        value = RiskJob._get_value(obj, attribute_name)

        if value is None or not str(value).strip():
            raise RiskInputError(
                f"Missing required field: {attribute_name}"
            )

        return str(value).strip().upper()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _create_summary() -> dict[str, Any]:
        return {
            "source": "MASTER_AI",
            "processed": 0,

            # TAKE_TRADE decisions. Retains old summary behaviour.
            "saved": 0,

            # All successfully persisted decisions.
            "persisted": 0,

            "approved": 0,
            "rejected": 0,
            "skipped": 0,
            "duplicates": 0,
            "failed": 0,
            "warnings": [],
            "errors": [],
            "trade_plans": {
                "processed": 0,
                "persisted": 0,
                "approved": 0,
                "rejected": 0,
                "failed": 0,
                "errors": [],
            },
        }
    def normalize_risk_signal(decision):
        normalized = str(decision or "").strip().upper()

        if normalized in LONG_DECISIONS:
            return "LONG"

        if normalized in SHORT_DECISIONS:
            return "SHORT"

        return "WAIT"
LONG_DECISIONS = {"BULLISH", "STRONG_LONG", "LONG", "BUY"}
SHORT_DECISIONS = {"BEARISH", "STRONG_SHORT", "SHORT", "SELL"}

def run_risk_job(*, context=None):
    """
    APScheduler-compatible entry point.
    """

    job = RiskJob()
    job._pipeline_context = context
    return job.run()
