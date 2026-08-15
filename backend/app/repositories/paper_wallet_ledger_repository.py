from app.database.models.paper_wallet_ledger import PaperWalletLedgerEntry
from app.repositories._db_utils import flush_or_rollback


class PaperWalletLedgerRepository:
    def ensure_table(self, db):
        bind = db.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", None) == "sqlite":
            PaperWalletLedgerEntry.__table__.create(bind=bind, checkfirst=True)

    def list_entries(self, db, paper_trade_id=None):
        self.ensure_table(db)
        query = db.query(PaperWalletLedgerEntry)
        if paper_trade_id is not None:
            query = query.filter(
                PaperWalletLedgerEntry.paper_trade_id == paper_trade_id
            )
        return query.order_by(
            PaperWalletLedgerEntry.created_at.asc(),
            PaperWalletLedgerEntry.id.asc(),
        ).all()

    def append_event(
        self,
        db,
        *,
        event_key,
        paper_trade_id,
        symbol,
        event_type,
        delta_inr=0.0,
        position_notional_inr=None,
        margin_inr=None,
        position_fraction=None,
        pnl_percent=None,
        created_at=None,
    ):
        self.ensure_table(db)
        existing = (
            db.query(PaperWalletLedgerEntry)
            .filter(PaperWalletLedgerEntry.event_key == event_key)
            .first()
        )
        if existing is not None:
            return existing, False

        entry = PaperWalletLedgerEntry(
            event_key=str(event_key),
            paper_trade_id=int(paper_trade_id),
            symbol=str(symbol).upper(),
            event_type=str(event_type).upper(),
            delta_inr=round(float(delta_inr or 0), 2),
            position_notional_inr=_optional_amount(position_notional_inr),
            margin_inr=_optional_amount(margin_inr),
            position_fraction=(
                None
                if position_fraction is None
                else float(position_fraction)
            ),
            pnl_percent=(None if pnl_percent is None else float(pnl_percent)),
        )
        if created_at is not None:
            entry.created_at = created_at
        db.add(entry)
        flush_or_rollback(db)
        return entry, True


def _optional_amount(value):
    return None if value is None else round(float(value), 2)
