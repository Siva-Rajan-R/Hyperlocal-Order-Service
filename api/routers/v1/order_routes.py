from ...handlers.ordrer_handler import HandleOrderRequest,CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,GetOrderByCustomerIdSchema
from fastapi import APIRouter,Depends,Query
from typing import Annotated,Optional
from infras.primary_db.main import get_pg_async_session,AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum


router=APIRouter(
    prefix='/orders',
    tags=['Orders CRUD']
)


PG_SESSION=Annotated[AsyncSession,Depends(get_pg_async_session)]
CURRENT_USER_ID=""
SHOP_ID="37d5519b-51a1-5854-982b-4d6524171017"

@router.post('')
async def create(data:CreateOrderSchema,session:PG_SESSION):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).create(data=data)


@router.put('/status')
async def update_status(data:CreateOrderSchema,session:PG_SESSION):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).update(data=data)


@router.delete('/{shop_id}/{id}')
async def delete(session:PG_SESSION,data:DeleteOrderSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).delete(data=data)


@router.get('')
async def get_all(session:PG_SESSION,data:GetAllOrderSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).get(data=data)


@router.get('/stats/customer/{shop_id}/{customer_id}')
async def get_customer_stats(session:PG_SESSION, shop_id: str, customer_id: str):
    return await HandleOrderRequest(session=session, shop_id=shop_id, cur_user_id=CURRENT_USER_ID).get_customer_stats(shop_id=shop_id, customer_id=customer_id)

@router.get('/stats/dashboard/{shop_id}')
async def get_dashboard_stats(session:PG_SESSION, shop_id: str, start_date: str = Query(...), end_date: str = Query(...), supplier_id: Optional[str] = Query(None), category: Optional[str] = Query(None)):
    return await HandleOrderRequest(session=session, shop_id=shop_id, cur_user_id=CURRENT_USER_ID).get_dashboard_stats(shop_id=shop_id, start_date=start_date, end_date=end_date, supplier_id=supplier_id, category=category)

@router.get('/by/customer/{shop_id}/{customer_id}')
async def get_by_customer(session:PG_SESSION,data:GetOrderByCustomerIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).getby_customer_id(data=data)

@router.get('/search/{shop_id}')
async def search(shop_id:str,session:PG_SESSION,q:str=Query(""),limit:Optional[int]=5):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).search(shop_id=shop_id,query=q,limit=limit)

@router.get('/{shop_id}')
async def get_all(session:PG_SESSION,data:GetOrderByShopIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).getby_shop_id(data=data)

@router.get('/{shop_id}/{id}')
async def get_byid(session:PG_SESSION,data:GetOrderByIdSchema=Depends()):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).getby_id(data=data)