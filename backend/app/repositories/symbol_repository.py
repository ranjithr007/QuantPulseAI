from app.database.models.symbols import Symbol


class SymbolRepository:

    def get_active_symbols(self, db):

        return db.query(Symbol).filter(Symbol.is_active == True).all()