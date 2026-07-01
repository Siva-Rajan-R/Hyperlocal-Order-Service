from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict, SuccessResponseTypDict, BaseResponseTypDict
from schemas.v1.request_scheams.order_schema import CreateReturnSchema
from infras.primary_db.services.return_service import ReturnService

class HandleReturnRequest:
    def __init__(self, session: AsyncSession, cur_user_id: str, shop_id: str):
        self.session = session
        self.cur_user_id = cur_user_id
        self.shop_id = shop_id

    async def create(self, data: CreateReturnSchema):
        res = await ReturnService(session=self.session).process_return(data=data)
        if not res:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Processing return",
                    description="Invalid Data for return",
                    success=False
                )
            )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=201,
                msg="Return Processed Successfully",
                success=True
            ),
            # Return response schema could be added here later if needed
            data=True
        )
