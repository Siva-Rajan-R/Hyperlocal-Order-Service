from ...handlers.exchange_handler import HandleExchangeRequest
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema
from fastapi import APIRouter, Depends
from typing import Annotated, Optional
from infras.primary_db.main import get_pg_async_session, AsyncSession
from core.utils.user_info import get_current_user_id

router = APIRouter(
    prefix='/exchanges',
    tags=['Exchanges']
)

PG_SESSION = Annotated[AsyncSession, Depends(get_pg_async_session)]

@router.post('')
async def create_exchange(data: CreateExchangeSchema, session: PG_SESSION, user_id: Optional[str] = Depends(get_current_user_id)):
    return await HandleExchangeRequest(session=session, shop_id=data.shop_id, cur_user_id=user_id or "").create(data=data)
