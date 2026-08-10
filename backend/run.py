import os

import uvicorn

from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    reload_enabled = os.getenv("QUANTPULSE_RELOAD", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload_enabled,
    )
