from core.utils.user_context import get_activity_log_user_info
import datetime
from typing import Any, Dict, List
from icecream import ic
from ..main import RabbitMQMessagingConfig

from hyperlocal_platform.core.utils.uuid_generator import generate_uuid

from infras.primary_db.main import AsyncOrdersLocalSession
from infras.primary_db.repos.order_repo import OrdersRepo
from infras.primary_db.repos.exchange_repo import ExchangeRepo
from infras.read_db.repos.order_repo import OrderReadDbRepo
from infras.primary_db.models.order_model import Exchanges, ExchangeItems, Orders, OrderItems
from schemas.v1.request_scheams.order_schema import GetOrderByIdSchema
import copy


class MessagingQueueOrderExchangeProducer:

    def __init__(self, headers: dict, payload: dict, saga_datas: dict):
        self.headers = headers
        self.payload = payload
        self.saga_datas = saga_datas

    async def create_exchange(self):
        """
        SAGA callback after PRODUCT_VERIFY_UPDATE (stock increment for returned items).
        Saves Exchanges + ExchangeItems to primary DB, updates read DB order doc,
        and publishes customer outstanding event if needed.
        """
        ic(self.headers, self.payload, self.saga_datas)

        execution = self.saga_datas.get("execution", {})
        current_step = execution.get("step")
        datas = self.saga_datas.get("data", {})
        exchange_payload = datas.get("exchange_data")

        rabbitmq_msg_obj = RabbitMQMessagingConfig()

        if not exchange_payload:
            ic("Missing 'exchange_data' in saga context.")
            return {"success": False, "reason": "Missing required exchange payload"}

        exchange_toadd = exchange_payload.get("exchange_toadd")
        exchange_items_toadd = exchange_payload.get("exchange_items_toadd", [])
        replacement_items = exchange_payload.get("replacement_items", [])
        customer_outst_payload = exchange_payload.get("customer_outst_payload") or {}
        executing_user_id = datas.get("executing_user_id")

        if current_step == "PRODUCT_VERIFY_UPDATE":
            try:
                async with AsyncOrdersLocalSession() as session:
                    exchange_repo = ExchangeRepo(session=session)
                    order_repo = OrdersRepo(session=session)
                    
                    original_order = exchange_payload.get("original_order") or {}
                    replacement_order_id = original_order.get("id")
                    replacement_ui_id = original_order.get("ui_id")

                    rep_order_items = []
                    for rep_itm in replacement_items:
                        rep_order_items.append(OrderItems(
                            id=generate_uuid(),
                            order_id=replacement_order_id,
                            product_id=rep_itm.get("product_id"),
                            variant_id=rep_itm.get("variant_id"),
                            batch_id=rep_itm.get("batch_id"),
                            serialno_infos=rep_itm.get("serialno_infos"),
                            gst=rep_itm.get("gst"),
                            quantity=rep_itm.get("quantity_in_base"),
                            entered_qty=rep_itm.get("quantity"),
                            entered_unit=rep_itm.get("unit"),
                            buy_price=rep_itm.get("buy_price"),
                            sell_price=rep_itm.get("sell_price"),
                            additional_infos={"is_replacement": True, "exchange_id": exchange_toadd.get("id")}
                        ))


                    session.add_all(rep_order_items)
                    
                    # Set replacement order id to exchange before saving
                    exchange_toadd["replacement_order_id"] = replacement_order_id

                    # 2. Create Exchange
                    exchange_obj = Exchanges(**{
                        k: v for k, v in exchange_toadd.items()
                        if k in (
                            "id", "ui_id", "original_order_id", "replacement_order_id",
                            "shop_id", "customer_id", "total_exchanged_amount",
                            "total_exchanged_qty", "total_replacement_amount",
                            "total_replacement_qty", "payment_infos", "payment_status",
                            "reason", "status"
                        )
                    })

                    exchange_item_objs = [
                        ExchangeItems(**{
                            k: v for k, v in ei.items()
                            if k in ("id", "exchange_id", "order_item_id", "product_id", "quantity", "exchange_amount", "reason")
                        })
                        for ei in exchange_items_toadd
                    ]

                    # Uses the existing repo function which presumably just adds to session and commits
                    # We will just add to session manually to guarantee it's in the same transaction
                    session.add(exchange_obj)
                    session.add_all(exchange_item_objs)
                    await session.commit()


                    ic("Exchange saved to primary DB successfully")

                    # 3. Create Replacement Order in Read DB
                    rep_read_items = []
                    for rep_itm in replacement_items:
                        rep_unit_name = rep_itm.get("entered_unit") or rep_itm.get("unit") or (rep_itm.get("unit_infos") or {}).get("name") or ""
                        rep_read_items.append({
                            "id": generate_uuid(),
                            "product_id": rep_itm.get("product_id"),
                            "ui_id": rep_itm.get("ui_id", ""),  # Ensure ui_id is available
                            "name": rep_itm.get("product_name") or rep_itm.get("name"),
                            "category_infos": rep_itm.get("category_infos"),
                            "unit_infos": rep_itm.get("unit_infos"),
                            "unit": rep_unit_name,
                            "variant_infos": {"variant_id": rep_itm.get("variant_id"), "variant_name": rep_itm.get("variant_name")} if rep_itm.get("variant_id") else None,
                            "batch_infos": {"batch_id": rep_itm.get("batch_id"), "batch_name": rep_itm.get("batch_name")} if rep_itm.get("batch_id") else None,
                            "serialno_infos": rep_itm.get("serialno_infos"),
                            "buy_price": rep_itm.get("buy_price", 0.0),
                            "sell_price": rep_itm.get("sell_price", 0.0),
                            "quantity": rep_itm.get("quantity_in_base"),
                            "entered_qty": rep_itm.get("entered_qty") if rep_itm.get("entered_qty") is not None else rep_itm.get("quantity"),
                            "entered_unit": rep_unit_name,
                            "stock_before": rep_itm.get("stocks_before"),
                            "stock_after": rep_itm.get("stocks_before", 0) - rep_itm.get("quantity_in_base", 0),
                            "returned_quantity": 0.0,
                            "total_amount": rep_itm.get("sell_price", 0.0) * rep_itm.get("quantity_in_base", 1.0),
                            "status": "COMPLETED",
                            "gst": rep_itm.get("gst")
                        })
                    
                    ic("Skipped creating Read DB replacement order, items will be appended to original order")
                    
                    try:
                        rabbitmq_msg_obj = RabbitMQMessagingConfig()
                        
                        # 1. Analytics Event for Original Order Update
                        analytics_payload = {
                            "shop_id": original_order.get("shop_id"),
                            "entity_name": "ORDER",
                            "entity_id": str(replacement_order_id),
                            "action": "UPDATE"
                        }
                        await rabbitmq_msg_obj.publish_event(
                            routing_key="analytics.service.routing.key",
                            exchange_name="analytics.service.exchange",
                            payload=analytics_payload,
                            headers={
                                "entity_name": "sales_event",
                                "service_name": "ANALYTICS",
                                "saga_id": "none",
                                "reply_key": "none",
                                "reply_exchange": "none",
                                "reply_entity_name": "none",
                                "body": analytics_payload
                            }
                        )
                    except Exception as e:
                        ic(f"Failed to publish analytics event: {e}")

                    order_id = exchange_toadd.get("original_order_id")
                    shop_id = exchange_toadd.get("shop_id")
                    exchange_id = exchange_toadd.get("id")
                    ui_id = exchange_toadd.get("ui_id")

                    # ── Update read-DB order doc ──────────────────────────────────
                    if order_id and shop_id:
                        existing_order = await OrderReadDbRepo.get_by_id(order_id=order_id, shop_id=shop_id)
                        if existing_order:
                            if "exchanges" not in existing_order or existing_order["exchanges"] is None:
                                existing_order["exchanges"] = []

                            # Format exchange items for read-DB
                            formatted_exchange_items = []
                            for ei in exchange_items_toadd:
                                orig_item = next(
                                    (o for o in (existing_order.get("items") or []) if o.get("id") == ei.get("order_item_id")),
                                    {}
                                )
                                formatted_exchange_items.append({
                                    "id": ei.get("id"),
                                    "order_item_id": ei.get("order_item_id"),
                                    "product_id": ei.get("product_id"),
                                    "name": orig_item.get("name"),
                                    "ui_id": orig_item.get("ui_id"),
                                    "unit_infos": orig_item.get("unit_infos"),
                                    "category_infos": orig_item.get("category_infos"),
                                    "variant_infos": orig_item.get("variant_infos"),
                                    "batch_infos": orig_item.get("batch_infos"),
                                    "quantity": ei.get("quantity"),
                                    "entered_qty": ei.get("entered_qty"),
                                    "entered_unit": ei.get("entered_unit"),
                                    "buy_price": orig_item.get("buy_price"),
                                    "sell_price": orig_item.get("sell_price"),
                                    "gst": orig_item.get("gst"),
                                    "exchange_amount": ei.get("exchange_amount"),
                                    "reason": ei.get("reason"),
                                })

                                # Increment exchanged_quantity on root item
                                for root_item in (existing_order.get("items") or []):
                                    if root_item.get("id") == ei.get("order_item_id"):
                                        curr_exchanged = root_item.get("exchanged_quantity") or 0.0
                                        root_item["exchanged_quantity"] = curr_exchanged + float(ei.get("quantity", 0))
                                        if "exchanges" not in root_item or root_item["exchanges"] is None:
                                            root_item["exchanges"] = []
                                        root_item["exchanges"].append({
                                            "id": exchange_id,
                                            "quantity": ei.get("quantity"),
                                            "entered_qty": ei.get("entered_qty"),
                                            "entered_unit": ei.get("entered_unit"),
                                            "exchange_amount": ei.get("exchange_amount"),
                                            "reason": ei.get("reason"),
                                            "created_at": exchange_toadd.get("created_at"),
                                        })
                                        break

                            # Append exchange summary to root exchanges array
                            existing_order["exchanges"].append({
                                "id": exchange_id,
                                "ui_id": ui_id,
                                "status": exchange_toadd.get("status", "COMPLETED"),
                                "total_exchanged_amount": exchange_toadd.get("total_exchanged_amount", 0.0),
                                "total_exchanged_qty": exchange_toadd.get("total_exchanged_qty", 0.0),
                                "total_replacement_amount": exchange_toadd.get("total_replacement_amount", 0.0),
                                "total_replacement_qty": exchange_toadd.get("total_replacement_qty", 0.0),
                                "payment_infos": exchange_toadd.get("payment_infos", {}),
                                "payment_status": exchange_toadd.get("payment_status"),
                                "reason": exchange_toadd.get("reason"),
                                "created_at": exchange_toadd.get("created_at"),
                                "items": formatted_exchange_items,
                                "replaced_items": rep_read_items,
                            })

                            await OrderReadDbRepo.replace_order(existing_order)
                            ic("Read DB order updated with exchange info")

                    # ── Publish customer outstanding event ───────────────────────
                    if customer_outst_payload:
                        orig_order_ui_id = str((existing_order.get("ui_id") or existing_order.get("invoice_no") or order_id) if existing_order else order_id)
                        exchange_display_id = str(ui_id or exchange_id)
                        action = customer_outst_payload.get("action", "ADD")
                        amt = float(customer_outst_payload.get("amount", 0.0))

                        if action == "CLEAR":
                            entity_name = "clear_customer_outstanding"
                            body_data = {
                                "id": customer_outst_payload.get("customer_id"),
                                "customer_id": customer_outst_payload.get("customer_id"),
                                "shop_id": customer_outst_payload.get("shop_id"),
                                "payment_infos": [
                                    {"method": "ON_CREDIT", "amount": amt}
                                ],
                                "entity_name": "exchange",
                                "entity_id": orig_order_ui_id,
                                "invoice_no": orig_order_ui_id,
                                "notes": f"Exchange for order {orig_order_ui_id}. Cleared outstanding: ₹{amt:.2f}",
                                "cleared_amount": amt,
                                "total_amount": amt
                            }
                        else:
                            entity_name = "add_customer_outstanding"
                            body_data = {
                                "id": customer_outst_payload.get("customer_id"),
                                "customer_id": customer_outst_payload.get("customer_id"),
                                "shop_id": customer_outst_payload.get("shop_id"),
                                "outstanding_infos": {"amount": amt},
                                "type": "INCREMENT",
                                "payment_infos": [
                                    {"method": "ON_CREDIT", "amount": amt}
                                ],
                                "entity_name": "exchange",
                                "entity_id": orig_order_ui_id,
                                "invoice_no": orig_order_ui_id,
                                "notes": f"Exchange for order {orig_order_ui_id}. Added to credit: ₹{amt:.2f}",
                                "cleared_amount": 0.0,
                                "total_amount": amt
                            }

                        await rabbitmq_msg_obj.publish_event(
                            routing_key="customers.service.routing.key",
                            exchange_name="customers.service.exchange",
                            payload=body_data,
                            headers={
                                "saga_id": "none",
                                "reply_entity_name": "none",
                                "reply_exchange": "none",
                                "reply_key": "none",
                                "service_name": "CUSTOMERS",
                                "entity_name": entity_name,
                                "service": "CUSTOMERS",
                                "body": body_data
                            }
                        )
                        ic(f"Published customer outstanding event: {action} {amt} for exchange {exchange_display_id}")

                    # ── Activity log ─────────────────────────────────────────────
                    try:
                        orig_order_ui_id = (existing_order.get("ui_id") or existing_order.get("invoice_no") or order_id) if existing_order else order_id
                        exchange_display_id = str(ui_id or exchange_id)
                        await rabbitmq_msg_obj.publish_event(
                            routing_key="activity_logs.routing.key",
                            exchange_name="activity_logs.exchange",
                            payload={
                                "shop_id": shop_id,
                                **get_activity_log_user_info(datas.get("user_infos") or datas.get("user_info") or exchange_payload.get("user_infos") or exchange_payload.get("user_info") or current_user_ctx.get()),
                                "service": "Sales-Order",
                                "action": "EXCHANGE",
                                "entity_type": "SALES-EXCHANGE",
                                "entity_id": exchange_display_id,
                                "entity_name": f"{exchange_display_id} ({orig_order_ui_id})" if orig_order_ui_id else exchange_display_id,
                                "description": f"Exchange {exchange_display_id} processed for order {orig_order_ui_id}",
                                "changes": [{"field": "id", "before": str(orig_order_ui_id), "after": "EXCHANGE"}]
                            },
                            headers={}
                        )
                    except Exception as e:
                        ic(f"Failed to publish activity log: {e}")

                    # ── Success notification ──────────────────────────────────────
                    try:
                        from helpers.emit_notification import emit_notification
                        import asyncio
                        asyncio.create_task(emit_notification(
                            title="Order Exchange Processed",
                            message=f"Exchange {exchange_display_id} for order '{orig_order_ui_id}' processed successfully.",
                            type="info",
                            user_id=executing_user_id or shop_id,
                            additional_metadata={"exchange_id": exchange_id, "order_id": order_id}
                        ))
                    except Exception as notification_error:
                        ic(f"Notification error: {notification_error}")

                    return {"success": True, "execution": None}

            except Exception as e:
                try:
                    from helpers.emit_notification import emit_notification
                    import asyncio
                    asyncio.create_task(emit_notification(
                        title="Order Exchange Failed",
                        message=f"Failed to save exchange for order '{exchange_toadd.get('original_order_id')}': {str(e)}",
                        type="error",
                        user_id=executing_user_id or exchange_toadd.get("shop_id")
                    ))
                except Exception as notification_error:
                    ic(f"Notification error: {notification_error}")
                raise e
