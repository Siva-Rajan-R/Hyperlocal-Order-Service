from fastapi import FastAPI
from api.routers.v1 import order_routes
from contextlib import asynccontextmanager
from icecream import ic
from dotenv import load_dotenv
from core.configs.settings_config import SETTINGS
from infras.primary_db.main import init_orders_pg_db
from hyperlocal_platform.core.enums.environment_enum import EnvironmentEnum
import os,asyncio
from hyperlocal_platform.infras.saga.main import init_infra_db
from messaging.worker import worker
from infras.read_db.main import DB,ORDERS_COLLECTION
from infras.caching.main import redis_client,check_redis_health
load_dotenv()


@asynccontextmanager
async def order_service_lifespan(app:FastAPI):
    try:
        ic("Starting Order service...")
        await init_infra_db()
        await init_orders_pg_db()
        await check_redis_health()
        # asyncio.create_task(worker())
        yield

    except Exception as e:
        ic(f"Error : Starting Order service => {e}")

    finally:
        ic("...Stoping Order Servcie...")

debug=False
openapi_url=None
docs_url=None
redoc_url=None

if SETTINGS.ENVIRONMENT.value==EnvironmentEnum.DEVELOPMENT.value:
    debug=True
    openapi_url="/openapi.json"
    docs_url="/docs"
    redoc_url="/redoc"

app=FastAPI(
    title="Order Service",
    description="This service contains all the CRUD operations for Order service",
    debug=debug,
    openapi_url=openapi_url,
    docs_url=docs_url,
    redoc_url=redoc_url,
    lifespan=order_service_lifespan
)



# Routes to include
app.include_router(order_routes.router)

