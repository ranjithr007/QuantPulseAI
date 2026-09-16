import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import sys
import types
from unittest.mock import Mock
from unittest.mock import patch

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.services.live_market_service import LiveMarketService
from app.services.live_market_service import BINANCE_STREAM_URL
from app.services.live_market_service import _reconnect_delay_seconds


class LiveMarketStatusTests(unittest.TestCase):
    def test_uses_current_binance_futures_market_stream_path(self):
        self.assertEqual(
            "wss://fstream.binance.com/market/stream",
            BINANCE_STREAM_URL,
        )

    def test_stopped_service_reports_unavailable_symbols(self):
        service = LiveMarketService()

        status = service.status()

        self.assertEqual("STOPPED", status["state"])
        self.assertFalse(status["connected"])
        self.assertEqual("UNAVAILABLE", status["symbol_status"]["BTCUSDT"]["state"])

    def test_connected_service_reports_live_and_stale_symbols(self):
        service = LiveMarketService()
        service._connected = True
        service._task = _RunningTask()
        service._symbols = ["BTCUSDT", "ETHUSDT"]
        service._records = {
            "BTCUSDT": {"symbol": "BTCUSDT", "received_at": datetime.now(timezone.utc).isoformat()},
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "received_at": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
            },
        }

        status = service.status()

        self.assertEqual("PARTIAL", status["state"])
        self.assertEqual("LIVE", status["symbol_status"]["BTCUSDT"]["state"])
        self.assertEqual("STALE", status["symbol_status"]["ETHUSDT"]["state"])

    def test_reconnect_delay_backoff_grows_and_caps(self):
        self.assertEqual(5, _reconnect_delay_seconds(1))
        self.assertEqual(10, _reconnect_delay_seconds(2))
        self.assertEqual(20, _reconnect_delay_seconds(3))
        self.assertEqual(60, _reconnect_delay_seconds(6))

    def test_successful_rest_refresh_clears_previous_network_error(self):
        service = LiveMarketService()
        service._last_error = "request retries exhausted"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{"symbol": "ETHUSDT", "price": "2500.5"}]

        with patch("app.services.live_market_service.requests.get", return_value=response):
            service._seed_from_rest(["ETHUSDT"])

        self.assertIsNone(service._last_error)
        self.assertEqual(2500.5, service._records["ETHUSDT"]["current_price"])


class _RunningTask:
    @staticmethod
    def done():
        return False


if __name__ == "__main__":
    unittest.main()
