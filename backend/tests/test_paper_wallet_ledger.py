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
