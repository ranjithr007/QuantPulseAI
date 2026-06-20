import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.services.live_market_service import LiveMarketService


class LiveMarketStatusTests(unittest.TestCase):
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


class _RunningTask:
    @staticmethod
    def done():
        return False


if __name__ == "__main__":
    unittest.main()
