from ..repos.order_repo import OrdersRepo
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from models.service_models.base_service_model import BaseServiceModel
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,UpdateOrderStatusDbSchema
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,UpdateOrderStatusSchema
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from hyperlocal_platform.core.utils.routingkey_builder import RoutingkeyActions,RoutingkeyState,RoutingkeyVersions,generate_routingkey
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from icecream import ic
from typing import Optional,List



class OrdersService(BaseServiceModel):
    async def create(self,data:CreateOrderSchema,cur_user_id:str):
        order_id:str=generate_uuid()
        repo_data=CreateOrderDbSchema(
            **data.model_dump(mode='json',exclude_none=True,exclude_unset=True),
            id=order_id,
            order_by=cur_user_id
        )
        return await OrdersRepo(session=self.session).create(data=repo_data)
    

    async def update(self,data:UpdateOrderStatusSchema):
        repo_data=UpdateOrderStatusDbSchema(
            **data.model_dump(mode='json',exclude_unset=True,exclude_none=True)
        )
        return await OrdersRepo(session=self.session).update(data=repo_data)
    
    async def delete(self,shop_id:str,order_id:str):
        return await OrdersRepo(session=self.session).delete(order_id=order_id,shop_id=shop_id)
    
    async def get(self,limit:int,timezone:TimeZoneEnum,shop_id:str,offset:int=1,query:str=""):
        return await OrdersRepo(session=self.session).get(limit=limit,offset=offset,shop_id=shop_id,timezone=timezone,query=query)

    async def getby_id(self,timezone:TimeZoneEnum,shop_id:str,order_id:str):
        return await OrdersRepo(session=self.session).getby_id(shop_id=shop_id,order_id=order_id,timezone=timezone)
    
    async def search(self,query:str,shop_id:str,limit:int=5):
        return await OrdersRepo(session=self.session).search(shop_id=shop_id,query=query,limit=limit)
        