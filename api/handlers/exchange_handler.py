from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict, SuccessResponseTypDict, BaseResponseTypDict
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema
from infras.primary_db.services.exchange_service import ExchangeService

class HandleExchangeRequest:
    def __init__(self, session: AsyncSession, cur_user_id: str, shop_id: str, custom_user_info: dict | None = None):
        self.session = session
        self.cur_user_id = cur_user_id
        self.shop_id = shop_id
        self.custom_user_info = custom_user_info

    async def create(self, data: CreateExchangeSchema):
        res = await ExchangeService(session=self.session).process_exchange(
            data=data,
            executing_user_id=self.cur_user_id or None,
            custom_user_info=self.custom_user_info
        )
        if not res:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Processing exchange",
                    description="Invalid Data for exchange",
                    success=False
                )
            )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=202,
                msg="Exchange Request Accepted",
                success=True
            ),
            data=True
        )
