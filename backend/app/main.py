from fastapi import FastAPI

from contextlib import asynccontextmanager


from app.scheduler.scheduler import start_scheduler, scheduler
from app.api.v1 import features_api
from app.api.v1 import orderflow_api
from app.api.v1 import smc_api
from app.api.v2 import master_ai_v2_api
from app.api.v1 import backtest_api
from app.api.v1 import ml_api
from app.api.v1 import dataset_api
from app.api.v1 import ml_label_api
from app.api.v1 import prediction_api


@asynccontextmanager
async def lifespan(app: FastAPI):

    print("🔥 QuantPulse Starting")

    start_scheduler()

    yield

    print("🛑 QuantPulse stopping")

    if scheduler.running:

        scheduler.shutdown(wait=False)


app = FastAPI(title="QuantPulse AI v3", lifespan=lifespan)

app.include_router(features_api.router)
app.include_router(orderflow_api.router)
app.include_router(smc_api.router)
app.include_router(master_ai_v2_api.router)
app.include_router(backtest_api.router)
app.include_router(ml_api.router)
app.include_router(dataset_api.router)
app.include_router(ml_label_api.router)
app.include_router(prediction_api.router)


@app.get("/")
def health():

    return {"system": "QuantPulse AI", "version": "3.0", "status": "running"}