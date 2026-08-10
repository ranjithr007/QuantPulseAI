"""Singleton scheduler worker entrypoint for cloud deployments."""

import signal
import threading

from app.config import get_settings
from app.scheduler.scheduler import get_scheduler, start_scheduler


def main():
    settings = get_settings()
    if settings.process_role != "worker":
        raise RuntimeError("Scheduler worker requires QUANTPULSE_PROCESS_ROLE=worker")
    if not settings.run_scheduler:
        raise RuntimeError("Scheduler worker requires QUANTPULSE_START_SCHEDULER=true")

    if not start_scheduler():
        raise RuntimeError("QuantPulse scheduler failed to start")

    stop_event = threading.Event()

    def request_shutdown(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print("QuantPulse scheduler worker started")
    stop_event.wait()

    scheduler = get_scheduler()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    print("QuantPulse scheduler worker stopped")


if __name__ == "__main__":
    main()
