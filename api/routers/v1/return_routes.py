from ...handlers.return_handler import HandleReturnRequest
from schemas.v1.request_scheams.order_schema import CreateReturnSchema
from fastapi import APIRouter, Depends
from typing import Annotated, Optional, List, Dict, Any
from infras.primary_db.main import get_pg_async_session, AsyncSession
from core.utils.user_info import get_current_user_info

router = APIRouter(
    prefix='/returns',
    tags=['Returns']
)

PG_SESSION = Annotated[AsyncSession, Depends(get_pg_async_session)]
SHOP_ID = "37d5519b-51a1-5854-982b-4d6524171017" # Consistent with existing implementation

@router.post('/{shop_id}')
async def create_return_by_shop_id(shop_id: str, data: CreateReturnSchema, session: PG_SESSION, user_info: Dict[str, Any] = Depends(get_current_user_info)):
    data.shop_id = shop_id
    user_id = user_info.get("user_id") or user_info.get("id") or ""
    return await HandleReturnRequest(session=session, shop_id=shop_id, cur_user_id=user_id, custom_user_info=user_info).create(data=data)

@router.post('')
async def create_return(data: CreateReturnSchema, session: PG_SESSION, user_info: Dict[str, Any] = Depends(get_current_user_info)):
    shop_id = data.shop_id or SHOP_ID
    data.shop_id = shop_id
    user_id = user_info.get("user_id") or user_info.get("id") or ""
    return await HandleReturnRequest(session=session, shop_id=shop_id, cur_user_id=user_id, custom_user_info=user_info).create(data=data)
