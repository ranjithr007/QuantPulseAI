"""Displayed-book cost estimates only. No order or account functionality."""
from decimal import Decimal, InvalidOperation


def number(value):
    try:
        value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid book number") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("Book numbers must be finite and positive")
    return value


def levels(rows, descending):
    parsed = [(number(p), number(q)) for p, q in rows]
    if not parsed:
        raise ValueError("Empty book side")
    prices = [p for p, _ in parsed]
    if prices != sorted(set(prices), reverse=descending):
        raise ValueError("Book levels must be unique and ordered")
    return parsed


def sweep(book_levels, quantity):
    remaining, quote = quantity, Decimal(0)
    for price, available in book_levels:
        take = min(remaining, available)
        quote += take * price
        remaining -= take
        if remaining == 0:
            return quote
    raise ValueError("Insufficient displayed depth; do not extrapolate")


def estimate_book_cost(book, quote_notional, fee_bps=10):
    bids, asks = levels(book["bids"], True), levels(book["asks"], False)
    if bids[0][0] >= asks[0][0]:
        raise ValueError("Crossed or locked book")
    mid = (bids[0][0] + asks[0][0]) / 2
    notional = number(quote_notional)
    fee = Decimal(str(fee_bps))
    if not fee.is_finite() or not 0 <= fee <= 100:
        raise ValueError("Invalid fee assumption")
    quantity = notional / mid
    buy, sell = sweep(asks, quantity), sweep(bids, quantity)
    book_bps = (buy - sell) / notional * 10000
    fees_bps = (buy + sell) / notional * fee
    return {"quote_notional": float(notional), "mid": float(mid),
            "base_quantity_unrounded": float(quantity),
            "top_spread_bps": float((asks[0][0] - bids[0][0]) / mid * 10000),
            "buy_vwap": float(buy / quantity), "sell_vwap": float(sell / quantity),
            "displayed_round_trip_bps": float(book_bps),
            "assumed_fee_round_trip_bps": float(fees_bps),
            "indicative_total_round_trip_bps": float(book_bps + fees_bps),
            "executable_fill_verified": False}
