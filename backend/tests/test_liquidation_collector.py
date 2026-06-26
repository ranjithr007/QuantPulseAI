import sys
import types

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.collectors.binances.liquidation_collector import _parse_liquidation_message
from app.collectors.binances.liquidation_collector import _reconnect_delay_seconds


def test_parse_liquidation_message_returns_normalized_record():
    payload = (
        '{"E": 1710000000000, "o": {"s": "BTCUSDT", "S": "SELL", '
        '"p": "65000.5", "q": "0.25"}}'
    )

    record = _parse_liquidation_message(payload)

    assert record["symbol"] == "BTCUSDT"
    assert record["side"] == "SELL"
    assert record["price"] == 65000.5
    assert record["quantity"] == 0.25
    assert record["value_usd"] == 16250.125


def test_parse_liquidation_message_rejects_malformed_payloads():
    assert _parse_liquidation_message("{}") is None
    assert _parse_liquidation_message("not-json") is None


def test_liquidation_reconnect_delay_backoff_grows_and_caps():
    assert _reconnect_delay_seconds(1) == 5
    assert _reconnect_delay_seconds(2) == 10
    assert _reconnect_delay_seconds(3) == 20
    assert _reconnect_delay_seconds(6) == 60
