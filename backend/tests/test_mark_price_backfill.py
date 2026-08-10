from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.governance.mark_price_backfill import backfill_mark_prices
from app.governance.mark_price_backfill import load_checkpoint


def test_mark_price_backfill_is_resumable_and_checkpoints_each_batch(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=3)
    first_close = start + timedelta(hours=1)
    second_close = start + timedelta(hours=2)
    collector = Mock()
    collector.get_klines.side_effect = [
        [{"close_time": first_close}],
        [{"close_time": second_close}],
        [],
    ]
    repository = Mock()
    db = Mock()
    checkpoint_path = tmp_path / "mark-prices.json"

    result = backfill_mark_prices(
        symbols=["DOGEUSDT"],
        timeframes=["1h"],
        start=start,
        end=end,
        checkpoint_path=checkpoint_path,
        collector=collector,
        repository=repository,
        session_factory=lambda: db,
    )

    checkpoint = load_checkpoint(checkpoint_path)
    scope = checkpoint["scopes"]["DOGEUSDT:1h"]
    assert result["status"] == "COMPLETE"
    assert result["rows_processed"] == 2
    assert repository.save_mark_prices.call_count == 2
    assert scope["status"] == "COMPLETE_FINAL_BOUNDARY"
    assert scope["rows"] == 2
    assert db.close.called


def test_mark_price_backfill_dry_run_has_no_database_or_network_side_effects(
    tmp_path,
):
    session_factory = Mock()
    collector = Mock()

    result = backfill_mark_prices(
        symbols=["DOGEUSDT"],
        timeframes=["1h", "4h", "1d"],
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        checkpoint_path=tmp_path / "checkpoint.json",
        collector=collector,
        session_factory=session_factory,
        dry_run=True,
    )

    assert result["status"] == "DRY_RUN"
    assert len(result["scopes"]) == 3
    session_factory.assert_not_called()
    collector.get_klines.assert_not_called()
