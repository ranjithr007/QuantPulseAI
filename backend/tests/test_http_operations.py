import json
import logging

from app.observability.http_operations import JsonLogFormatter
from app.observability.http_operations import SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_expires_old_events():
    limiter = SlidingWindowRateLimiter()

    assert limiter.allow("client", 2, now=0) is True
    assert limiter.allow("client", 2, now=1) is True
    assert limiter.allow("client", 2, now=2) is False
    assert limiter.allow("client", 2, now=61) is True


def test_json_log_formatter_emits_structured_fields():
    record = logging.LogRecord(
        "quantpulse.http",
        logging.INFO,
        __file__,
        1,
        "http_request",
        (),
        None,
    )
    record.structured = {"request_id": "req-1", "status_code": 200}

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "http_request"
    assert payload["request_id"] == "req-1"
    assert payload["status_code"] == 200
