from typing import Optional
from fastapi import HTTPException
from icecream import ic
import httpx
import os

from core.data_formats.enums.order_enum import OrderStatusEnum
from infras.primary_db.repos.order_repo import OrdersRepo
from infras.primary_db.repos.exchange_repo import ExchangeRepo
from infras.primary_db.models.order_model import Exchanges, ExchangeItems
from infras.read_db.repos.order_repo import OrderReadDbRepo
from schemas.v1.db_schemas.order_schema import CreateExchangeDbSchema, CreateExchangeItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema, GetOrderByIdSchema
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from integrations.utility_service import get_ui_id
from integrations.customer_service import get_customer_info
from messaging.saga_producer import SagaProducer, CreateSagaStateSchema, SagaStatusEnum
from hyperlocal_platform.core.enums.saga_state_enum import SagaStepsValueEnum
from hyperlocal_platform.core.typed_dicts.saga_status_typ_dict import SagaStateExecutionTypDict
from messaging.main import RabbitMQMessagingConfig
from ..main import AsyncSession


INVENTORY_URL = f"{os.getenv('INVENTORY_SERVICE_URL', 'http://127.0.0.1:8000')}/inventories/inventories"
CUSTOMER_SERVICE_URL = f"{os.getenv('CUSTOMER_SERVICE_URL', 'http://127.0.0.1:8007')}/customers"


class ExchangeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_exchange(self, data: CreateExchangeSchema, executing_user_id: Optional[str] = None) -> bool | None:
        try:
            rabbitmq_connection = RabbitMQMessagingConfig()
            exchange_id = generate_uuid()

            # ── 1. Fetch original order ──────────────────────────────────────────
            order_data = await OrdersRepo(session=self.session).getby_id(
                data=GetOrderByIdSchema(id=data.original_order_id, shop_id=data.shop_id)
            )
            if not order_data:
                raise HTTPException(status_code=404, detail="Original order not found")

            items_map = {itm["id"]: itm for itm in (order_data.get("items") or [])}

            # Merge denormalized fields from read-DB (unit_infos, name, ui_id, etc.)
            read_db_order = await OrderReadDbRepo.get_by_id(
                shop_id=data.shop_id,
                order_id=data.original_order_id,
            )
            if read_db_order:
                for rd_itm in (read_db_order.get("items") or []):
                    rd_id = rd_itm.get("id")
                    if rd_id and rd_id in items_map:
                        for field in ("unit_infos", "category_infos", "name", "ui_id", "variant_infos"):
                            if field in rd_itm:
                                items_map[rd_id][field] = rd_itm[field]

            # ── 2. Get UI ID for this exchange ────────────────────────────────────
            ui_id_res = await get_ui_id(shop_id=data.shop_id)
            ui_id = f"{ui_id_res.get('prefix')}-{ui_id_res.get('current_number')}"

            order_id = order_data["id"]
            shop_id = data.shop_id
            customer_id = order_data.get("customer_id")

            # ── 3. Process each returned (exchanged-out) item with sub-unit support ─
            exchange_items_toadd = []
            products_toupdate = []       # stock INCREMENT for returned items
            total_exchanged_qty = 0.0
            total_exchanged_amount = 0.0

            for exc_item in data.exchange_items:
                exc_item_dict = exc_item.model_dump()
                order_item_id = exc_item_dict["order_item_id"]  # new field name

                if order_item_id not in items_map:
                    raise HTTPException(status_code=400, detail=f"Order item '{order_item_id}' not found in original order")

                orig = items_map[order_item_id]

                # ── Sub-unit conversion ──────────────────────────────────────────
                unit_infos = orig.get("unit_infos") or {}
                base_unit_name = unit_infos.get("name", "")
                sub_units = unit_infos.get("sub_units", []) or []

                conversion_factor = 1.0
                entered_unit = exc_item_dict.get("unit")
                if entered_unit:
                    if entered_unit.lower() == base_unit_name.lower():
                        conversion_factor = 1.0
                    else:
                        matched_sub = next(
                            (su for su in sub_units if su and su.get("name", "").lower() == entered_unit.lower()),
                            None
                        )
                        if not matched_sub:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Invalid unit '{entered_unit}'. Base unit: '{base_unit_name}', sub-units: {[su.get('name') for su in sub_units if su]}"
                            )
                        conversion_factor = float(matched_sub.get("factor", 1.0))

                qty_in_base = exc_item_dict["quantity"] * conversion_factor  # new field name

                # ── Validate qty doesn't exceed what's available to exchange ──────
                original_qty = float(orig.get("quantity") or 0.0)
                returned_qty = float(orig.get("returned_quantity") or 0.0)
                exchanged_qty = float(orig.get("exchanged_quantity") or 0.0)
                already_consumed = returned_qty + exchanged_qty

                if already_consumed >= original_qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"All qty for item '{order_item_id}' has already been returned or exchanged "
                               f"(original: {original_qty}, returned: {returned_qty}, exchanged: {exchanged_qty})"
                    )

                available_qty = original_qty - already_consumed
                if qty_in_base > available_qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Exchange qty ({qty_in_base}) exceeds available qty ({available_qty}) for item '{order_item_id}'. "
                               f"Original: {original_qty}, already returned: {returned_qty}, already exchanged: {exchanged_qty}"
                    )

                sell_price = orig.get("sell_price", 0.0)
                item_exchange_amount = qty_in_base * sell_price
                total_exchanged_qty += qty_in_base
                total_exchanged_amount += item_exchange_amount

                # ── Handle Serial Numbers for Exchange Item (returned item coming in) ──
                founded_serialno = []
                existing_serial_ids = [s.get('id') for s in (orig.get('serialno_infos') or [])]
                
                # Extract already returned/exchanged serial numbers from MongoDB read DB order
                already_returned_or_exchanged_sns = set()
                if read_db_order:
                    # Collect serial numbers from past returns
                    for ret in (read_db_order.get("returns") or []):
                        for r_item in (ret.get("items") or []):
                            if r_item.get("order_item_id") == order_item_id:
                                for sn in (r_item.get("serialno_infos") or []):
                                    if sn.get("id"):
                                        already_returned_or_exchanged_sns.add(sn.get("id"))
                    # Collect serial numbers from past exchanges
                    for exc in (read_db_order.get("exchanges") or []):
                        for e_item in (exc.get("items") or []):
                            if e_item.get("order_item_id") == order_item_id:
                                for sn in (e_item.get("serialno_infos") or []):
                                    if sn.get("id"):
                                        already_returned_or_exchanged_sns.add(sn.get("id"))

                for serialno in (exc_item.serialno_infos or []):
                    serialno_dict = serialno.model_dump() if hasattr(serialno, 'model_dump') else serialno
                    if serialno_dict['id'] not in existing_serial_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Serial number '{serialno_dict['id']}' not found in original order item '{order_item_id}'"
                        )
                    
                    if serialno_dict['id'] in already_returned_or_exchanged_sns:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Serial number '{serialno_dict['id']}' has already been returned or exchanged."
                        )
                        
                    matched_sn = next((s for s in (orig.get('serialno_infos') or []) if s.get('id') == serialno_dict['id']), None)
                    if matched_sn:
                        founded_serialno.append(matched_sn)

                exchange_items_toadd.append({
                    "id": generate_uuid(),
                    "exchange_id": exchange_id,
                    "order_item_id": order_item_id,
                    "product_id": orig.get("product_id", ""),
                    "quantity": qty_in_base,
                    "entered_qty": exc_item_dict["quantity"],
                    "entered_unit": entered_unit or base_unit_name,
                    "exchange_amount": item_exchange_amount,
                    "reason": exc_item_dict.get("reason"),
                })

                products_toupdate.append({
                    "shop_id": shop_id,
                    "product_id": orig.get("product_id"),
                    "variant_id": orig.get("variant_id"),
                    "batch_infos": {"id": orig["batch_id"]} if orig.get("batch_id") else None,
                    "serialno_infos": founded_serialno,
                    "stocks": qty_in_base,
                    "entity_name": "OFFLINE_SALES_EXCHANGE",
                    "type": "INCREMENT",
                    "create_stock_mov_adj": True,
                })

            # ── 4. Fetch replacement items pricing & calculate total ───────────────
            enriched_replacement_items = []
            total_replacement_qty = 0.0
            total_replacement_amount = 0.0

            async with httpx.AsyncClient() as client:
                for rep_item in data.replacement_items:
                    try:
                        resp = await client.get(f"{INVENTORY_URL}/by/id/{shop_id}/{rep_item.product_id}")
                        resp.raise_for_status()
                        prod_data = resp.json().get("data")
                        if not prod_data:
                            raise HTTPException(status_code=400, detail=f"Product '{rep_item.product_id}' not found")
                    except httpx.HTTPError:
                        raise HTTPException(status_code=500, detail=f"Failed to fetch product '{rep_item.product_id}'")

                    # ── Resolve pricing from the correct level ─────────────────────
                    type_infos = prod_data.get("type_infos") or {}
                    pricing = {}
                    matched_batch = None
                    matched_variant = None

                    if rep_item.batch_id:
                        batch_list = prod_data.get("batch_infos") or []
                        matched_batch = next(
                            (b for b in batch_list if b.get("id") == rep_item.batch_id),
                            None
                        )
                        if matched_batch:
                            pricing = matched_batch.get("pricing_infos") or {}
                    elif rep_item.variant_id:
                        variant_list = prod_data.get("variant_infos") or []
                        matched_variant = next(
                            (v for v in variant_list if v.get("id") == rep_item.variant_id),
                            None
                        )
                        if matched_variant:
                            pricing = matched_variant.get("pricing_infos") or {}
                    else:
                        pricing = prod_data.get("pricing_infos") or {}

                    gst = prod_data.get("gst") or "0"

                    # ── Sub-unit conversion for replacement qty ──────────────────
                    rep_unit_infos = prod_data.get("unit_infos") or {}
                    rep_base_unit = rep_unit_infos.get("name", "")
                    rep_sub_units = rep_unit_infos.get("sub_units", []) or []
                    rep_conversion_factor = 1.0
                    rep_entered_unit = rep_item.unit
                    if rep_entered_unit:
                        if rep_entered_unit.lower() == rep_base_unit.lower():
                            rep_conversion_factor = 1.0
                        else:
                            rep_matched_sub = next(
                                (su for su in rep_sub_units if su and su.get("name", "").lower() == rep_entered_unit.lower()),
                                None
                            )
                            if not rep_matched_sub:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"Invalid unit '{rep_entered_unit}' for replacement product '{rep_item.product_id}'. "
                                           f"Base unit: '{rep_base_unit}', sub-units: {[su.get('name') for su in rep_sub_units if su]}"
                                )
                            rep_conversion_factor = float(rep_matched_sub.get("factor", 1.0))

                    rep_qty_in_base = rep_item.quantity * rep_conversion_factor

                    # ── Handle Serial Numbers for Replacement Item (stock going out) ──
                    replacement_serialno = []
                    for serialno in (rep_item.serialno_infos or []):
                        serialno_dict = serialno.model_dump() if hasattr(serialno, 'model_dump') else serialno
                        replacement_serialno.append(serialno_dict)

                    rep_dump = rep_item.model_dump()
                    rep_dump["buy_price"] = pricing.get("buy_price", 0.0)
                    rep_dump["sell_price"] = pricing.get("sell_price", 0.0)
                    rep_dump["gst"] = gst
                    rep_dump["product_name"] = prod_data.get("name", "Unknown")
                    rep_dump["variant_name"] = (matched_variant or {}).get("name") if matched_variant else None
                    rep_dump["batch_name"] = (matched_batch or {}).get("name") if matched_batch else None
                    stock_source = matched_batch or matched_variant or prod_data
                    rep_dump["stocks_before"] = (stock_source.get("stock_infos") or {}).get("physical_stocks", 0.0)
                    rep_dump["quantity_in_base"] = rep_qty_in_base
                    enriched_replacement_items.append(rep_dump)

                    total_replacement_qty += rep_qty_in_base
                    total_replacement_amount += rep_dump["sell_price"] * rep_qty_in_base

                    # ── DECREMENT stock for replacement item (customer takes it) ──
                    products_toupdate.append({
                        "shop_id": shop_id,
                        "product_id": rep_item.product_id,
                        "variant_id": rep_item.variant_id,
                        "batch_infos": {"id": rep_item.batch_id} if rep_item.batch_id else None,
                        "serialno_infos": replacement_serialno,
                        "stocks": rep_qty_in_base,
                        "entity_name": "OFFLINE_SALES_EXCHANGE",   # DECREMENT — stock goes out
                        "type": "DECREMENT",
                        "create_stock_mov_adj": True,
                    })

            # ── 5. Calculate diff ─────────────────────────────────────────────────
            # diff > 0 → replacement costs MORE → customer pays extra
            # diff < 0 → exchanged item costs MORE → shopkeeper gives back / clears outstanding
            amount_diff = total_replacement_amount - total_exchanged_amount

            # ── 6. Process payments: validate ON_CREDIT scenarios ─────────────────
            total_paid_cash = 0.0
            on_credit_amount = 0.0

            for payment in (data.payments or []):
                # Now using ExchangePaymentSchema objects with .method and .amount
                method = payment.method if hasattr(payment, 'method') else (payment.get("method") or "")
                amt = float(payment.amount if hasattr(payment, 'amount') else payment.get("amount", 0.0))
                if str(method).strip().upper() in ("ON_CREDIT", "ON CREDIT"):
                    on_credit_amount += amt
                else:
                    total_paid_cash += amt

            customer_outst_payload = {}

            if on_credit_amount > 0:
                if not customer_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot use ON_CREDIT payment for walk-in customers"
                    )

                if amount_diff > 0:
                    # Replacement costs MORE → customer owes more → ADD to customer outstanding
                    # ON_CREDIT means: "I'll pay later" → add outstanding
                    customer_outst_payload = {
                        "customer_id": customer_id,
                        "shop_id": shop_id,
                        "amount": on_credit_amount,
                        "action": "ADD"
                    }
                else:
                    # Replacement costs LESS → shopkeeper owes → clear customer's outstanding
                    # ON_CREDIT means: "deduct from my outstanding"
                    customer_infos = await get_customer_info(shop_id=shop_id, customer_id=customer_id)
                    if not customer_infos:
                        raise HTTPException(status_code=400, detail="Failed to fetch customer details")

                    customer_existing_outst = (customer_infos.get("outstanding_infos") or {}).get("amount", 0.0)
                    if not customer_existing_outst or customer_existing_outst <= 0:
                        raise HTTPException(
                            status_code=400,
                            detail="Customer has no outstanding balance to clear via ON_CREDIT"
                        )
                    if on_credit_amount > customer_existing_outst:
                        raise HTTPException(
                            status_code=400,
                            detail=f"ON_CREDIT amount ({on_credit_amount}) exceeds customer outstanding balance ({customer_existing_outst})"
                        )
                    customer_outst_payload = {
                        "customer_id": customer_id,
                        "shop_id": shop_id,
                        "amount": on_credit_amount,
                        "action": "CLEAR"
                    }

            # ── 7. Determine payment_status ───────────────────────────────────────
            total_expected = abs(amount_diff) if amount_diff > 0 else 0.0  # only applicable when customer owes
            if amount_diff <= 0:
                payment_status = "COMPLETED"  # shopkeeper gives back — no customer payment needed
            elif total_paid_cash + on_credit_amount >= total_expected:
                payment_status = "COMPLETED"
            else:
                payment_status = "PARTIALLY_PAID"

            # ── 8. Build exchange DB record ───────────────────────────────────────
            exchange_db = CreateExchangeDbSchema(
                id=exchange_id,
                ui_id=ui_id,
                original_order_id=data.original_order_id,
                replacement_order_id="",   # Will be set in saga step after replacement order is created
                shop_id=shop_id,
                customer_id=customer_id,
                total_exchanged_amount=total_exchanged_amount,
                total_exchanged_qty=total_exchanged_qty,
                total_replacement_amount=total_replacement_amount,
                total_replacement_qty=total_replacement_qty,
                payment_infos={"payments": [p.model_dump() if hasattr(p, 'model_dump') else p for p in (data.payments or [])]},
                payment_status=payment_status,
                reason=data.reason,
                status="COMPLETED",
            )

            # Strip temp fields from exchange_items_toadd before DB insert
            clean_exchange_items = []
            for ei in exchange_items_toadd:
                clean_exchange_items.append({k: v for k, v in ei.items() if k != "orig_item"})

            # ── 9. Build saga data ────────────────────────────────────────────────
            saga_payload = {
                "exchange_data": {
                    "exchange_toadd": exchange_db.model_dump(),
                    "exchange_items_toadd": clean_exchange_items,
                    "replacement_items": enriched_replacement_items,
                    "customer_outst_payload": customer_outst_payload,
                    "amount_diff": amount_diff,
                    "payment_status": payment_status,
                },
                "executing_user_id": executing_user_id,
            }

            saga_id = generate_uuid()
            steps = {
                "PRODUCT_VERIFY_UPDATE": SagaStepsValueEnum.PENDING,
            }

            # products_toupdate = INCREMENT stock for returned items
            await SagaProducer.emit(
                session=self.session,
                saga_payload=CreateSagaStateSchema(
                    id=saga_id,
                    status=SagaStatusEnum.IN_PROGRESS,
                    type="ORDER_EXCHANGED",
                    steps=steps,
                    execution=SagaStateExecutionTypDict(
                        step="PRODUCT_VERIFY_UPDATE",
                        service="PRODUCTS"
                    ),
                    data=saga_payload,
                ),
                routing_key="products.service.routing.key",
                exchange_name="products.service.exchange",
                headers={
                    "reply_key": "orders.producer.routing.key",
                    "reply_exchange": "orders.producer.exchange",
                    "reply_entity_name": "create_exchange",
                    "reply_service_name": "ORDERS_EXCHANGE",
                    "service_name": "PRODUCTS",
                    "entity_name": "update_bulk_prodinv",
                    "body": products_toupdate,
                },
            )

            return True

        except Exception as e:
            try:
                from helpers.emit_notification import emit_notification
                import asyncio
                asyncio.create_task(emit_notification(
                    title="Order Exchange Process Failed",
                    message=f"Failed to initiate order exchange: {str(e.detail) if hasattr(e, 'detail') else str(e)}",
                    type="error",
                    user_id=executing_user_id or data.shop_id
                ))
            except Exception as notification_error:
                ic(f"Notification error: {notification_error}")
            raise e
