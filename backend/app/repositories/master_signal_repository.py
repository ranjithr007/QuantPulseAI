from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database.models.master_signals import MasterSignal
from app.repositories._db_utils import commit_or_rollback


class MasterSignalRepository:

    def save(self, db, data):
        db.add(MasterSignal(**data))
        commit_or_rollback(db)

    def latest(self, db, symbol, timeframe=None):
        query = db.query(MasterSignal).filter(MasterSignal.symbol == symbol)
        if timeframe:
            query = query.filter(MasterSignal.timeframe == timeframe)
        return query.order_by(MasterSignal.created_at.desc()).first()

    def get_latest_signals(
        self,
        db,
        timeframe=None,
        symbols=None,
    ):
        filters = []

        if timeframe:
            filters.append(MasterSignal.timeframe == timeframe)

        if symbols:
            normalized_symbols = [
                symbol.strip().upper()
                for symbol in symbols
                if symbol and symbol.strip()
            ]

            if normalized_symbols:
                filters.append(MasterSignal.symbol.in_(normalized_symbols))

        ranked = (
            db.query(
                MasterSignal.id.label("master_signal_id"),
                func.row_number()
                .over(
                    partition_by=(
                        MasterSignal.symbol,
                        MasterSignal.timeframe,
                    ),
                    order_by=(
                        MasterSignal.created_at.desc(),
                        MasterSignal.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .filter(*filters)
            .subquery()
        )

        return (
            db.query(MasterSignal)
            .join(
                ranked,
                MasterSignal.id == ranked.c.master_signal_id,
            )
            .filter(ranked.c.row_number == 1)
            .order_by(MasterSignal.symbol.asc())
            .all()
        )

    def get_latest_for_symbol(
        self,
        db: Session,
        symbol: str,
        timeframe: str = "5m",
    ) -> MasterSignal | None:
        """
        Return the latest Master AI signal for one symbol/timeframe.
        """

        return (
            db.query(MasterSignal)
            .filter(
                MasterSignal.symbol == symbol.strip().upper(),
                MasterSignal.timeframe == timeframe,
            )
            .order_by(
                MasterSignal.created_at.desc(),
                MasterSignal.id.desc(),
            )
            .first()
        )
