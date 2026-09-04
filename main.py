from fastapi import FastAPI
from api.routers.v1 import order_routes, cart_routes, return_routes, exchange_routes
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
        asyncio.create_task(worker())
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
app.include_router(cart_routes.router)
app.include_router(return_routes.router)
app.include_router(exchange_routes.router)










# --- INJECTED LOGGING SETUP ---
import time
import logging
import traceback
from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# ANSI Escape Codes for Colors
RESET = "\033[0m"
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    request.state.error_detail = str(exc.detail)
    logger.error(f"{RED}❌ HTTP {exc.status_code} Error on {request.method} {request.url.path}:{RESET} {exc.detail}")
    
    if isinstance(exc.detail, dict) and "msg" in exc.detail:
        exc.detail["status_type"] = exc.detail.get("status_type", "error")
        exc.detail["title"] = exc.detail.get("title", "HTTP Error")
        exc.detail["description"] = exc.detail.get("description", exc.detail.get("msg", str(exc.detail)))
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": {
                "msg": "HTTP Error",
                "status_code": exc.status_code,
                "success": False,
                "status_type": "error",
                "title": "HTTP Error",
                "description": str(exc.detail)
            }
        }
    )

@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    error_details = str(exc.errors())
    request.state.error_detail = error_details
    logger.error(f"{RED}❌ Validation Error on {request.method} {request.url.path}:{RESET} {error_details}")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "msg": "Validation Error",
                "status_code": 422,
                "success": False,
                "status_type": "error",
                "title": "Validation Error",
                "description": error_details
            }
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_details = str(exc)
    request.state.error_detail = error_details
    logger.error(f"{RED}❌ Unhandled Exception on {request.method} {request.url.path}:{RESET} {error_details}")
    logger.error(traceback.format_exc())
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "msg": "Internal Server Error",
                "status_code": 500,
                "success": False,
                "status_type": "error",
                "title": "System Error",
                "description": error_details
            }
        }
    )

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    if request.method == "GET":
        method_color = CYAN
    elif request.method == "POST":
        method_color = GREEN
    elif request.method == "PUT":
        method_color = YELLOW
    elif request.method == "DELETE":
        method_color = RED
    else:
        method_color = MAGENTA
    
    logger.info(f"{BLUE}▶ Incoming:{RESET} {method_color}{request.method}{RESET} {request.url.path}")
    
    try:
        response = await call_next(request)
    except Exception as e:
        raise e
        
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = f"{process_time:.2f}ms"
    
    if response.status_code < 300:
        status_color = GREEN
    elif response.status_code < 400:
        status_color = YELLOW
    else:
        status_color = RED
        
    error_msg = ""
    if response.status_code >= 400 and hasattr(request.state, "error_detail"):
        error_msg = f" - {RED}Error: {request.state.error_detail}{RESET}"
        
    logger.info(f"{MAGENTA}✔ Completed:{RESET} {method_color}{request.method}{RESET} {request.url.path} - {status_color}Status: {response.status_code}{RESET} - {YELLOW}Time: {formatted_process_time}{RESET}{error_msg}")
    
    return response
# ------------------------------


# --- INJECTED USER CONTEXT MIDDLEWARE ---
import json
from fastapi import Request
from core.utils.user_context import current_user_ctx

@app.middleware("http")
async def user_context_middleware(request: Request, call_next):
    user_infos_header = request.headers.get("x-user-infos")
    if user_infos_header:
        try:
            user_infos = json.loads(user_infos_header)
            current_user_ctx.set(user_infos)
        except Exception:
            pass
    return await call_next(request)
# ----------------------------------------
