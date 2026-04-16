from infras.primary_db.services.order_service import OrdersService
from sqlalchemy.ext.asyncio import AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from icecream import ic
from . import HTTPException
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,UpdateOrderStatusSchema
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict,SuccessResponseTypDict,BaseResponseTypDict
from infras.caching.models.billing_model import BillingCacheModel,CachingBillingSchema

class HandleOrderRequest:

    def __init__(self,session:AsyncSession,cur_user_id:str,shop_id:str):
        self.session=session
        self.cur_user_id=cur_user_id
        self.shop_id=shop_id

        
    async def create(self,data:CreateOrderSchema):
        cached_billing_data:Dict[str,dict]=await BillingCacheModel(shop_id=self.shop_id,cur_user_id=self.cur_user_id).get_billing_cache()
        ic(data.orders,cached_billing_data)
        
        if not cached_billing_data or len(data.orders)!=len(cached_billing_data):
            raise HTTPException(
                status_code=404,
                detail=ErrorResponseTypDict(
                    status_code=404,
                    msg="Error : Creating order",
                    description="Billing was not initiated, or invalid Billing",
                    success=False
                )
            )
        ic(len(data.orders),len(cached_billing_data))
        
        total_amount:int=0
        orders=[]
        for product in data.orders:
            product_info=cached_billing_data.get(product,None)
            if not product_info:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorResponseTypDict(
                        status_code=404,
                        msg="Error : Creating Order",
                        description="Billed product not found",
                        success=False
                    )
                )
            
            total_amount+=product_info.get('total_price')
            orders.append(
                OrderItemValueTypDict(
                    product_name=product_info.get('product_name'),
                    barcode=product_info.get('barcode'),
                    quantity=product_info.get('qty'),
                    price=product_info.get('product_price'),
                    total_price=product_info.get('total_price')
                )
            )

        
        data.total_price=total_amount
        data.orders=orders
        res=await OrdersService(session=self.session).create(data=data,cur_user_id=self.cur_user_id)
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
        
        await BillingCacheModel(shop_id=self.shop_id,cur_user_id=self.cur_user_id).delete_billing_cache()
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=201,
                msg="Order Created Successfully",
                success=True
            )
        )
    
    async def update(self,data:UpdateOrderStatusSchema):
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
    
    async def delete(self,shop_id:str,order_id:str):
        res=await OrdersService(session=self.session).delete(shop_id=shop_id,order_id=order_id)
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
            )
        )
    
    async def get(self,query:str,limit:int,offset:int,shop_id:str,timezone:TimeZoneEnum):
        res=await OrdersService(session=self.session).get(limit=limit,timezone=timezone,shop_id=shop_id,offset=offset,query=query)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )
    
    async def get_byid(self,shop_id:str,order_id:str,timezone:TimeZoneEnum):
        res=await OrdersService(session=self.session).getby_id(timezone=timezone,shop_id=shop_id,order_id=order_id)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
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
    

        
