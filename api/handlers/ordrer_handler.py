from infras.primary_db.services.order_service import OrdersService
from sqlalchemy.ext.asyncio import AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from icecream import ic
from . import HTTPException
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,DeleteOrderSchema,ReturnOrderSchema,ExchangeOrderSchema,GetOrderByCustomerIdSchema
from schemas.v1.response_schemas.user_schemas.order_schema import OrderGetResponseSchema,OrderCreateResponseSchema,OrderUpdateResponseSchema,OrderDeleteResponseSchema
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict,SuccessResponseTypDict,BaseResponseTypDict

from infras.caching.models.billing_model import BillingCacheModel,CachingBillingSchema

class HandleOrderRequest:

    def __init__(self,session:AsyncSession,cur_user_id:str,shop_id:str):
        self.session=session
        self.cur_user_id=cur_user_id
        self.shop_id=shop_id

        
    async def create(self,data:CreateOrderSchema):
        res=await OrdersService(session=self.session).create(data=data)
        if not res:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Creating order",
                    description="Invalid Data for order",
                    success=False
                )
            )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=201,
                msg="Order Created Successfully",
                success=True
            ),
            data=OrderCreateResponseSchema(**res) if res else None
        )
    
    async def update(self,data:CreateOrderSchema):
        res=await OrdersService(session=self.session).update(data=data)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Updating order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order Updated Successfully",
                success=True
            )
        )
    

    async def return_order(self,data:ReturnOrderSchema):
        res=await OrdersService(session=self.session).return_order(data=data)
        ic(res)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Updating order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order Updated Successfully",
                success=True
            )
        )
    

    async def exchange_order(self,data:ExchangeOrderSchema):
        res=await OrdersService(session=self.session).exchange_order(data=data)
        ic(res)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Updating order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order Updated Successfully",
                success=True
            )
        )
        
    async def delete(self,data:DeleteOrderSchema):
        res=await OrdersService(session=self.session).delete(data=data)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Deleting order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
            
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order deleted Successfully",
                success=True
            ),
            data=OrderDeleteResponseSchema(**res) if res else None
        )
    
    async def get(self,data:GetAllOrderSchema):
        res=await OrdersService(session=self.session).get(data=data)
        ic(res)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=[OrderGetResponseSchema(**r) for r in res] if res else []
        )
    
    async def getby_shop_id(self,data:GetOrderByShopIdSchema):
        res=await OrdersService(session=self.session).getby_shop_id(data=data)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=[OrderGetResponseSchema(**r) for r in res] if res else []
        )
    
    async def getby_customer_id(self,data:GetOrderByCustomerIdSchema):
        res=await OrdersService(session=self.session).getby_customer_id(data=data)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=[OrderGetResponseSchema(**r) for r in res] if res else []
        )
    
    async def get_byid(self,data:GetOrderByIdSchema):
        res=await OrdersService(session=self.session).getby_id(data=data)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=OrderGetResponseSchema(**res) if res else None
        )
    
    async def search(self,limit:int,shop_id:str,query:str=""):
        res=await OrdersService(session=self.session).search(query=query,shop_id=shop_id,limit=limit)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )
    

        
