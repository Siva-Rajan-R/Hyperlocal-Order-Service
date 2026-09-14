from ...handlers.ordrer_handler import HandleOrderRequest,CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,GetOrderByCustomerIdSchema,UpdateOrderStatusSchema,GetBulkOrdersSchema
from fastapi import APIRouter,Depends,Query
from typing import Annotated,Optional
from infras.primary_db.main import get_pg_async_session,AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum


router=APIRouter(
    prefix='/orders',
    tags=['Orders CRUD']
)


from core.utils.user_info import get_current_user_id

PG_SESSION=Annotated[AsyncSession,Depends(get_pg_async_session)]
SHOP_ID="37d5519b-51a1-5854-982b-4d6524171017"

@router.post('')
async def create(data:CreateOrderSchema,session:PG_SESSION,user_id: Optional[str] = Depends(get_current_user_id)):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=user_id or "").create(data=data)


@router.put('/status')
async def update_status(data:UpdateOrderStatusSchema,session:PG_SESSION,user_id: Optional[str] = Depends(get_current_user_id)):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=user_id or "").update(data=data)

from schemas.v1.request_scheams.order_schema import VerifyDeliverySchema
@router.post('/verify-delivery')
async def verify_delivery(data:VerifyDeliverySchema,session:PG_SESSION,user_id: Optional[str] = Depends(get_current_user_id)):
    return await HandleOrderRequest(session=session,shop_id=data.shop_id,cur_user_id=user_id or "").verify_delivery(data=data)


@router.delete('/{shop_id}/{id}')
async def delete(session:PG_SESSION,data:DeleteOrderSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=data.shop_id,cur_user_id="").delete(data=data)


@router.get('')
async def get_all(session:PG_SESSION,data:GetAllOrderSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id="",cur_user_id="").get(data=data)


@router.get('/stats/customer/{shop_id}/{customer_id}')
async def get_customer_stats(session:PG_SESSION, shop_id: str, customer_id: str):
    return await HandleOrderRequest(session=session, shop_id=shop_id, cur_user_id="").get_customer_stats(shop_id=shop_id, customer_id=customer_id)

@router.get('/stats/dashboard/{shop_id}')
async def get_dashboard_stats(session:PG_SESSION, shop_id: str, start_date: str = Query(...), end_date: str = Query(...), supplier_id: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    return await HandleOrderRequest(session=session, shop_id=shop_id, cur_user_id="").get_dashboard_stats(shop_id=shop_id, start_date=start_date, end_date=end_date, supplier_id=supplier_id, category=category)

@router.get('/by/customer/{shop_id}/{customer_id}')
async def get_by_customer(session:PG_SESSION,data:GetOrderByCustomerIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=data.shop_id,cur_user_id="").getby_customer_id(data=data)

@router.get('/search/{shop_id}')
async def search(shop_id:str,session:PG_SESSION,q:str=Query(""),limit:Optional[int]=5):
    return await HandleOrderRequest(session=session,shop_id=shop_id,cur_user_id="").search(shop_id=shop_id,query=q,limit=limit)

@router.get('/{shop_id}')
async def get_all(session:PG_SESSION,data:GetOrderByShopIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=data.shop_id,cur_user_id="").getby_shop_id(data=data)

@router.get('/{shop_id}/{id}')
async def get_byid(session:PG_SESSION,data:GetOrderByIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=data.shop_id,cur_user_id="").getby_id(data=data)

@router.post('/get_bulk_orders')
async def get_bulk_orders(data: GetBulkOrdersSchema, session: PG_SESSION):
    return await HandleOrderRequest(session=session, shop_id=data.shop_id, cur_user_id="").get_bulk_orders(data=data)

@router.get('/by/user/{user_id}')
async def get_by_user_id(user_id: str, session: PG_SESSION, limit: int = Query(10), offset: int = Query(1)):
    return await HandleOrderRequest(session=session, shop_id="", cur_user_id="").getby_user_id(user_id=user_id, limit=limit, offset=offset)


# --- Export Routes ---
from schemas.v1.export_schemas import ExportDataRequestSchema
from arq import create_pool
from arq.connections import RedisSettings
import json, os, uuid
from hyperlocal_platform.core.models.req_res_models import SuccessResponseTypDict, BaseResponseTypDict
from fastapi import HTTPException
import redis.asyncio as aioredis

REDIS_URL = os.getenv("PLATFORM_REDIS_URL") or "redis://localhost:6379"

@router.post('/export')
async def export_orders(data: ExportDataRequestSchema):
    job_id = str(uuid.uuid4())
    payload = data.model_dump()
    payload["job_id"] = job_id
    
    redis_client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.set(
        f"EXPORT_JOB:{job_id}",
        json.dumps({
            "job_id": job_id,
            "entity": "ORDER",
            "status": "QUEUED",
            "params": payload
        }),
        ex=86400
    )
    await redis_client.aclose()

    try:
        from background_worker import export_orders_task
        asyncio.create_task(export_orders_task(None, payload))
    except Exception:
        pass
    
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            msg="Order export job scheduled successfully in the background",
            status_code=202,
            success=True
        ),
        data={
            "job_id": job_id,
            "entity": "ORDER",
            "status": "QUEUED"
        }
    )

@router.get('/export/status/{job_id}')
async def get_order_export_status(job_id: str):
    redis_client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
    raw = await redis_client.get(f"EXPORT_JOB:{job_id}")
    await redis_client.aclose()
    
    if not raw:
        raise HTTPException(status_code=404, detail="Export job not found")
        
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            msg="Export status fetched successfully",
            status_code=200,
            success=True
        ),
        data=json.loads(raw)
    )
