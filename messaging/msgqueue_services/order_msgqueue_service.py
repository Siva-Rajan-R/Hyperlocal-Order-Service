from infras.primary_db.services.order_service import OrdersService
from models.service_models.base_service_model import BaseServiceModel
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,ReturnOrderSchema,ExchangeOrderSchema,ReturnBulkOrderSchema,ExchangeBulkOrderSchema
from schemas.v1.response_schemas.msgqueue_schemas.order_schema import OrderGetResponseSchema,OrderCreateResponseSchema,OrderItemsResponseSchema,OrderDeleteResponseSchema,OrderUpdateResponseSchema
from hyperlocal_platform.core.models.req_res_models import SuccessResponseTypDict,ErrorResponseTypDict,BaseResponseTypDict
from fastapi.exceptions import HTTPException
from infras.primary_db.main import AsyncOrdersLocalSession
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from core.decorators.error_handler_dec import catch_errors
from typing import Optional,Union
from icecream import ic

class MessagingQueueOrderService:
    async def create_order(self,data:Union[CreateOrderSchema,dict]):
        if isinstance(data, dict):
            data = CreateOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.create(data=data)

            if not res:
                return res

            return OrderCreateResponseSchema(**res).model_dump(mode="json") if res else None
        
    
    async def return_order(self,data:Union[ReturnOrderSchema,dict]):
        if isinstance(data, dict):
            data = ReturnOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.return_order(data=data)
            
            return res
        

    async def return_order_bulk(self,data:Union[ReturnBulkOrderSchema,dict]):
        if isinstance(data, dict):
            data = ReturnBulkOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.return_order_bulk(data=data)
            ic("inside srvice",res)
            return res


    async def exchange_order(self,data:Union[ExchangeOrderSchema,dict]):
        if isinstance(data, dict):
            data = ExchangeOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.exchange_order(data=data)
            
            return res
        
    async def exchange_order_bulk(self,data:Union[ExchangeBulkOrderSchema,dict]):
        ic(data)
        if isinstance(data, dict):
            data = ExchangeBulkOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.exchange_bulk_order(data=data)
            
            return res

    async def delete_order(self,data:Union[DeleteOrderSchema,dict]):
        if isinstance(data, dict):
            data = DeleteOrderSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.delete(data=data)

            if not res:
                return res

            return OrderDeleteResponseSchema(**res).model_dump(mode="json") if res else None

    async def get_orders(self,data:Union[GetAllOrderSchema,dict]):
        if isinstance(data, dict):
            data = GetAllOrderSchema(**data)
        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.get(data=data)

            if not res:
                return res

            return [OrderGetResponseSchema(**r).model_dump(mode="json") for r in res]
    
    async def get_order_by_id(self,data:Union[GetOrderByIdSchema,dict]):
        if isinstance(data, dict):
            data = GetOrderByIdSchema(**data)
        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.getby_id(data=data)

            if not res:
                return res
            
            return OrderGetResponseSchema(**res).model_dump(mode="json")
    
    async def get_order_by_shop_id(self,data:Union[GetOrderByShopIdSchema,dict]):
        if isinstance(data, dict):
            data = GetOrderByShopIdSchema(**data)
        async with AsyncOrdersLocalSession() as session:
            order_service_obj=OrdersService(session=session)
            res=await order_service_obj.getby_shopid(data=data)

            if not res:
                return res
            
            return [OrderGetResponseSchema(**r).model_dump(mode="json") for r in res]