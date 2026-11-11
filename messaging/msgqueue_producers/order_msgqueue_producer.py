from core.utils.user_context import current_user_ctx
from core.utils.user_context import get_activity_log_user_info
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
from infras.primary_db.models.order_model import OrderItems, Orders
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema
from integrations.utility_service import get_ui_id, get_shop_category, get_shop_unit
from integrations.shop_service import get_shop_info
from core.data_formats.enums.order_enum import OrderOriginEnum


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

class MessagingQueueOrderProducer:

    def __init__(self, headers: dict, payload: dict, saga_datas: dict):
        self.headers = headers
        self.payload = payload
        self.saga_datas = saga_datas

    

    async def create_order(self):
        """
        Migrated Order Flow: Extracts order details from the saga data,
        generates sequential UI IDs, saves to primary DB, replicates to read DB,
        and fires an activity log via RabbitMQ.
        """
        ic(self.headers, self.payload, self.saga_datas)
        
        execution = self.saga_datas.get('execution', {})
        current_step = execution.get('step')
        datas = self.saga_datas.get("data", {})
        order_payload = datas.get("orders")  # This is a dict from saga data
        cart_items = order_payload.get("items", []) if order_payload else []

        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        
        if not order_payload or not cart_items:
            ic("Missing 'order_payload' or 'cart_items' in saga data context.")
            return {"success": False, "reason": "Missing required payload data"}


        if current_step == "VERIFY_CUSTOMER":
            ic("Inside verify customer")
            customer_data=datas.get("customers")
            if not customer_data:
                ic("Invalid Customer Info")
                return False

            return await get_product_bulk(
                order_data=order_payload,
                headers=self.headers,
                payload=self.payload,
                rabbitmq_connection=rabbitmq_msg_obj

            )


        # STEP-3: PARSE AND PERSIST TRANSACTION RECORD
        if current_step == "FETCHING_PRODUCTS":
            try:
                order_id = generate_uuid()
                
                ui_id = order_payload.get("ui_id")
                if not ui_id:
                    ui_id_res = await get_ui_id(shop_id=order_payload.get('shop_id'))
                    if isinstance(ui_id_res, dict) and "prefix" in ui_id_res:
                        ui_id = f"{ui_id_res.get('prefix')}-{ui_id_res.get('current_number')}"
                    else:
                        ui_id = f"ORD-{int(datetime.datetime.utcnow().timestamp())}"
                product_res = datas.get("products") or []
                shop_id = order_payload.get("shop_id")
                calculation_infos = order_payload.get("calculation_infos") or {}
                charges_infos = order_payload.get("charges_infos") or {}
                payment_infos = order_payload.get("payment_infos") or {}
                origin=order_payload['origin']
                status=order_payload['status']
                customer_id=order_payload['customer_id']
                ord_date=order_payload.get("date", datetime.datetime.now()) or datetime.datetime.now()
                if isinstance(ord_date, str):
                    ord_date = datetime.datetime.strptime(
                        ord_date,
                        "%Y-%m-%d"
                    ).date()

                item_infos = {
                    'total_order_items': 0,
                    'total_order_qty': 0,
                    'total_order_cost': 0,
                    'total_order_amount': 0,
                    'total_order_gst_amount': 0.0
                }

                # Fetch shop details to check if registered for GST
                shop_infos = await get_shop_info(shop_id=shop_id)
                shop_gst_registered = False
                if shop_infos:
                    biz_infos = shop_infos.get("business_infos") or {}
                    gst_infos = biz_infos.get("gst_infos") or {}
                    shop_gst_registered = bool(
                        gst_infos.get("registered") or
                        gst_infos.get("number") or
                        biz_infos.get("gstin") or
                        biz_infos.get("gst_number") or
                        shop_infos.get("gstin") or
                        shop_infos.get("gst_number")
                    )
                else:
                    shop_gst_registered = True
                ic(shop_gst_registered)

                product_res = datas.get("products") or []
                validated_payload_map: Dict[str, List[dict]] = {}
                for prod in cart_items:
                    p_id = prod['product_id']
                    if p_id not in validated_payload_map:
                        validated_payload_map[p_id] = []
                    validated_payload_map[p_id].append(prod)

                read_items = []
                order_items_toadd = []

                async with AsyncOrdersLocalSession() as session:
                    repo = OrdersRepo(session)

                    ic(product_res)
                    for prod_db in product_res:
                        ic(prod_db)
                        product_id = prod_db['id']
                        product_name = prod_db['name']
                        db_ui_id = prod_db['ui_id']
                        
                        type_infos = prod_db.get('type_infos', {})
                        has_variant = type_infos.get('has_variant', False)
                        has_batch = type_infos.get('has_batch', False)
                        has_serialno = type_infos.get('has_serialno', False)
                        
                        # Always preserve the product's GST breakdown even if the shop itself isn't GST-registered;
                        # registration status is tracked separately via calculation_infos['include_gst'].
                        product_gst = prod_db.get('gst') or prod_db.get('gst_rate') or prod_db.get('tax_rate') or '0%'
                        if isinstance(product_gst, (int, float)):
                            product_gst = f"{product_gst}%"
                        gst = product_gst

                        category_infos=prod_db.get('category_infos') or {}
                        unit_infos=prod_db.get('unit_infos') or {}

                        incoming_item_matches = validated_payload_map.get(product_id) or []
                        
                        for itm in incoming_item_matches:
                            variant_id = itm.get('variant_id')
                            batch_id = itm.get('batch_id')
                            batch_target_name = itm.get('batch_name') or itm.get('batch_target_name')

                            variant_name = ''
                            batch_infos = {}
                            serialno_infos = []
                            stock_infos = {}
                            stl_infos = {}
                            rop_infos = {}
                            pricing_infos = {}

                            # --- Dynamic Scope Resolution Resolution Tree ---
                            if has_variant:
                                variants_dict = prod_db.get('variants', {})
                                variant_data = variants_dict.get(variant_id) if variants_dict else None
                                
                                if variant_data:
                                    variant_name = variant_data.get('name', '')
                                    
                                    if has_batch:
                                        batches_list = variant_data.get('batch_infos', [])
                                        for b in batches_list:
                                            if (batch_id and b.get('id') == batch_id) or (batch_target_name and b.get('name') == batch_target_name):
                                                batch_infos = b
                                                break
                                        
                                        stock_infos = batch_infos.get('stock_infos') or {}
                                        serialno_infos = batch_infos.get('serialno_infos') or [] if has_serialno else []
                                        stl_infos = batch_infos.get("storage_location_infos") or {}
                                        rop_infos = batch_infos.get("reorder_point_infos") or {}
                                        pricing_infos = batch_infos.get('pricing_infos') or {}
                                    else:
                                        stock_infos = variant_data.get('stock_infos') or {}
                                        serialno_infos = variant_data.get('serialno_infos') or [] if has_serialno else []
                                        stl_infos = variant_data.get("storage_location_infos") or {}
                                        rop_infos = variant_data.get("reorder_point_infos") or {}
                                        pricing_infos = variant_data.get('pricing_infos') or {}
                            else:
                                if has_batch:
                                    batches_list = prod_db.get('batch_infos', [])
                                    for b in batches_list:
                                        if (batch_id and b.get('id') == batch_id) or (batch_target_name and b.get('name') == batch_target_name):
                                            batch_infos = b
                                            break
                                    
                                    stock_infos = batch_infos.get('stock_infos') or {}
                                    serialno_infos = batch_infos.get('serialno_infos') or [] if has_serialno else []
                                    stl_infos = batch_infos.get("storage_location_infos") or {}
                                    rop_infos = batch_infos.get("reorder_point_infos") or {}
                                    pricing_infos = batch_infos.get('pricing_infos') or {}
                                else:
                                    stock_infos = prod_db.get('stock_infos') or {}
                                    serialno_infos = prod_db.get('serialno_infos') or [] if has_serialno else []
                                    stl_infos = prod_db.get("storage_location_infos") or {}
                                    rop_infos = prod_db.get("reorder_point_infos") or {}
                                    pricing_infos = prod_db.get('pricing_infos') or {}

                            # Compute Safe Inventory Delta Strategy metrics
                            stocks = float(itm.get('qty',0))
                            current_db_physical = float(stock_infos.get('physical_stocks', 0))
                            
                            stock_before = current_db_physical + stocks
                            ic(stock_before, current_db_physical, stocks)
                            stock_after = current_db_physical

                            # Update transaction metadata
                            item_infos['total_order_items'] += 1
                            item_infos['total_order_qty'] += stocks
                            
                            orig_val = getattr(origin, "value", origin) if origin else ""
                            is_online_order = "ONLINE" in str(orig_val).upper() if orig_val else False
                            if is_online_order:
                                online_sp = pricing_infos.get('online_sell_price')
                                if online_sp is not None and float(online_sp) > 0:
                                    sell_price_val = float(online_sp)
                                else:
                                    sell_price_val = float(pricing_infos.get('sell_price', 0))
                            else:
                                sell_price_val = float(pricing_infos.get('sell_price', 0))
                            
                            # Check incoming item GST override if product has 0%
                            incoming_gst = itm.get('gst') or itm.get('gst_rate')
                            if incoming_gst and (gst == '0%' or not gst):
                                if isinstance(incoming_gst, (int, float)) and incoming_gst > 0:
                                    gst = f"{incoming_gst}%"
                                elif isinstance(incoming_gst, str) and incoming_gst != '0%':
                                    gst = incoming_gst

                            # Parse GST percentage to raw rate
                            gst_val = gst.replace('%', '').strip() if isinstance(gst, str) else '0'
                            try:
                                gst_rate = float(gst_val) / 100.0
                            except ValueError:
                                gst_rate = 0.0
                            
                            # Selling price is always INCLUSIVE of GST (e.g. 100 SP with 18% GST -> 18.0 GST + 82.0 base)
                            inclusive_unit_price = sell_price_val
                            if gst_rate > 0:
                                gst_amount = round(inclusive_unit_price * gst_rate, 2)
                                taxable_unit = round(inclusive_unit_price - gst_amount, 2)
                            else:
                                taxable_unit = inclusive_unit_price
                                gst_amount = 0.0

                            total_item_gst = gst_amount * stocks
                            
                            # total_order_amount represents the customer payable amount (inclusive of GST)
                            item_infos['total_order_amount'] += (inclusive_unit_price * stocks)
                            item_infos['total_order_gst_amount'] += total_item_gst
                            ic(item_infos)

                            raw_buy_price = float(pricing_infos.get('cost_to_make') or pricing_infos.get('buy_price') or 0.0)
                            is_untracked = prod_db.get('have_tracking') is False
                            try:
                                prod_gst_pct = float(str(product_gst).replace('%', '').strip())
                            except ValueError:
                                prod_gst_pct = 0.0
                            cost_gst_rate = gst_rate if gst_rate > 0 else (prod_gst_pct / 100.0)
                            if is_untracked and raw_buy_price > 0 and cost_gst_rate > 0:
                                buy_price = round(raw_buy_price + round(raw_buy_price * cost_gst_rate, 2), 2)
                            else:
                                buy_price = raw_buy_price
                            item_infos['total_order_cost'] += (buy_price*stocks)

                            order_item_id = generate_uuid()
                            order_items_toadd.append(OrderItems(
                                order_id=order_id,
                                id=order_item_id,
                                product_id=product_id,
                                variant_id=variant_id,
                                batch_id=batch_infos.get('id', batch_id),
                                serialno_infos=itm.get('serialno_infos') or [],
                                gst=gst,
                                buy_price=buy_price,
                                sell_price=inclusive_unit_price,
                                quantity=stocks,
                                entered_qty=itm.get('entered_qty'),
                                entered_unit=itm.get('entered_unit'),
                                additional_infos={"taxable_price": taxable_unit, "gst_amount": gst_amount},
                            ))

                            read_items.append(
                                {
                                    "id": order_item_id,
                                    "product_id": product_id,
                                    "ui_id": db_ui_id,
                                    "name": product_name,
                                    "category_infos":category_infos,
                                    "unit_infos":unit_infos,
                                    "variant_infos": {"variant_id": variant_id, "variant_name": variant_name} if variant_id else None,
                                    "batch_infos": {
                                        "batch_id": batch_id,
                                        "batch_name": batch_infos.get('name', ''),
                                        "exp_date":batch_infos.get("expiry_date"),
                                        "mfg_date":batch_infos.get("manufacturing_date")
                                    } if batch_id else None,
                                    "serialno_infos": itm['serialno_infos'] if itm['serialno_infos'] else None,
                                    "raw_buy_price": raw_buy_price,
                                    "buy_price": buy_price,
                                    "sell_price": inclusive_unit_price,
                                    "taxable_price": taxable_unit,
                                    "gst_amount": gst_amount,
                                    "quantity": stocks,
                                    "entered_qty": itm.get('entered_qty'),
                                    "entered_unit": itm.get('entered_unit'),
                                    "stock_before":stock_before,
                                    "stock_after":stock_after,
                                    "returned_quantity": 0.0,
                                    "total_amount": inclusive_unit_price * stocks,
                                    "status": status,
                                    "gst": gst
                                }
                            )

                calc_taxable = round(sum(i.get("taxable_price", 0.0) * i.get("quantity", 1.0) for i in read_items), 2)
                calc_gst = round(item_infos["total_order_gst_amount"], 2)
                calc_items_subtotal = round(item_infos["total_order_amount"], 2)

                if not isinstance(calculation_infos, dict):
                    calculation_infos = {}

                if "include_gst" not in calculation_infos:
                    calculation_infos["include_gst"] = bool(shop_gst_registered)

                # If caller omitted GST or sent 0 even though products have GST, backfill authoritative breakdown
                if float(calculation_infos.get("gst_amount") or 0) <= 0 and calc_gst > 0:
                    calculation_infos["gst_amount"] = calc_gst
                    calculation_infos["taxable_amount"] = calc_taxable
                    calculation_infos["base_subtotal"] = calc_taxable
                    cgst_val = round(calc_gst / 2.0, 2)
                    calculation_infos["cgst"] = cgst_val
                    calculation_infos["sgst"] = round(calc_gst - cgst_val, 2)
                else:
                    if not calculation_infos.get("gst_amount"):
                        calculation_infos["gst_amount"] = calc_gst
                    if not calculation_infos.get("taxable_amount"):
                        calculation_infos["taxable_amount"] = calc_taxable
                    if not calculation_infos.get("base_subtotal"):
                        calculation_infos["base_subtotal"] = calculation_infos["taxable_amount"]
                    if calculation_infos.get("cgst") is None:
                        cgst_val = round(float(calculation_infos["gst_amount"] or 0.0) / 2.0, 2)
                        calculation_infos["cgst"] = cgst_val
                        calculation_infos["sgst"] = round(float(calculation_infos["gst_amount"] or 0.0) - cgst_val, 2)

                if not calculation_infos.get("subtotal"):
                    calculation_infos["subtotal"] = calc_items_subtotal
                if not calculation_infos.get("grand_total"):
                    calculation_infos["grand_total"] = calc_items_subtotal

                if not calculation_infos.get("items") and read_items:
                    tax_groups_map: Dict[float, Dict[str, float]] = {}
                    calc_items_list = []
                    for ri in read_items:
                        qty_val = float(ri.get("quantity") or 1.0)
                        gst_pct = float(str(ri.get("gst") or "0").replace("%", "").strip() or 0.0)
                        line_tax = round(float(ri.get("gst_amount") or 0.0) * qty_val, 2)
                        line_taxable = round(float(ri.get("taxable_price") or 0.0) * qty_val, 2)
                        line_cgst = round(line_tax / 2.0, 2)
                        line_sgst = round(line_tax - line_cgst, 2)
                        calc_items_list.append({
                            "product_id": ri.get("product_id"),
                            "order_item_id": ri.get("id"),
                            "name": ri.get("name"),
                            "qty": qty_val,
                            "unit": (ri.get("unit_infos") or {}).get("name") or ri.get("entered_unit"),
                            "price": ri.get("sell_price"),
                            "gst_rate": gst_pct,
                            "taxable_value": line_taxable,
                            "gst_amount": line_tax,
                            "cgst": line_cgst,
                            "sgst": line_sgst,
                            "final_inclusive": round(float(ri.get("total_amount") or 0.0), 2),
                        })
                        if gst_pct > 0:
                            grp = tax_groups_map.setdefault(gst_pct, {"gstRate": gst_pct, "taxableValue": 0.0, "cgst": 0.0, "sgst": 0.0, "totalTax": 0.0})
                            grp["taxableValue"] = round(grp["taxableValue"] + line_taxable, 2)
                            grp["cgst"] = round(grp["cgst"] + line_cgst, 2)
                            grp["sgst"] = round(grp["sgst"] + line_sgst, 2)
                            grp["totalTax"] = round(grp["totalTax"] + line_tax, 2)
                    calculation_infos["items"] = calc_items_list
                    if not calculation_infos.get("tax_groups"):
                        calculation_infos["tax_groups"] = list(tax_groups_map.values())

                order_toadd=CreateOrderDbSchema(
                    id=order_id,
                    ui_id=ui_id,
                    shop_id=shop_id,
                    customer_id=customer_id,
                    status=status,
                    origin=origin,
                    calculation_infos=calculation_infos,
                    item_infos=item_infos,
                    payment_infos=payment_infos,
                    charges_infos=charges_infos,
                    date=ord_date
                )

                await repo.create(data=order_toadd)

                if origin == "ONLINE" or origin == OrderOriginEnum.ONLINE.value:
                    await repo.create_online_order(
                        order_id=order_id,
                        user_id=order_payload.get("user_id"),
                        user_address_id=order_payload.get("address_id")
                    )

                await repo.create_bulk_items(datas=order_items_toadd)

                def _parse_amount(v) -> float:
                    if v is None:
                        return 0.0
                    if isinstance(v, (int, float)):
                        return float(v)
                    if isinstance(v, dict):
                        for key in ("amount", "paid", "total", "value"):
                            if key in v and v[key] is not None:
                                try:
                                    return float(v[key])
                                except (ValueError, TypeError):
                                    pass
                        for val in v.values():
                            if isinstance(val, (int, float)):
                                return float(val)
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                pass
                        return 0.0
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return 0.0

                on_credit_amt = 0.0
                total_amount_paid = 0.0
                parsed_payment_infos = {}

                if isinstance(payment_infos, dict):
                    for method, amount in payment_infos.items():
                        num_amount = _parse_amount(amount)
                        parsed_payment_infos[method] = num_amount
                        method_str = str(method).strip().upper()
                        if method_str in ("ON_CREDIT", "ON CREDIT"):
                            on_credit_amt += num_amount
                        elif method_str in ("COD", "CASH ON DELIVERY"):
                            # For COD, payment is collected upon delivery, not upfront
                            pass
                        else:
                            total_amount_paid += num_amount
                elif isinstance(payment_infos, list):
                    for item in payment_infos:
                        if isinstance(item, dict):
                            method = item.get("mode") or item.get("method") or item.get("type") or "CASH"
                            num_amount = _parse_amount(item.get("amount", item.get("value", 0)))
                            parsed_payment_infos[method] = num_amount
                            method_str = str(method).strip().upper()
                            if method_str in ("ON_CREDIT", "ON CREDIT"):
                                on_credit_amt += num_amount
                            elif method_str in ("COD", "CASH ON DELIVERY"):
                                pass
                            else:
                                total_amount_paid += num_amount

                total_ord_cost = float(calculation_infos.get('grand_total') or calculation_infos.get('total') or item_infos['total_order_amount'])
                is_cod = any(str(m).strip().upper() in ("COD", "CASH ON DELIVERY") for m in parsed_payment_infos.keys())

                if is_cod and (origin == "ONLINE" or origin == OrderOriginEnum.ONLINE.value):
                    outstanding_status = "CASH ON DELIVERY"
                    outstanding_amount = total_ord_cost
                else:
                    outstanding_amount = on_credit_amt if on_credit_amt > 0 else max(0.0, total_ord_cost - total_amount_paid)
                    if outstanding_amount == 0:
                        outstanding_status = "COMPLETED"
                    elif total_amount_paid == 0:
                        if (origin == "ONLINE" or origin == OrderOriginEnum.ONLINE.value):
                            outstanding_status = "CASH ON DELIVERY"
                        else:
                            outstanding_status = "NOT-PAID"
                    else:
                        outstanding_status = "PARTIALY-PAID"

                ic(total_amount_paid, total_ord_cost, outstanding_amount, outstanding_status)


                cust_info = datas.get("customers") or order_payload.get("customer") or {}
                cust_name = (
                    (cust_info.get("name") if isinstance(cust_info, dict) else None)
                    or (cust_info.get("customer_name") if isinstance(cust_info, dict) else None)
                    or order_payload.get("customer_name")
                    or order_payload.get("name")
                )

                read_db_order_payload = {
                    "id": order_id,
                    "ui_id": ui_id,
                    "shop_id": shop_id,
                    "customer_id": customer_id,
                    "customer_name": cust_name,
                    "customer": cust_info if isinstance(cust_info, dict) and cust_info else (
                        {"customer_id": customer_id, "name": cust_name} if (customer_id or cust_name) else None
                    ),
                    "status": status,
                    "origin": origin,
                    "delivery_fee": float(
                        calculation_infos.get("delivery_fee")
                        or calculation_infos.get("delivery_charge")
                        or (charges_infos.get("delivery_charge") if isinstance(charges_infos, dict) else 0.0)
                        or (charges_infos.get("delivery_fee") if isinstance(charges_infos, dict) else 0.0)
                        or order_payload.get("delivery_fee")
                        or order_payload.get("delivery_charge")
                        or 0.0
                    ),
                    "total_quantity": float(item_infos.get("total_order_qty") or sum(float(i.get("quantity", 1)) for i in read_items) or 1.0),
                    "calculation_infos": calculation_infos or {},
                    "charges_infos": charges_infos or {},
                    "item_infos": item_infos or {},
                    "payment_infos": payment_infos or [],
                    "payment_status":outstanding_status,
                    "pending_amount":outstanding_amount,
                    "date": ord_date,
                    "items": read_items
                }
                
                if origin == "ONLINE" or origin == OrderOriginEnum.ONLINE.value:
                    read_db_order_payload["online_details"] = {
                        "user_id": order_payload.get("user_id"),
                        "name": order_payload.get("name"),
                        "phone": order_payload.get("phone"),
                        "address_id": order_payload.get("address_id"),
                        "full_address": order_payload.get("full_address"),
                        "latitude": order_payload.get("latitude"),
                        "longitude": order_payload.get("longitude"),
                        "city": order_payload.get("city"),
                        "pincode": order_payload.get("pincode"),
                        "state": order_payload.get("state")
                    }

                ic(item_infos)
                ic(read_items)
                ic(read_db_order_payload)
                await OrderReadDbRepo.replace_order(read_db_order_payload)

                

                if customer_id:
                    non_credit_paid = total_amount_paid
                    pay_infos_list = []
                    for m, amt in parsed_payment_infos.items():
                        if str(m).strip().upper() not in ("ON_CREDIT", "ON CREDIT", "COD", "CASH ON DELIVERY") and amt > 0:
                            pay_infos_list.append({
                                "mode": m,
                                "method": m,
                                "amount": float(amt),
                                "notes": f"Payment for order {ui_id}"
                            })

                    is_credit_billed = bool((on_credit_amt > 0 and non_credit_paid == 0) or (parsed_payment_infos.get("ON_CREDIT", 0) > 0 and non_credit_paid == 0))
                    primary_method = "ON_CREDIT" if is_credit_billed else "CASH"
                    notes_str = f"Initial payment of {non_credit_paid} for order {ui_id}" if non_credit_paid > 0 else f"Order {ui_id} billed (on credit)"

                    if not pay_infos_list and on_credit_amt > 0:
                        pay_infos_list = [{
                            "mode": "ON_CREDIT",
                            "method": "ON_CREDIT",
                            "amount": float(on_credit_amt),
                            "notes": f"Billed on credit for order {ui_id}"
                        }]

                    cust_outst_body = {
                        "shop_id": order_payload.get('shop_id'),
                        "id": customer_id,
                        "outstanding_infos": {"amount": float(on_credit_amt)},
                        "type": "INCREMENT",
                        "cleared_amount": float(non_credit_paid),
                        "paid_amount": float(non_credit_paid),
                        "invoice_outstanding": float(on_credit_amt),
                        "total_amount": float(total_ord_cost),
                        "entity_name": "order",
                        "entity_id": str(ui_id or order_id),
                        "invoice_no": str(ui_id or order_id),
                        "payment_method": primary_method,
                        "payment_infos": pay_infos_list,
                        "notes": notes_str,
                        "is_initial": True
                    }

                    await rabbitmq_msg_obj.publish_event(
                        routing_key="customers.service.routing.key",
                        exchange_name="customers.service.exchange",
                        payload=cust_outst_body,
                        headers={
                            **self.headers.copy(),
                            "body": cust_outst_body,
                            "entity_name": "add_customer_outstanding",
                            "service_name": "CUSTOMERS"
                        }
                    )

                try:
                    analytics_payload = {
                        "shop_id": shop_id,
                        "entity_name": "ORDER",
                        "entity_id": str(order_id),
                        "action": "CREATE"
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

                    try:
                        effective_ui_id = ui_id or f"Order #{order_id[:8]}"
                        order_name = effective_ui_id
                        
                        is_online_order = bool(str(origin).upper() in ("ONLINE", "DIGITAL_STORE")) or origin == OrderOriginEnum.ONLINE.value
                        cust_name = order_payload.get("name") or order_payload.get("customer_name") or "Online Customer"
                        
                        if is_online_order:
                            log_user_info = {
                                "user_name": f"{cust_name} (Online Store)",
                                "user_email": order_payload.get("email") or "",
                                "user_role": "Customer"
                            }
                            log_desc = f"Online Order Placed: {order_name} ({effective_ui_id}) by {cust_name}"
                        else:
                            log_user_info = get_activity_log_user_info(datas.get("user_infos") or datas.get("user_info") or current_user_ctx.get())
                            log_desc = f"Created Order {order_name} ({effective_ui_id})"

                        rabbitmq_msg_obj = RabbitMQMessagingConfig()
                        await rabbitmq_msg_obj.publish_event(
                            routing_key="activity_logs.routing.key",
                            exchange_name="activity_logs.exchange",
                            payload={
                                "shop_id": shop_id,
                                **log_user_info,
                                "service": "Order",
                                "action": "CREATED",
                                "entity_type": "ORDER",
                                "entity_id": str(effective_ui_id),
                                "entity_name": str(order_name),
                                "description": log_desc,
                                "changes": []
                            },
                            headers={}
                        )
                    except Exception as e:
                        ic(f"Failed to publish activity log: {e}")
                except Exception as e:
                    ic(f"Failed to publish analytics event: {e}")

                # Emit Success Notification
                try:
                    from helpers.emit_notification import emit_notification
                    import asyncio
                    executing_user_id = datas.get("executing_user_id")
                    is_online = bool(str(origin).upper() in ("ONLINE", "DIGITAL_STORE")) or origin == OrderOriginEnum.ONLINE.value
                    
                    # 1. Send notification to the shop so it appears in the shop's notifications & live alert
                    shop_notif_title = "New Online Order Received!" if is_online else "New Order Placed"
                    shop_notif_message = (
                        f"New online order '{ui_id}' received from {cust_name} for ₹{float(total_ord_cost):.2f}."
                        if is_online else
                        f"Order '{ui_id}' has been successfully placed (Total: ₹{float(total_ord_cost):.2f})."
                    )
                    
                    asyncio.create_task(emit_notification(
                        title=shop_notif_title,
                        message=shop_notif_message,
                        type="success" if is_online else "info",
                        user_id=shop_id,
                        user_ids=[shop_id],
                        target_type="particular",
                        additional_metadata={
                            "shop_id": shop_id,
                            "order_id": order_id,
                            "ui_id": str(ui_id),
                            "origin": origin,
                            "is_online": is_online,
                            "category": "digital_store" if is_online else "order",
                            "channel": "digital_store" if is_online else "pos",
                            "total_amount": float(total_ord_cost),
                            "customer_name": cust_name,
                            "customer_id": customer_id
                        }
                    ))

                    # 2. Also notify executing customer if distinct from shop
                    if executing_user_id and executing_user_id != shop_id:
                        asyncio.create_task(emit_notification(
                            title="Order Placed Successfully",
                            message=f"Your {'online order' if is_online else 'order'} '{ui_id}' has been placed successfully.",
                            type="info",
                            user_id=executing_user_id,
                            target_type="particular",
                            additional_metadata={
                                "shop_id": shop_id,
                                "order_id": order_id,
                                "ui_id": str(ui_id),
                                "origin": origin,
                                "is_online": is_online,
                                "category": "digital_store" if is_online else "order",
                                "channel": "digital_store" if is_online else "pos"
                            }
                        ))
                except Exception as notification_error:
                    ic(f"Notification error: {notification_error}")

                return {
                    "success": True,
                    "execution": {
                        "step":"SUCCESS",
                        "service":"ORDERS"
                    }
                }
            except Exception as e:
                # Emit Error Notification
                try:
                    from helpers.emit_notification import emit_notification
                    import asyncio
                    asyncio.create_task(emit_notification(
                        title="Order Placement Failed",
                        message=f"Failed to place order: {str(e)}",
                        type="error",
                        user_id=order_payload.get("shop_id")
                    ))
                except Exception as notification_error:
                    ic(f"Notification error: {notification_error}")
                raise e

        if current_step == "SUCCESS":
            ic("Successfully completed the order cycle context workflow.")
            
            return {
                "success": True,
                "execution": None
            }
    
