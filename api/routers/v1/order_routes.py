from ...handlers.ordrer_handler import HandleOrderRequest,CreateOrderSchema,UpdateOrderStatusSchema,Optional,List
from fastapi import APIRouter,Depends,Query
from typing import Annotated
from infras.primary_db.main import get_pg_async_session,AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum


router=APIRouter(
    prefix='/orders',
    tags=['Orders CRUD']
)


PG_SESSION=Annotated[AsyncSession,Depends(get_pg_async_session)]
CURRENT_USER_ID=""
SHOP_ID="812921c7-e107-51e2-b5b5-9d24957aad0f"

@router.post('/')
async def create(data:CreateOrderSchema,session:PG_SESSION):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).create(data=data)


@router.put('/status')
async def update_status(data:UpdateOrderStatusSchema,session:PG_SESSION):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).update(data=data)


@router.delete('/{shop_id}/{order_id}')
async def delete(shop_id:str,order_id:str,session:PG_SESSION):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).delete(shop_id=shop_id,order_id=order_id)


@router.get('/{shop_id}')
async def get_all(offset:int,shop_id:str,session:PG_SESSION,q:str=Query(""),limit:Optional[int]=Query(10),timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).get(query=q,limit=limit,offset=offset,shop_id=shop_id,timezone=timezone)


@router.get('/{shop_id}/{order_id}')
async def get_byid(session:PG_SESSION,shop_id:str,order_id:str,timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).get_byid(shop_id=shop_id,order_id=order_id,timezone=timezone)


@router.get('/search/{shop_id}')
async def search(shop_id:str,session:PG_SESSION,q:str=Query(""),limit:Optional[int]=5):
    return await HandleOrderRequest(session=session,shop_id=SHOP_ID,cur_user_id=CURRENT_USER_ID).search(shop_id=shop_id,query=q,limit=limit)