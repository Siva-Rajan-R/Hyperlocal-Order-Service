from ..repos.order_repo import OrdersRepo,OrderItems
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum,OrderReturnTypeEnum
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.read_db.repos.order_repo import OrderReadDbRepo
import asyncpg
from fastapi.exceptions import HTTPException
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,OrderItemsSchema,GetOrderByCustomerIdSchema,UpdateOrderStatusSchema,GetBulkOrdersSchema
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from hyperlocal_platform.core.utils.routingkey_builder import RoutingkeyActions,RoutingkeyState,RoutingkeyVersions,generate_routingkey
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from icecream import ic
from typing import Optional,List
import httpx
from ..main import AsyncSession
from infras.caching.models.cart_model import OrderCartCacheModel
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict,SuccessResponseTypDict,BaseResponseTypDict
from integrations.stock_reservation import commit_reservation
from hyperlocal_platform.core.enums.saga_state_enum import SagaStatusEnum,SagaStepsValueEnum
from messaging.saga_producer import SagaProducer,CreateSagaStateSchema,SagaStatusEnum,SagaStateExecutionTypDict





class OrdersService:
    def __init__(self,session:AsyncSession):
         self.session=session
    async def create(self, data: CreateOrderSchema, executing_user_id: Optional[str] = None):
        cart = OrderCartCacheModel(data.session_id)
        cart_data = await cart.get_cart()
        ic(cart_data)
        if not cart_data:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Creating order",
                    description="Cart session is invalid, expired, or empty",
                    success=False
                )
            )
        reservation_complete_res=await commit_reservation(session_id=data.session_id)
        if not reservation_complete_res:
            ic("Cant able to reserve the stocks please try again")
            return False
    
        await cart.delete_cart()
            

        saga_id:str=generate_uuid()
        product_ids=[]
        for item in cart_data:
            ic(item)
            product_ids.append(item['product_id'])
        ic(cart_data)
        order_data={**data.model_dump(mode="json"),"items":cart_data}

        saga_data={"orders":order_data, "executing_user_id": executing_user_id}
        ic(product_ids)

        if data.customer_id:
            await SagaProducer.emit(
                session=self.session,
                saga_payload=CreateSagaStateSchema(
                    id=saga_id,
                    status=SagaStatusEnum.IN_PROGRESS,
                    type="ORDER_CREATED",
                    steps={
                        "VERIFY_CUSTOMER":SagaStepsValueEnum.PENDING,
                        "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
                    },
                    execution=SagaStateExecutionTypDict(
                        step="VERIFY_CUSTOMER",
                        service="CUSTOMERS"
                    ),
                    data=saga_data
                ),
                routing_key="customers.service.routing.key",
                exchange_name="customers.service.exchange",
                headers={
                    "reply_key":"orders.producer.routing.key",
                    "reply_exchange":"orders.producer.exchange",
                    "reply_entity_name":"create_order",
                    "reply_service_name":"ORDERS",
                    "service_name":"CUSTOMERS",
                    "entity_name":"get_customer_by_id",
                    "body":{
                        "shop_id":data.shop_id,
                        "id":data.customer_id
                    }
                }
            )
        else:
                       
            if product_ids:
                await SagaProducer.emit(
                    session=self.session,
                    saga_payload=CreateSagaStateSchema(
                        id=saga_id,
                        status=SagaStatusEnum.IN_PROGRESS,
                        type="ORDER_CREATED",
                        steps={
                            "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
                        },
                        execution=SagaStateExecutionTypDict(
                            step="FETCHING_PRODUCTS",
                            service="PRODUCTS"
                        ),
                        data=saga_data
                    ),
                    routing_key="products.service.routing.key",
                    exchange_name="products.service.exchange",
                    headers={
                        "reply_key":"orders.producer.routing.key",
                        "reply_exchange":"orders.producer.exchange",
                        "reply_entity_name":"create_order",
                        "reply_service_name":"ORDERS",
                        "service_name":"PRODUCTS",
                        "entity_name":"get_bulk_product_by_id",
                        "body":{
                            "shop_id":data.shop_id,
                            "id":list(set(product_ids))
                        }
                    }
                )


        return True
    

    async def update(self,data:UpdateOrderStatusSchema, executing_user_id: Optional[str] = None):
        old_order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
        
        from schemas.v1.db_schemas.order_schema import UpdateOrderDbSchema
        repo_data=UpdateOrderDbSchema(
            **data.model_dump(mode='json',exclude_unset=True,exclude_none=True)
        )
        res = await OrdersRepo(session=self.session).update(data=repo_data)
        if res:
            await self.session.commit()
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))

        return res
    

    async def delete(self,data:DeleteOrderSchema):
        res = await OrdersRepo(session=self.session).delete(data=data)
        if res:
            await self.session.commit()
            await OrderReadDbRepo.delete_order(order_id=data.id, shop_id=data.shop_id)
            
            try:
                from messaging.main import RabbitMQMessagingConfig
                rabbitmq_msg_obj = RabbitMQMessagingConfig()
                await rabbitmq_msg_obj.publish_event(
                    routing_key="activity_logs.routing.key",
                    exchange_name="activity_logs.exchange",
                    payload={
                        "shop_id": data.shop_id,
                        "user_name": "siva",
                        "service": "Billing",
                        "action": "DELETE",
                        "entity_type": "Order",
                        "entity_id": data.id,
                        "description": f"Deleted billing entry",
                        "changes": [{"field": "order_id", "before": str(data.id), "after": "DELETED"}]
                    },
                    headers={}
                )
            except Exception as e:
                ic(f"Failed to publish activity log: {e}")
        return res
    
    async def get(self,data:GetAllOrderSchema):
        res = await OrdersRepo(session=self.session).get(data=data)
        return res
    

    async def getby_shop_id(self,data:GetOrderByShopIdSchema):
        res = await OrdersRepo(session=self.session).getby_shop_id(data=data)
        if data.offset in (0, 1):
            overall_values = await OrdersRepo(session=self.session).get_overall_values(data=data)
            return {
                "overall_datas": overall_values,
                "datas": res
            }
        return {"datas": res}
    
    async def getby_customer_id(self,data:GetOrderByCustomerIdSchema):
        res = await OrdersRepo(session=self.session).getby_customer_id(data=data)
        if data.offset in (0, 1):
            overall_values = await OrdersRepo(session=self.session).get_overall_values(data=data)
            return {
                "overall_datas": overall_values,
                "datas": res
            }
        return {"datas": res}
    
    

    async def getby_id(self,data:GetOrderByIdSchema):
        return await OrdersRepo(session=self.session).getby_id(data=data)
    
    async def search(self,query:str,shop_id:str,limit:int=5):
        return await OrdersRepo(session=self.session).search(shop_id=shop_id,query=query,limit=limit)

    async def get_bulk_orders(self, data: GetBulkOrdersSchema):
        res = await OrderReadDbRepo.get_bulk_orders(shop_id=data.shop_id, order_ids=data.order_ids)
        if not res:
            res = await OrdersRepo(session=self.session).get_bulk_orders(shop_id=data.shop_id, order_ids=data.order_ids)
        return res

        