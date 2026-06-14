from ..repos.order_repo import OrdersRepo,OrderItems
from ..models.order_model import ExchangedOrderItems
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum,OrderReturnTypeEnum
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.read_db.repos.order_repo import OrderReadDbRepo
import asyncpg
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema,ReturnBulkOrderDbSchema
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,ReturnOrderSchema,ExchangeOrderSchema,OrderItemsSchema,ReturnBulkOrderSchema,ExchangeBulkOrderSchema,GetOrderByCustomerIdSchema
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from hyperlocal_platform.core.utils.routingkey_builder import RoutingkeyActions,RoutingkeyState,RoutingkeyVersions,generate_routingkey
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from icecream import ic
from typing import Optional,List
import httpx

ACTIVITY_LOG_URL = "http://127.0.0.1:8001/activity-logs"

async def _send_activity_log(shop_id: str, action: str, entity_id: str, description: str, entity_type: str = "Order", changes: list = None):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(ACTIVITY_LOG_URL, json={
                "shop_id": shop_id,
                "user_name": "siva",
                "service": "Billing",
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "description": description,
                "changes": changes or []
            })
    except Exception as e:
        ic(f"Failed to log activity: {e}")



class OrdersService(BaseServiceModel):
    async def create(self,data:CreateOrderSchema,type:Optional[str]="NORMAL"):

        order_id:str=generate_uuid()
        tot_qty=0
        tot_buy_price=0
        tot_sell_price=0

        order_items_toadd=[]

        for item in data.items:
            tot_qty+=item.quantity
            tot_buy_price+=item.buy_price*item.quantity
            tot_sell_price+=item.sell_price*item.quantity

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


        order_dict = data.model_dump(mode='json',exclude_none=True,exclude_unset=True,exclude=['items'])
        
        customer_id = order_dict.pop('customer_id', None)
        if 'customer' in order_dict:
            customer_data = order_dict.pop('customer')
            customer_id = customer_data.get('customer_id') or customer_id
            if 'datas' not in order_dict or not order_dict['datas']:
                order_dict['datas'] = {}
            order_dict['datas']['customer'] = customer_data

        if customer_id and ('datas' not in order_dict or 'customer' not in order_dict.get('datas', {})):
            try:
                conn = await asyncpg.connect('postgresql://postgres:TempSuperSecretPwd@89.167.72.254:5432/CustomerServiceDb')
                row = await conn.fetchrow('SELECT id, name, mobile_number FROM customers WHERE id = $1', customer_id)
                await conn.close()
                if row:
                    if 'datas' not in order_dict or not order_dict['datas']:
                        order_dict['datas'] = {}
                    order_dict['datas']['customer'] = {
                        "customer_id": row["id"],
                        "customer_name": row["name"],
                        "customer_mobile_number": row["mobile_number"]
                    }
            except Exception as e:
                ic(f"Error fetching customer from CustomerServiceDb Postgres: {e}")

        from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo
        from core.utils.id_formatter import format_ui_id

        shop_config = await ShopIdConfigReadDbRepo.get_config(data.shop_id)
        order_config = shop_config.get("order", {})
        prefix = order_config.get("prefix", "ORD")
        start_from = order_config.get("start_from", 1)

        raw_sequence = await OrdersRepo(session=self.session).get_next_sequence(data.shop_id, start_from)
        ui_id_str = format_ui_id(prefix, start_from, raw_sequence)

        order_toadd=CreateOrderDbSchema(
            **order_dict,
            id=order_id,
            ui_id=ui_id_str,
            total_buyprice=tot_buy_price,
            total_quantity=tot_qty,
            total_sellprice=tot_sell_price,
            type=type,
            customer_id=customer_id
        )
        ic(order_items_toadd)
        order_res = await OrdersRepo(session=self.session).create(data=order_toadd)
        if order_res:
            item_res=await OrdersRepo(session=self.session).create_bulk_items(datas=order_items_toadd)
        if not item_res:
            order_res=None
        
        if order_res:
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=order_id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))

            # Activity log
            item_count = len(data.items)
            await _send_activity_log(
                shop_id=data.shop_id,
                action="CREATE",
                entity_id=order_id,
                description=f"Created new billing entry with {item_count} item(s), total: ₹{tot_sell_price:.2f}",
                changes=[
                    {"field": "items", "before": "", "after": str(item_count)},
                    {"field": "total_sellprice", "before": "", "after": f"₹{tot_sell_price:.2f}"},
                    {"field": "type", "before": "", "after": str(type)}
                ]
            )

        return order_res
    

    async def update(self,data:CreateOrderSchema):
        repo_data=CreateOrderDbSchema(
            **data.model_dump(mode='json',exclude_unset=True,exclude_none=True)
        )
        res = await OrdersRepo(session=self.session).update(data=repo_data)
        if res:
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))
        return res
    

    async def return_order(self,data:ReturnOrderSchema):
        res = await OrdersRepo(session=self.session).update_order_item(data=UpdateOrderItemDbSchema(id=data.item_id,order_id=data.id,status=OrderStatusEnum.REFUNDED))
        if res:
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))
            await _send_activity_log(
                shop_id=data.shop_id,
                action="RETURN",
                entity_id=data.id,
                description=f"Returned order item {data.item_id}",
                changes=[{"field": "item_id", "before": "COMPLETED", "after": "REFUNDED"}]
            )
        return res
    
    async def return_order_bulk(self,data:ReturnBulkOrderSchema):
        order=await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id,shop_id=data.shop_id))
        if not order:
            return False

        item_toupdate=[]
        for item in data.items:
            item_toupdate.append(
                {
                    'b_item_id':item.id,
                    'b_order_id':data.id,
                    'b_status':OrderStatusEnum.REFUNDED.value,
                    'b_reason':item.reason,
                    'b_returned_quantity':item.quantity
                }
            )
        ic(item_toupdate)
        res=await OrdersRepo(session=self.session).update_order_item_bulk_adv(data=item_toupdate)
        ic(res)

        if res:
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))

        return order
    
    async def exchange_order(self,data:ExchangeOrderSchema)-> bool | None:
        data_toadd=CreateOrderSchema(
            shop_id=data.shop_id,
            customer_id=data.customer_id,
            status=OrderStatusEnum.COMPLETED,
            payments=data.payments,
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

        # Sync original order
        order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.order_id, shop_id=data.shop_id))
        if order_data:
            await OrderReadDbRepo.replace_order(data=dict(order_data))

        # The new exchange order is automatically synced in self.create()

        return True
    

    async def exchange_bulk_order(self,data:ExchangeBulkOrderSchema)-> bool | None:
        order=await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.order_id,shop_id=data.shop_id))
        data_toadd=CreateOrderSchema(
            shop_id=data.shop_id,
            customer_id=data.customer_id,
            status=OrderStatusEnum.COMPLETED,
            payments=data.payments,
            origin=OrderOriginEnum.OFFLINE,
            items=data.items
        )

        res=await self.create(data=data_toadd,type="EXCHANGE")
        if not res:
            return res
        
        exchange_order_items_toadd=[]

        item_toupdate=[]
        for item in data.exchange_items:
            item_toupdate.append(
                {
                    'b_item_id':item.id,
                    'b_order_id':data.order_id,
                    'b_status':OrderStatusEnum.EXCHANGED.value,
                    'b_reason':item.reason,
                    'b_returned_quantity':item.quantity
                }
            )

            formatted_data=ExchangedOrderItems(
                id=generate_uuid(),
                item_id=item.id,
                parent_order_id=data.order_id,
                replacement_order_id=res['id']
            )

            exchange_order_items_toadd.append(formatted_data)
            

        # await OrdersRepo(session=self.session).update_order_item(data=UpdateOrderItemDbSchema(id=data.item_id,order_id=data.order_id,status=OrderStatusEnum.EXCHANGED))
        await OrdersRepo(session=self.session).update_order_item_bulk_adv(data=item_toupdate)
        self.session.add_all(exchange_order_items_toadd)
        await self.session.commit()
        ic(order)

        # Sync original order
        order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.order_id, shop_id=data.shop_id))
        if order_data:
            await OrderReadDbRepo.replace_order(data=dict(order_data))

        # The new exchange order is automatically synced in self.create()

        return order
        

    async def delete(self,data:DeleteOrderSchema):
        res = await OrdersRepo(session=self.session).delete(data=data)
        if res:
            await OrderReadDbRepo.delete_order(order_id=data.id, shop_id=data.shop_id)
            await _send_activity_log(
                shop_id=data.shop_id,
                action="DELETE",
                entity_id=data.id,
                description=f"Deleted billing entry",
                changes=[{"field": "order_id", "before": str(data.id), "after": "DELETED"}]
            )
        return res
    
    async def get(self,data:GetAllOrderSchema):
        res = await OrdersRepo(session=self.session).get(data=data)
        if data.offset in (0, 1):
            overall_values = await OrdersRepo(session=self.session).get_overall_values(data=data)
            return {
                "overall_datas": overall_values,
                "datas": res
            }
        return {"datas": res}
    

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
        