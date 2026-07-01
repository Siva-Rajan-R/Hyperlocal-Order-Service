import datetime
from typing import Any, Dict, List
from icecream import ic
from ..main import RabbitMQMessagingConfig
# Core utilities
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from core.utils.id_formatter import format_ui_id

# Database Sessions & Repositories
from infras.primary_db.main import AsyncOrdersLocalSession
from infras.primary_db.repos.order_repo import OrdersRepo
from infras.read_db.repos.order_repo import OrderReadDbRepo
from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo

# Database Models / Schemas
from infras.primary_db.models.order_model import OrderItems, Orders,ReturnItems,Returns
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema
from schemas.v1.request_scheams.order_schema import GetOrderByIdSchema
from integrations.utility_service import get_ui_id
from infras.primary_db.repos.return_repo import ReturnRepo


async def get_product_bulk(order_data: dict,headers: dict,payload: dict,rabbitmq_connection:RabbitMQMessagingConfig):
    product_ids=[]

    for item in order_data.get('items', []):
        product_ids.append(item.get('product_id'))

    routing_key="products.service.routing.key"
    exchange_name="products.service.exchange"
    entity_name="get_bulk_product_by_id"
    service_name="PRODUCTS"
    body={
        "shop_id":order_data.get('shop_id'),
        "id":product_ids
    }
                

    headers={
        **headers,
        "routing_key":routing_key,
        "exchange_name":exchange_name,
        "entity_name":entity_name,
        "service_name":service_name,
        "body":body
    }
    payload={
        **payload
    }

    await rabbitmq_connection.publish_event(
        routing_key=routing_key,
        payload=payload,
        headers=headers,
        exchange_name=exchange_name
    )

    return {
        "success":True,
        "execution":{
            "step":"FETCHING_PRODUCTS",
            "service":"PRODUCTS"
        }
    }

class MessagingQueueOrderReturnProducer:

    def __init__(self, headers: dict, payload: dict, saga_datas: dict):
        self.headers = headers
        self.payload = payload
        self.saga_datas = saga_datas

    

    async def create_return(self):
        """
        Migrated Order Flow: Extracts order details from the saga data,
        generates sequential UI IDs, saves to primary DB, replicates to read DB,
        and fires an activity log via RabbitMQ.
        """
        ic(self.headers, self.payload, self.saga_datas)
        
        execution = self.saga_datas.get('execution', {})
        current_step = execution.get('step')
        datas = self.saga_datas.get("data", {})
        order_return_payload = datas.get("order_return")  # This is a dict from saga data
        

        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        
        if not order_return_payload:
            ic("Missing 'order_payload' or 'cart_items' in saga data context.")
            return {"success": False, "reason": "Missing required payload data"}

        order_toadd=order_return_payload.get("return_toadd")
        order_items_toadd=order_return_payload.get("return_items_toadd")


        if current_step == "PRODUCT_VERIFY_UPDATE":

            async with AsyncOrdersLocalSession() as session:
                return_repo_obj=ReturnRepo(session=session)

                await return_repo_obj.create_return_with_items(
                    return_obj=Returns(**order_toadd),
                    return_items=[ReturnItems(**itm) for itm in order_items_toadd]
                )

                ic("Return Process COmpleted")

                order_id = order_toadd.get("order_id")
                shop_id = order_toadd.get("shop_id")
                
                if order_id and shop_id:
                    existing_order = await OrderReadDbRepo.getby_id(GetOrderByIdSchema(shop_id=shop_id, id=order_id))
                    if existing_order:
                        if "returns" not in existing_order or existing_order["returns"] is None:
                            existing_order["returns"] = []
                        
                        # Format items for the return object
                        return_items_formatted = []
                        for itm in order_items_toadd:
                            formatted_item = {
                                "id": itm.get("id"),
                                "order_item_id": itm.get("order_item_id"),
                                "product_id": itm.get("product_id"),
                                "quantity": itm.get("quantity", 0),
                                "refund_amount": itm.get("refund_amount", 0.0),
                                "reason": itm.get("reason", "")
                            }
                            return_items_formatted.append(formatted_item)
                            
                            # Update root items
                            for existing_item in existing_order.get("items", []):
                                if existing_item.get("id") == itm.get("order_item_id"):
                                    # Increment returned_quantity (cumulative logic)
                                    curr_returned = existing_item.get("returned_quantity") or 0.0
                                    existing_item["returned_quantity"] = curr_returned + float(itm.get("quantity", 0))
                                    
                                    # Append to item-level returns array
                                    if "returns" not in existing_item or existing_item["returns"] is None:
                                        existing_item["returns"] = []
                                        
                                    existing_item["returns"].append({
                                        "id": generate_uuid(),
                                        "return_id": order_toadd.get("id"),
                                        "quantity": itm.get("quantity", 0),
                                        "refund_amount": itm.get("refund_amount", 0.0),
                                        "reason": itm.get("reason", ""),
                                        "created_at": order_toadd.get("created_at")
                                    })
                                    break

                        # Append to root returns
                        new_return = {
                            "id": order_toadd.get("id"),
                            "sequence_id": order_toadd.get("sequence_id"),
                            "status": order_toadd.get("status", "COMPLETED"),
                            "total_refund_amount": order_toadd.get("total_refund_amount", 0.0),
                            "total_refund_qty": order_toadd.get("total_refund_qty", 0.0),
                            "payment_infos": order_toadd.get("payment_infos", []),
                            "created_at": order_toadd.get("created_at"),
                            "updated_at": order_toadd.get("updated_at"),
                            "items": return_items_formatted
                        }
                        existing_order["returns"].append(new_return)

                        await OrderReadDbRepo.replace_order(existing_order)

                return {
                    "success":True,
                    "execution":None
                }