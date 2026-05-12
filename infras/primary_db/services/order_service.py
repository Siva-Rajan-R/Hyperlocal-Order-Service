from ..repos.order_repo import OrdersRepo,OrderItems
from ..models.order_model import ExchangedOrderItems
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum,OrderReturnTypeEnum
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from models.service_models.base_service_model import BaseServiceModel
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema,ReturnBulkOrderDbSchema
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,ReturnOrderSchema,ExchangeOrderSchema,OrderItemsSchema,ReturnBulkOrderSchema,ExchangeBulkOrderSchema
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from hyperlocal_platform.core.utils.routingkey_builder import RoutingkeyActions,RoutingkeyState,RoutingkeyVersions,generate_routingkey
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from icecream import ic
from typing import Optional,List



class OrdersService(BaseServiceModel):
    async def create(self,data:CreateOrderSchema,type:Optional[str]="NORMAL"):

        order_id:str=generate_uuid()
        tot_qty=0
        tot_buy_price=0
        tot_sell_price=0

        order_items_toadd=[]

        for item in data.items:
            tot_qty+=item.quantity
            tot_buy_price+=item.buy_price
            tot_sell_price+=item.sell_price

            item_id=generate_uuid()
            ic(item.model_dump())
            item_toadd=OrderItemsDbSchema(
                id=item_id,
                order_id=order_id,
                sku=generate_uuid(),
                **item.model_dump(),
                status=OrderStatusEnum.COMPLETED,
                
            )

            ic(item_toadd)

            order_items_toadd.append(OrderItems(**item_toadd.model_dump(exclude=['inv_serial_numbers']),serial_numbers=item_toadd.inv_serial_numbers))


        order_toadd=CreateOrderDbSchema(
            **data.model_dump(mode='json',exclude_none=True,exclude_unset=True,exclude=['items']),
            id=order_id,
            total_buyprice=tot_buy_price,
            total_quantity=tot_qty,
            total_sellprice=tot_sell_price,
            type=type
        )
        ic(order_items_toadd)
        order_res = await OrdersRepo(session=self.session).create(data=order_toadd)
        if order_res:
            item_res=await OrdersRepo(session=self.session).create_bulk_items(datas=order_items_toadd)
        if not item_res:
            order_res=None
        
        return order_res
    

    async def update(self,data:CreateOrderSchema):
        repo_data=CreateOrderDbSchema(
            **data.model_dump(mode='json',exclude_unset=True,exclude_none=True)
        )
        return await OrdersRepo(session=self.session).update(data=repo_data)
    

    async def return_order(self,data:ReturnOrderSchema):
        return await OrdersRepo(session=self.session).update_order_item(data=UpdateOrderItemDbSchema(id=data.item_id,order_id=data.id,status=OrderStatusEnum.REFUNDED))
    
    async def return_order_bulk(self,data:ReturnBulkOrderSchema):

        res=await OrdersRepo(session=self.session).update_order_item_bulk(data=ReturnBulkOrderDbSchema(**data.model_dump(),status=OrderStatusEnum.REFUNDED.value))

        if len(data.items_id)!=len(res):
            return False
        
        return True
    
    async def exchange_order(self,data:ExchangeOrderSchema)-> bool | None:
        data_toadd=CreateOrderSchema(
            shop_id=data.shop_id,
            customer_id=data.customer_id,
            status=OrderStatusEnum.COMPLETED,
            payment_method=data.payment_method,
            origin=OrderOriginEnum.OFFLINE,
            items=[data.items]
        )
        res=await self.create(data=data_toadd,type="EXCHANGE")
        if not res:
            return res
        
        exchange_item_toadd=ExchangedOrderItems(
            id=generate_uuid(),
            item_id=data.item_id,
            parent_order_id=data.order_id,
            replacement_order_id=res['id']
        )

        await OrdersRepo(session=self.session).update_order_item(data=UpdateOrderItemDbSchema(id=data.item_id,order_id=data.order_id,status=OrderStatusEnum.EXCHANGED))
        self.session.add(exchange_item_toadd)
        await self.session.commit()

        return True
    

    async def exchange_bulk_order(self,data:ExchangeBulkOrderSchema)-> bool | None:
        data_toadd=CreateOrderSchema(
            shop_id=data.shop_id,
            customer_id=data.customer_id,
            status=OrderStatusEnum.COMPLETED,
            payment_method=data.payment_method,
            origin=OrderOriginEnum.OFFLINE,
            items=data.items
        )

        

        res=await self.create(data=data_toadd,type="EXCHANGE")
        if not res:
            return res
        
        exchange_order_items_toadd=[]
        for item_id in data.items_id:
            formatted_data=ExchangedOrderItems(
                id=generate_uuid(),
                item_id=item_id,
                parent_order_id=data.order_id,
                replacement_order_id=res['id']
            )

            exchange_order_items_toadd.append(formatted_data)

        # await OrdersRepo(session=self.session).update_order_item(data=UpdateOrderItemDbSchema(id=data.item_id,order_id=data.order_id,status=OrderStatusEnum.EXCHANGED))
        await OrdersRepo(session=self.session).update_order_item_bulk(data=ReturnBulkOrderDbSchema(id=data.order_id,items_id=data.items_id,status=OrderStatusEnum.EXCHANGED))
        self.session.add_all(exchange_order_items_toadd)
        await self.session.commit()

        return True
        

    async def delete(self,data:DeleteOrderSchema):
        return await OrdersRepo(session=self.session).delete(data=data)
    
    async def get(self,data:GetAllOrderSchema):
        return await OrdersRepo(session=self.session).get(data=data)
    

    async def getby_shop_id(self,data:GetOrderByShopIdSchema):
        return await OrdersRepo(session=self.session).getby_shop_id(data=data)
    
    

    async def getby_id(self,data:GetOrderByIdSchema):
        return await OrdersRepo(session=self.session).getby_id(data=data)
    
    async def search(self,query:str,shop_id:str,limit:int=5):
        return await OrdersRepo(session=self.session).search(shop_id=shop_id,query=query,limit=limit)
        