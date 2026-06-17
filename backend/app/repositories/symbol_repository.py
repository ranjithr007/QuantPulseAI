from app.database.models.symbols import Symbol


class SymbolRepository:

    def get_active_symbols(self, db):

        symbols = (
            db.query(Symbol)
            .filter(Symbol.is_active == True)
            .order_by(Symbol.symbol.asc(), Symbol.id.asc())
            .all()
        )

        return _dedupe_symbols(symbols)


def _dedupe_symbols(symbols):
    unique_symbols = []
    seen = set()

    for item in symbols:
        normalized = item.symbol.upper()

        if normalized in seen:
            continue

        seen.add(normalized)
        unique_symbols.append(item)

    return unique_symbols
