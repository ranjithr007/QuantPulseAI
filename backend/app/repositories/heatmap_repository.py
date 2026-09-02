from app.database.models.liquidation_heatmaps import LiquidationHeatmap
from app.repositories._db_utils import commit_or_rollback


class HeatmapRepository:

    def save(self, db, data):

        column_names = {column.name for column in LiquidationHeatmap.__table__.columns}
        db.add(
            LiquidationHeatmap(
                **{
                    key: value
                    for key, value in (data or {}).items()
                    if key in column_names and key not in {"id", "created_at"}
                }
            )
        )

        commit_or_rollback(db)
