from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.paper_wallet_ledger import PaperWalletLedgerEntry
from app.repositories.paper_wallet_ledger_repository import PaperWalletLedgerRepository


def test_wallet_ledger_event_key_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    repo = PaperWalletLedgerRepository()
    with Session() as db:
        first, first_created = repo.append_event(
            db,
            event_key="paper_trade:7:TARGET1",
            paper_trade_id=7,
            symbol="BTCUSDT",
            event_type="TARGET1_REALIZED",
            delta_inr=500,
        )
        duplicate, duplicate_created = repo.append_event(
            db,
            event_key="paper_trade:7:TARGET1",
            paper_trade_id=7,
            symbol="BTCUSDT",
            event_type="TARGET1_REALIZED",
            delta_inr=999,
        )
        db.commit()

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert db.query(PaperWalletLedgerEntry).count() == 1
        assert db.query(PaperWalletLedgerEntry).one().delta_inr == 500

    engine.dispose()


def test_wallet_snapshot_aggregates_full_ledger_but_bounds_recent_rows():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    repo = PaperWalletLedgerRepository()
    with Session() as db:
        repo.ensure_table(db)
        db.add_all(
            [
                PaperWalletLedgerEntry(
                    event_key=f"paper_trade:{index}:CLOSED",
                    paper_trade_id=index,
                    symbol="BTCUSDT",
                    event_type="POSITION_CLOSED",
                    delta_inr=10.0,
                )
                for index in range(125)
            ]
        )
        db.add(
            PaperWalletLedgerEntry(
                event_key="paper_trade:qa:CLOSED",
                paper_trade_id=999,
                symbol="QABTCUSDT",
                event_type="POSITION_CLOSED",
                delta_inr=50_000.0,
            )
        )
        db.commit()

        snapshot = repo.wallet_snapshot(db, recent_limit=10)

        assert snapshot["count"] == 125
        assert snapshot["realized_pnl_inr"] == 1_250.0
        assert len(snapshot["recent_entries"]) == 10
        assert [item.paper_trade_id for item in snapshot["recent_entries"]] == list(
            range(115, 125)
        )

    engine.dispose()
