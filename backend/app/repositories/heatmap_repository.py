from app.database.models.liquidation_heatmaps import LiquidationHeatmap


class HeatmapRepository:

    def save(self, db, data):

        db.add(LiquidationHeatmap(**data))

        db.commit()