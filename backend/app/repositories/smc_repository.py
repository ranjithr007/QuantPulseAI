from app.database.models.market_smc import MarketSMCSignal
from app.repositories._db_utils import commit_or_rollback


class SMCRepository:
    def save_smc_signal(db, symbol, timeframe, result):

        record = MarketSMCSignal(
            symbol=symbol,
            timeframe=timeframe,
            bos_detected=result["bos"]["detected"],
            choch_detected=result["choch"],
            structure=result["bos"]["direction"],
            order_block_type=result["order_block"]["type"],
            order_block_price=result["order_block"]["price"],
            fvg_detected=result["fvg"]["detected"],
            fvg_price=result["fvg"]["price"],
            liquidity_sweep=result["sweep"]["detected"],
            sweep_price=result["sweep"]["price"],
            smc_bias=result["bias"],
            confidence=result["confidence"],
        )

        db.add(record)

        commit_or_rollback(db)

        return record

    def save(self, db, data):
        smc_bias = data.get("smc_bias")
        smc_score = data.get("smc_score")

        if smc_bias is None:
            if smc_score is not None and smc_score > 55:
                smc_bias = "LONG"
            elif smc_score is not None and smc_score < 45:
                smc_bias = "SHORT"
            else:
                smc_bias = "NEUTRAL"

        signal = MarketSMCSignal(
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            structure=data["structure"],
            # ==================
            # BOS
            # ==================
            bos_detected=(data.get("bos") != "NONE"),
            bos_type=data.get("bos", "NONE"),
            # ==================
            # CHOCH
            # ==================
            choch_detected=(data.get("choch") != "NONE"),
            choch_type=data.get("choch", "NONE"),
            # ==================
            # Liquidity Sweep
            # ==================
            liquidity_sweep=(data.get("liquidity_sweep", "NONE") != "NONE"),
            # ==================
            # Order Block
            # ==================
            order_block_type=data.get("order_block_type", "NONE"),
            order_block_price=data.get("order_block_price", 0),
            # ==================
            # FVG
            # ==================
            fvg_detected=(data.get("fvg_direction", "NONE") != "NONE"),
            fvg_price=data.get("fvg_size", 0),
            smc_bias=smc_bias,
            confidence=data["smc_score"],
            data_generation_id=data.get("data_generation_id"),
        )

        db.add(signal)

        commit_or_rollback(db)

        return signal

    def latest(self, db, symbol, timeframe=None):

        query = db.query(MarketSMCSignal).filter(MarketSMCSignal.symbol == symbol)

        if timeframe:
            query = query.filter(MarketSMCSignal.timeframe == timeframe)

        return query.order_by(MarketSMCSignal.created_at.desc()).first()
