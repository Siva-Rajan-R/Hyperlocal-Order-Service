from ...handlers.return_handler import HandleReturnRequest
from schemas.v1.request_scheams.order_schema import CreateReturnSchema
from fastapi import APIRouter, Depends
from typing import Annotated
from infras.primary_db.main import get_pg_async_session, AsyncSession

router = APIRouter(
    prefix='/returns',
    tags=['Returns']
)

PG_SESSION = Annotated[AsyncSession, Depends(get_pg_async_session)]
CURRENT_USER_ID = ""
SHOP_ID = "37d5519b-51a1-5854-982b-4d6524171017" # Consistent with existing implementation

@router.post('')
async def create_return(data: CreateReturnSchema, session: PG_SESSION):
    return await HandleReturnRequest(session=session, shop_id=SHOP_ID, cur_user_id=CURRENT_USER_ID).create(data=data)
