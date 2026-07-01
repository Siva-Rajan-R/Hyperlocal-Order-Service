from infras.primary_db.services.order_service import OrdersService
from models.service_models.base_service_model import BaseServiceModel
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,CreateReturnSchema,CreateExchangeSchema
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
        
    
    async def process_return(self,data:Union[CreateReturnSchema,dict]):
        if isinstance(data, dict):
            data = CreateReturnSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            from infras.primary_db.services.return_service import ReturnService
            return_service_obj=ReturnService(session=session)
            res=await return_service_obj.process_return(data=data)
            
            return res
        
    async def process_exchange(self,data:Union[CreateExchangeSchema,dict]):
        if isinstance(data, dict):
            data = CreateExchangeSchema(**data)

        async with AsyncOrdersLocalSession() as session:
            from infras.primary_db.services.exchange_service import ExchangeService
            exchange_service_obj=ExchangeService(session=session)
            res=await exchange_service_obj.process_exchange(data=data)
            
            return res

    async def publish_customer_outstanding_update(self, shop_id: str, customer_id: str, amount: float, action: str, reference_id: str):
        from messaging.main import RabbitMQMessagingConfig
        from hyperlocal_platform.core.utils.routingkey_builder import generate_routingkey
        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        
        routing_key = "customer.outstanding.update"
        exchange_name = "customer_exchange"
        
        payload = {
            "shop_id": shop_id,
            "customer_id": customer_id,
            "amount": amount,
            "action": action,
            "reference_id": reference_id,
            "source": "ORDER_SERVICE"
        }
        
        await rabbitmq_msg_obj.publish_event(
            routing_key=routing_key,
            exchange_name=exchange_name,
            payload=payload,
            headers={}
        )

    async def publish_inventory_stock_update(self, shop_id: str, updates: list):
        """
        updates should be a list of dicts with:
        id (stock_id), product_id, shop_id, variant_id, batch_id, physical_stocks, type (e.g., "INCREMENT"),
        origin (e.g. ONLINE_SALES_RETURN), name, variant_name, batch_name
        """
        from messaging.main import RabbitMQMessagingConfig
        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        
        routing_key = "products.service.routing.key"
        exchange_name = "products.service.exchange"
        
        payload = {}
        headers = {
            "routing_key": routing_key,
            "exchange_name": exchange_name,
            "entity_name": "update_bulk_stock",
            "service_name": "PRODUCTS",
            "saga_id": "none",
            "reply_key": "none",
            "reply_exchange": "none",
            "reply_entity_name": "none",
            "body": updates
        }
        
        await rabbitmq_msg_obj.publish_event(
            routing_key=routing_key,
            exchange_name=exchange_name,
            payload=payload,
            headers=headers
        )

    async def publish_inventory_prodinv_update(self, updates: list):
        """
        Calls update_bulk_prodinv on the Inventory Service via messaging.
        Each item in updates should match UpdateAllProdInvSchema:
        {product_id, shop_id, variant_id, batch_infos, serialno_infos,
         stocks, type (INCREMENT/DECREMENT), buy_price, sell_price, gst, ...}
        """
        from messaging.main import RabbitMQMessagingConfig
        rabbitmq_msg_obj = RabbitMQMessagingConfig()

        routing_key = "products.service.routing.key"
        exchange_name = "products.service.exchange"

        payload = {}
        headers = {
            "routing_key": routing_key,
            "exchange_name": exchange_name,
            "entity_name": "update_bulk_prodinv",
            "service_name": "PRODUCTS",
            "saga_id": "none",
            "reply_key": "none",
            "reply_exchange": "none",
            "reply_entity_name": "none",
            "body": updates
        }

        await rabbitmq_msg_obj.publish_event(
            routing_key=routing_key,
            exchange_name=exchange_name,
            payload=payload,
            headers=headers
        )

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