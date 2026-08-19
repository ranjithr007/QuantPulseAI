from app.collectors.binances.mark_price_collector import MarkPriceCollector


def get_current_paper_entry_mark(symbol):
    """Return the direct futures mark used to simulate a new paper fill."""

    return MarkPriceCollector().get_current_mark_price(str(symbol).upper())
