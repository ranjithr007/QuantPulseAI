import pytest

from app.backtesting.spot_execution_probe import estimate_book_cost


def test_round_trip_spread_and_fee_accounting():
    book = {"bids": [[99, 100]], "asks": [[101, 100]]}
    result = estimate_book_cost(book, 1000, 10)
    assert result["base_quantity_unrounded"] == 10
    assert result["displayed_round_trip_bps"] == 200
    assert result["assumed_fee_round_trip_bps"] == 20
    assert result["indicative_total_round_trip_bps"] == 220
    assert result["executable_fill_verified"] is False


def test_sweep_multiple_levels_and_partial_last_level():
    book = {"bids": [[99, 2], [98, 20]], "asks": [[101, 2], [102, 20]]}
    result = estimate_book_cost(book, 1000, 0)
    assert result["buy_vwap"] == pytest.approx(101.8)
    assert result["sell_vwap"] == pytest.approx(98.2)
    assert result["displayed_round_trip_bps"] == pytest.approx(360)


@pytest.mark.parametrize("book", [
    {"bids": [[101, 2]], "asks": [[100, 2]]},
    {"bids": [[99, 2], [100, 2]], "asks": [[101, 2]]},
    {"bids": [[99, 1]], "asks": [[101, 1]]},
    {"bids": [[99, 100]], "asks": [["NaN", 100]]},
    {"bids": [], "asks": [[101, 100]]},
])
def test_invalid_or_insufficient_depth_fails_closed(book):
    with pytest.raises(ValueError):
        estimate_book_cost(book, 1000)
