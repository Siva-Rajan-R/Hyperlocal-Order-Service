from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.primary_db.repos.order_repo import OrdersRepo
from schemas.v1.db_schemas.order_schema import CreateExchangeDbSchema, CreateExchangeItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema, GetOrderByIdSchema, CreateOrderSchema
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from infras.primary_db.models.order_model import Exchanges, ExchangeItems
from infras.read_db.repos.order_repo import OrderReadDbRepo
from .order_service import OrdersService
from icecream import ic
from ..main import AsyncSession

class ExchangeService:
    def __init__(self,session:AsyncSession):
        self.session=session

    async def process_exchange(self, data: CreateExchangeSchema) -> bool | None:
        from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo
        from core.utils.id_formatter import format_ui_id

        # 1. Create a new replacement order
        order_svc = OrdersService(session=self.session)
        replacement_order_data = CreateOrderSchema(
            shop_id=data.shop_id,
            session_id=generate_uuid(), # Assuming required
            customer_id=data.customer_id,
            customer=data.customer,
            status=OrderStatusEnum.COMPLETED,
            origin=OrderOriginEnum.OFFLINE, # Assuming offline for exchange, can be passed
            type="EXCHANGE",
            payment_infos=data.payments
        )

        original_order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.original_order_id, shop_id=data.shop_id))
        if not original_order_data:
            raise HTTPException(status_code=404, detail="Original order not found")
        orig_items_map = {itm["id"]: itm for itm in original_order_data["items"]}
        
        total_returned_value = 0.0
        for exc_item in data.exchange_items:
            orig_itm = orig_items_map.get(exc_item.return_order_item_id)
            if not orig_itm:
                raise HTTPException(status_code=400, detail=f"Returned item {exc_item.return_order_item_id} not found")
            total_returned_value += (exc_item.quantity_returned * orig_itm.get("sell_price", 0.0))

        # 1. Fetch Pricing and Reserve Inventory for replacement items
        import httpx
        from fastapi import HTTPException
        from datetime import datetime, timezone, timedelta
        
        INVENTORY_URL = "http://127.0.0.1:8000/inventories/inventories"
        enriched_cart_items = []
        total_replacement_value = 0.0
        
        async with httpx.AsyncClient() as client:
            for item in data.replacement_items:
                # 1a. Fetch Pricing Info
                try:
                    prod_resp = await client.get(f"{INVENTORY_URL}/by/id/{data.shop_id}/{item.product_id}")
                    prod_resp.raise_for_status()
                    prod_data = prod_resp.json().get("data")
                    if not prod_data:
                        raise HTTPException(status_code=400, detail=f"Product {item.product_id} not found")
                    
                    target_unit = None
                    for unit in prod_data.get("inventory_units", []):
                        v_id = unit.get("variant_infos", {}).get("id") if unit.get("variant_infos") else None
                        b_id = unit.get("batch_infos", {}).get("id") if unit.get("batch_infos") else None
                        if v_id == item.variant_id and b_id == item.batch_id:
                            target_unit = unit
                            break
                    if not target_unit:
                        target_unit = prod_data.get("inventory_units", [{}])[0]
                    
                    pricing = target_unit.get("pricing_infos") or {}
                    additional_infos = pricing.get("additional_infos") or {}
                    
                    item_dump = item.model_dump()
                    item_dump["buy_price"] = pricing.get("buy_price", 0.0)
                    item_dump["sell_price"] = pricing.get("sell_price", 0.0)
                    item_dump["gst"] = additional_infos.get("gst", "0")
                    item_dump["product_name"] = prod_data.get("name", "Unknown")
                    item_dump["variant_name"] = (target_unit.get("variant_infos") or {}).get("name")
                    item_dump["batch_name"] = (target_unit.get("batch_infos") or {}).get("name")
                    item_dump["stocks_before"] = target_unit.get("stock_infos", {}).get("physical_stocks", 0.0)
                    enriched_cart_items.append(item_dump)
                    total_replacement_value += (item_dump["sell_price"] * item.quantity)
                except httpx.HTTPError as e:
                    raise HTTPException(status_code=500, detail=f"Failed to fetch details for {item.product_id}")

                # 1b. Reserve Stock
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
                payload = {
                    "session_id": replacement_order_data.session_id,
                    "product_id": item.product_id,
                    "variant_id": item.variant_id,
                    "batch_id": item.batch_id,
                    "shop_id": data.shop_id,
                    "qty": item.quantity,
                    "expires_at": expires_at.isoformat()
                }
                try:
                    res = await client.post(f"{INVENTORY_URL}/reservations/reserve", json=payload)
                    res.raise_for_status()
                except httpx.HTTPError as e:
                    raise HTTPException(status_code=500, detail=f"Failed to reserve stock for {item.product_id}")

            # 1c. Commit Inventory reservations
            try:
                res = await client.post(
                    f"{INVENTORY_URL}/reservations/commit", 
                    json={
                        "session_id": replacement_order_data.session_id
                    }
                )
                res.raise_for_status()
            except httpx.HTTPError as e:
                raise HTTPException(status_code=500, detail="Failed to commit inventory reservations")

            # Emit Stock_Mov_Adj_Service event for replacement items
            commit_items = []
            origin_tag = "ONLINE_SALES_EXCHANGE" if getattr(replacement_order_data.origin, 'value', replacement_order_data.origin) == "ONLINE" else "OFFLINE_SALES_EXCHANGE"
            for item in enriched_cart_items:
                stocks_before = item.get("stocks_before", 0.0)
                qty = item.get("quantity", 0.0)
                commit_items.append({
                    "product_id": item.get("product_id"),
                    "name": item.get("product_name", "Unknown"),
                    "ui_id": "",
                    "variant_id": item.get("variant_id"),
                    "variant_name": item.get("variant_name"),
                    "batch_id": item.get("batch_id"),
                    "batch_name": item.get("batch_name"),
                    "type": "DECREMENT",
                    "stocks_before": stocks_before,
                    "stocks_adjusted": qty,
                    "stocks_after": stocks_before - qty,
                    "storage_location": "Default"
                })
            
            if commit_items:
                from messaging.main import RabbitMQMessagingConfig
                from datetime import datetime, timezone
                
                rabbitmq_msg_obj = RabbitMQMessagingConfig()
                routing_key = "stockmovadj.service.routing.key"
                exchange_name = "stockmovadj.service.exchange"
                
                payload = {
                    "shop_id": data.shop_id,
                    "type": origin_tag,
                    "date": datetime.now(timezone.utc).isoformat(),
                    "description": f"Automated stock movement via exchange replacement for {origin_tag}",
                    "items": commit_items
                }
                
                headers = {
                    "routing_key": routing_key,
                    "exchange_name": exchange_name,
                    "entity_name": "create_adjustment",
                    "service_name": "STOCK_MOV_ADJ",
                    "saga_id": "none",
                    "reply_key": "none",
                    "reply_exchange": "none",
                    "reply_entity_name": "none",
                    "body": payload
                }
                
                await rabbitmq_msg_obj.publish_event(
                    routing_key=routing_key,
                    exchange_name=exchange_name,
                    payload=payload,
                    headers=headers
                )

        # 2. Create the new replacement order
        new_order_res = await order_svc.create(data=replacement_order_data, cart_items=enriched_cart_items)
        
        if not new_order_res:
            return False

        replacement_order_id = new_order_res['id']

        # 2. Track the exchange link
        exchange_id = generate_uuid()
        
        shop_config = await ShopIdConfigReadDbRepo.get_config(data.shop_id)
        exchange_config = shop_config.get("exchange", {})
        prefix = exchange_config.get("prefix", "EXC")
        start_from = exchange_config.get("start_from", 1)

        raw_sequence = await OrdersRepo(session=self.session).get_next_sequence(data.shop_id, start_from)
        ui_id_str = format_ui_id(prefix, start_from, raw_sequence)

        amount_diff = total_replacement_value - total_returned_value
        calculated_additional_amount_paid = max(0.0, amount_diff)
        calculated_amount_refunded = max(0.0, -amount_diff)
        
        calculated_clear_outstanding_amount = 0.0
        calculated_add_outstanding_amount = 0.0
        
        async def process_credit(credit_amount: float):
            nonlocal calculated_clear_outstanding_amount, calculated_add_outstanding_amount
            if credit_amount > 0:
                if not data.customer_id:
                    raise HTTPException(status_code=400, detail="Customer ID required for ON CREDIT payment")
                
                if amount_diff < 0:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(f"http://127.0.0.1:8007/customers/by/id/{data.shop_id}/{data.customer_id}")
                        if resp.status_code != 200:
                            raise HTTPException(status_code=400, detail="Failed to fetch customer details")
                        cust_data = resp.json().get("data", {})
                        outstanding = cust_data.get("outstanding_infos", {}) or {}
                        balance = outstanding.get("amount", 0.0)
                        
                        if balance <= 0:
                            raise HTTPException(status_code=400, detail="Customer has no outstanding balance to clear")
                    
                    calculated_clear_outstanding_amount += credit_amount
                elif amount_diff > 0:
                    calculated_add_outstanding_amount += credit_amount

        for payment in data.payments:
            if "mode" in payment or "method" in payment:
                method = payment.get("mode") or payment.get("method")
                amt = float(payment.get("amount", 0.0))
                if method and str(method).lower() == "on credit":
                    await process_credit(amt)
            else:
                for method, amount in payment.items():
                    try:
                        amt = float(amount)
                    except (ValueError, TypeError):
                        amt = 0.0
                    if str(method).lower() == "on credit":
                        await process_credit(amt)

        exchange_db_data = CreateExchangeDbSchema(
            id=exchange_id,
            ui_id=ui_id_str,
            original_order_id=data.original_order_id,
            replacement_order_id=replacement_order_id,
            shop_id=data.shop_id,
            customer_id=data.customer_id,
            additional_amount_paid=calculated_additional_amount_paid,
            amount_refunded=calculated_amount_refunded,
            clear_outstanding_amount=calculated_clear_outstanding_amount,
            reason=data.reason,
            status=data.status.value if hasattr(data.status, 'value') else data.status
        )

        exchange_items_to_add = []
        item_updates = []
        for item in data.exchange_items:
            exc_item_id = generate_uuid()
            
            qty_replaced = 0.0
            for r_item in data.replacement_items:
                if r_item.product_id == item.replacement_product_id:
                    qty_replaced += r_item.quantity
                    
            exchange_items_to_add.append(
                ExchangeItems(**CreateExchangeItemDbSchema(
                    id=exc_item_id,
                    exchange_id=exchange_id,
                    return_order_item_id=item.return_order_item_id,
                    replacement_product_id=item.replacement_product_id,
                    quantity_returned=item.quantity_returned,
                    quantity_replaced=qty_replaced,
                    reason=item.reason
                ).model_dump())
            )
            item_updates.append(
                {
                    'b_item_id': item.return_order_item_id,
                    'b_order_id': data.original_order_id,
                    'b_status': data.status.value if hasattr(data.status, 'value') else data.status,
                    'b_reason': item.reason,
                    'b_returned_quantity': item.quantity_returned
                }
            )

        exchange_obj = Exchanges(**exchange_db_data.model_dump())
        
        from infras.primary_db.repos.exchange_repo import ExchangeRepo
        await ExchangeRepo(session=self.session).create_exchange_with_items(exchange_obj, exchange_items_to_add)
        
        # Update original order items
        await OrdersRepo(session=self.session).update_order_item_bulk_adv(data=item_updates)
        
        await self.session.commit()

        # Sync original order
        order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.original_order_id, shop_id=data.shop_id))
        if order_data:
            await OrderReadDbRepo.replace_order(data=dict(order_data))

        # Publish event if clearing outstanding (adding to their balance) or deducting from their balance
        if calculated_clear_outstanding_amount > 0 and data.customer_id:
            from messaging.msgqueue_services.order_msgqueue_service import MessagingQueueOrderService
            msg_service = MessagingQueueOrderService()
            # if we are clearing outstanding (like a refund, giving credit back)
            await msg_service.publish_customer_outstanding_update(
                shop_id=data.shop_id,
                customer_id=data.customer_id,
                amount=calculated_clear_outstanding_amount,
                action="CLEAR",
                reference_id=exchange_id
            )
            
        if calculated_add_outstanding_amount > 0 and data.customer_id:
            from messaging.msgqueue_services.order_msgqueue_service import MessagingQueueOrderService
            msg_service = MessagingQueueOrderService()
            await msg_service.publish_customer_outstanding_update(
                shop_id=data.shop_id,
                customer_id=data.customer_id,
                amount=calculated_add_outstanding_amount,
                action="ADD",
                reference_id=exchange_id
            )

        # Increment stock for returned items in exchange
        stock_updates = []
        stock_mov_adj_items_returned = []
        origin_tag_returned = f"{replacement_order_data.origin.value}_SALES_EXCHANGE" if hasattr(replacement_order_data.origin, 'value') else f"{replacement_order_data.origin}_SALES_EXCHANGE"
        
        async with httpx.AsyncClient() as client:
            for item in data.exchange_items:
                orig_item = orig_items_map.get(item.return_order_item_id)
                if not orig_item:
                    continue
                
                variant_id = orig_item.get("variant_id")
                batch_id = orig_item.get("batch_id")
                
                # Fetch inventory for the returned product
                res = await client.get(f"{INVENTORY_URL}/by/id/{data.shop_id}/{orig_item['product_id']}")
                if res.status_code == 200:
                    prod_data = res.json().get("data", {})
                    if prod_data:
                        inventory_units = prod_data.get("inventory_units", [])
                        stock_id = None
                        stocks_before = 0.0
                        for unit in inventory_units:
                            u_var = (unit.get("variant_infos") or {}).get("id")
                            u_bat = (unit.get("batch_infos") or {}).get("id")
                            if u_var == variant_id and u_bat == batch_id:
                                stock_info = unit.get("stock_infos")
                                if stock_info:
                                    stock_id = stock_info.get("id")
                                    stocks_before = stock_info.get("physical_stocks", 0.0)
                                    u_var_name = (unit.get("variant_infos") or {}).get("name")
                                    u_bat_name = (unit.get("batch_infos") or {}).get("name")
                                break
                        
                        if stock_id:
                            stock_updates.append({
                                "id": stock_id,
                                "product_id": orig_item["product_id"],
                                "shop_id": data.shop_id,
                                "variant_id": variant_id,
                                "batch_id": batch_id,
                                "physical_stocks": item.quantity_returned,
                                "type": "INCREMENT"
                            })
                            
                            stock_mov_adj_items_returned.append({
                                "product_id": orig_item["product_id"],
                                "name": prod_data.get("name", "Unknown"),
                                "ui_id": "",
                                "variant_id": variant_id,
                                "variant_name": u_var_name,
                                "batch_id": batch_id,
                                "batch_name": u_bat_name,
                                "type": "INCREMENT",
                                "stocks_before": stocks_before,
                                "stocks_adjusted": item.quantity_returned,
                                "stocks_after": stocks_before + item.quantity_returned,
                                "storage_location": "Default"
                            })

        if stock_updates:
            from messaging.msgqueue_services.order_msgqueue_service import MessagingQueueOrderService
            msg_service = MessagingQueueOrderService()
            await msg_service.publish_inventory_stock_update(
                shop_id=data.shop_id,
                updates=stock_updates
            )
            
        if stock_mov_adj_items_returned:
            from messaging.main import RabbitMQMessagingConfig
            from datetime import datetime, timezone
            
            rabbitmq_msg_obj = RabbitMQMessagingConfig()
            routing_key = "stockmovadj.service.routing.key"
            exchange_name = "stockmovadj.service.exchange"
            
            payload = {
                "shop_id": data.shop_id,
                "type": origin_tag_returned,
                "date": datetime.now(timezone.utc).isoformat(),
                "description": f"Automated stock movement via exchange return for {origin_tag_returned}",
                "items": stock_mov_adj_items_returned
            }
            
            headers = {
                "routing_key": routing_key,
                "exchange_name": exchange_name,
                "entity_name": "create_adjustment",
                "service_name": "STOCK_MOV_ADJ",
                "saga_id": "none",
                "reply_key": "none",
                "reply_exchange": "none",
                "reply_entity_name": "none",
                "body": payload
            }
            
            await rabbitmq_msg_obj.publish_event(
                routing_key=routing_key,
                exchange_name=exchange_name,
                payload=payload,
                headers=headers
            )

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
                    "action": "CREATE",
                    "entity_type": "Exchange",
                    "entity_id": exchange_id,
                    "description": f"Created exchange {ui_id_str} for order {data.original_order_id}",
                    "changes": [{"field": "exchange_id", "before": "", "after": str(exchange_id)}]
                },
                headers={}
            )
        except Exception as e:
            ic(f"Failed to publish activity log: {e}")

        return True
