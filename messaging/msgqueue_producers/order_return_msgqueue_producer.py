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
        ic(order_toadd,order_items_toadd)


        if current_step == "PRODUCT_VERIFY_UPDATE":
            try:
                async with AsyncOrdersLocalSession() as session:
                    return_repo_obj=ReturnRepo(session=session)

                    await return_repo_obj.create_return_with_items(
                        return_obj=Returns(**order_toadd),
                        return_items=[ReturnItems(**{k: v for k, v in itm.items() if k not in ('serialno_infos',)}) for itm in order_items_toadd]
                    )

                    ic("Return Process COmpleted")

                    order_id = order_toadd.get("order_id")
                    shop_id = order_toadd.get("shop_id")
                    
                    if order_id and shop_id:
                        existing_order = await OrderReadDbRepo.get_by_id(order_id=order_id,shop_id=shop_id)
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
                                    "entered_qty": itm.get("entered_qty"),
                                    "entered_unit": itm.get("entered_unit"),
                                    "refund_amount": itm.get("refund_amount", 0.0),
                                    "reason": itm.get("reason", "")
                                }
                                
                                # Find the original item from existing_order to copy its extra data
                                original_item = next((orig for orig in existing_order.get("items", []) if orig.get("id") == itm.get("order_item_id")), None)
                                if original_item:
                                    formatted_item.update({
                                        "name": original_item.get("name"),
                                        "ui_id": original_item.get("ui_id"),
                                        "category_infos": original_item.get("category_infos"),
                                        "unit_infos": original_item.get("unit_infos"),
                                        "variant_infos": original_item.get("variant_infos"),
                                        "batch_infos": original_item.get("batch_infos"),
                                        "serialno_infos": original_item.get("serialno_infos"),
                                        "buy_price": original_item.get("buy_price"),
                                        "sell_price": original_item.get("sell_price"),
                                        "gst": original_item.get("gst")
                                    })

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
                                            "id": order_toadd.get("id"),
                                            "order_item_id": itm.get("order_item_id"),
                                            "quantity": itm.get("quantity", 0),
                                            "entered_qty": itm.get("entered_qty"),
                                            "entered_unit": itm.get("entered_unit"),
                                            "serialno_infos": itm.get("serialno_infos") or [],
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
                                "payment_infos": order_toadd.get("payment_infos", {}),
                                "created_at": order_toadd.get("created_at"),
                                "updated_at": order_toadd.get("updated_at"),
                                "items": return_items_formatted
                            }
                            existing_order["returns"].append(new_return)

                            await OrderReadDbRepo.replace_order(existing_order)

                        try:
                            rabbitmq_msg_obj = RabbitMQMessagingConfig()
                            await rabbitmq_msg_obj.publish_event(
                                routing_key="activity_logs.routing.key",
                                exchange_name="activity_logs.exchange",
                                payload={
                                    "shop_id": shop_id,
                                    "user_name": "Hyperlocal-User",
                                    "service": "Sales-Order",
                                    "action": "RETURN",
                                    "entity_type": f"SALES-RETURN",
                                    "entity_id": order_id,
                                    "description": f"Returned order {order_id}",
                                    "changes": [{"field": "id", "before": str(order_id), "after": "RETURN"}]
                                },
                                headers={}
                            )
                        except Exception as e:
                            ic(f"Failed to publish activity log: {e}")

                # Emit Success Notification
                try:
                    from helpers.emit_notification import emit_notification
                    import asyncio
                    executing_user_id = datas.get("executing_user_id")
                    asyncio.create_task(emit_notification(
                        title="Order Return Processed",
                        message=f"Order return for order '{order_id}' has been successfully processed.",
                        type="info",
                        user_id=executing_user_id or shop_id,
                        additional_metadata={"order_id": order_id}
                    ))
                except Exception as notification_error:
                    ic(f"Notification error: {notification_error}")

                return {
                    "success":True,
                    "execution":None
                }
            except Exception as e:
                # Emit Error Notification
                try:
                    from helpers.emit_notification import emit_notification
                    import asyncio
                    executing_user_id = datas.get("executing_user_id")
                    asyncio.create_task(emit_notification(
                        title="Order Return Failed",
                        message=f"Failed to process return for order '{order_toadd.get('order_id')}': {str(e)}",
                        type="error",
                        user_id=executing_user_id or order_toadd.get("shop_id")
                    ))
                except Exception as notification_error:
                    ic(f"Notification error: {notification_error}")
                raise e