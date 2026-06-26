from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.repositories._db_utils import commit_or_rollback


class HeatmapRepository:

    def save(self, db, data):

        db.add(LiquidationHeatmap(**data))

        commit_or_rollback(db)
