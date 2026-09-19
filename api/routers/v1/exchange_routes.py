from ...handlers.exchange_handler import HandleExchangeRequest
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema
from fastapi import APIRouter, Depends
from typing import Annotated, Optional, Dict, Any
from infras.primary_db.main import get_pg_async_session, AsyncSession
from core.utils.user_info import get_current_user_info

router = APIRouter(
    prefix='/exchanges',
    tags=['Exchanges']
)

PG_SESSION = Annotated[AsyncSession, Depends(get_pg_async_session)]

@router.post('')
async def create_exchange(data: CreateExchangeSchema, session: PG_SESSION, user_info: Dict[str, Any] = Depends(get_current_user_info)):
    user_id = user_info.get("user_id") or user_info.get("id") or ""
    return await HandleExchangeRequest(session=session, shop_id=data.shop_id, cur_user_id=user_id, custom_user_info=user_info).create(data=data)
