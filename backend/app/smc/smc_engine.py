from app.smc.bos_detector import detect_bos
from app.smc.choch_detector import detect_choch
from app.smc.order_block_detector import detect_order_block
from app.smc.fvg_detector import detect_fvg
from app.smc.liquidity_sweep_detector import detect_liquidity_sweep


def analyze_smc(candles):

    bos = detect_bos(candles)

    choch = detect_choch(candles)

    order_block = detect_order_block(candles)

    fvg = detect_fvg(candles)

    sweep = detect_liquidity_sweep(candles)

    confidence = 0

    if bos["detected"]:
        confidence += 25

    if choch:
        confidence += 20

    if order_block["type"] != "NONE":
        confidence += 20

    if fvg["detected"]:
        confidence += 15

    if sweep["detected"]:
        confidence += 20

    bias = "NEUTRAL"

    if bos["direction"] == "BULLISH" and order_block["type"] == "BULLISH":
        bias = "LONG"

    elif bos["direction"] == "BEARISH" and order_block["type"] == "BEARISH":
        bias = "SHORT"

    return {
        "bos": bos,
        "choch": choch,
        "order_block": order_block,
        "fvg": fvg,
        "sweep": sweep,
        "bias": bias,
        "confidence": confidence,
    }