# create_tables.py

from app.database.base import Base
from app.database.sqlserver import engine

# import all models

from app.database.models.symbols import Symbol
from app.database.models.market_candles import MarketCandle
from app.database.models.open_interest import OpenInterest
from app.database.models.funding_rates import FundingRate
from app.database.models.ai_scores import AIScore

# Base.metadata.create_all(bind=engine)

print("All tables created successfully")