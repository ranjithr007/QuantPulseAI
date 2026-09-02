from types import SimpleNamespace
from unittest.mock import patch

from app.api.v1 import health_api


class FakePool:
    def checkedin(self):
        return 3

    def checkedout(self):
        return 7

    def overflow(self):
        return 2


def test_database_pool_status_reports_safe_connection_counts():
    settings = SimpleNamespace(database_pool_size=5, database_max_overflow=5)
    with patch.object(health_api, "engine", SimpleNamespace(pool=FakePool())), patch.object(
        health_api, "get_settings", return_value=settings
    ):
        status = health_api._database_pool_status()

    assert status == {
        "implementation": "FakePool",
        "configured_size": 5,
        "configured_max_overflow": 5,
        "capacity": 10,
        "checked_in": 3,
        "checked_out": 7,
        "overflow_in_use": 2,
        "utilization_percent": 70.0,
        "status": "NORMAL",
    }


def test_database_pool_status_flags_capacity_saturation():
    class SaturatedPool(FakePool):
        def checkedout(self):
            return 10

    settings = SimpleNamespace(database_pool_size=5, database_max_overflow=5)
    with patch.object(
        health_api, "engine", SimpleNamespace(pool=SaturatedPool())
    ), patch.object(health_api, "get_settings", return_value=settings):
        status = health_api._database_pool_status()

    assert status["utilization_percent"] == 100.0
    assert status["status"] == "SATURATED"
