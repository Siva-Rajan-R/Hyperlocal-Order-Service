from core.utils.user_context import current_user_ctx
from core.data_formats.enums.order_enum import OrderOriginEnum, OrderStatusEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.primary_db.repos.order_repo import OrdersRepo
from schemas.v1.db_schemas.order_schema import CreateReturnDbSchema, CreateReturnItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateReturnSchema, GetOrderByIdSchema
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from infras.primary_db.models.order_model import Returns, ReturnItems
from infras.read_db.repos.order_repo import OrderReadDbRepo
import httpx
from fastapi import HTTPException
from icecream import ic
from ..main import AsyncSession
from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo
from core.utils.id_formatter import format_ui_id
from integrations.utility_service import get_ui_id
from integrations.customer_service import get_customer_info
from messaging.saga_producer import SagaProducer,CreateSagaStateSchema,SagaStatusEnum
from hyperlocal_platform.core.enums.saga_state_enum import SagaStepsValueEnum
from hyperlocal_platform.core.typed_dicts.saga_status_typ_dict import SagaStateExecutionTypDict
from messaging.main import RabbitMQMessagingConfig
from typing import Optional,List


def parse_gst_rate(gst_val) -> float:
    if gst_val is None:
        return 0.0
    if isinstance(gst_val, (int, float)):
        val = float(gst_val)
        return val / 100.0 if val > 1.0 else val
    if isinstance(gst_val, str):
        cleaned = gst_val.replace('%', '').strip()
        try:
            val = float(cleaned)
            return val / 100.0 if val > 1.0 else val
        except ValueError:
            return 0.0
    return 0.0


def resolve_item_gst_rate(
    item_dict: dict,
    calculation_infos: Optional[dict] = None,
    read_db_order: Optional[dict] = None
) -> float:
    calc = calculation_infos or (read_db_order.get('calculation_infos') if read_db_order else {}) or {}
    include_gst = calc.get('include_gst')
    gst_amount = float(calc.get('gst_amount') or 0.0)

    # If the original order did NOT include GST (shop not registered for GST or non-GST order), GST rate is 0.0
    if include_gst is False and gst_amount <= 0:
        return 0.0
    if include_gst is not True and gst_amount <= 0:
        return 0.0

    # 1. Try from calculation_infos['items']
    product_id = item_dict.get('product_id')
    variant_id = item_dict.get('variant_id')

    for ci in (calc.get('items') or []):
        if not isinstance(ci, dict):
            continue
        if ci.get('product_id') == product_id:
            if variant_id and ci.get('variant_id'):
                if ci.get('variant_id') != variant_id:
                    continue
            ci_gst = parse_gst_rate(ci.get('gst'))
            if ci_gst > 0:
                return ci_gst

    # 2. Try directly from item_dict['gst']
    item_gst = item_dict.get('gst')
    gst_rate = parse_gst_rate(item_gst)
    if gst_rate > 0:
        return gst_rate

    # 3. Try from read_db_order items
    if read_db_order:
        item_id = item_dict.get('id')
        for rd_itm in (read_db_order.get('items') or []):
            if rd_itm.get('id') == item_id:
                rd_gst = parse_gst_rate(rd_itm.get('gst'))
                if rd_gst > 0:
                    return rd_gst
                break

    # 4. Try from overall order calculation_infos (gst_amount / subtotal)
    subtotal = float(calc.get('subtotal') or 0.0)
    if gst_amount > 0 and subtotal > 0:
        return gst_amount / subtotal

    return 0.0


class ReturnService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_return(self, data: CreateReturnSchema, executing_user_id: Optional[str] = None, custom_user_info: Optional[dict] = None) -> bool | None:
        try:
            rabbitmq_connection=RabbitMQMessagingConfig()
            return_id = generate_uuid()
            order_data = await OrdersRepo(session=self.session).getby_id(
                data=GetOrderByIdSchema(id=data.order_id, shop_id=data.shop_id)
            )
            ic(order_data)
            if not order_data:
                raise HTTPException(status_code=404, detail="Order not found")
            
            ui_id_res = await get_ui_id(shop_id=order_data.get('shop_id'))
            ui_id=f"{ui_id_res.get('prefix')}-{ui_id_res.get('current_number')}"

            order_id=order_data['id']
            additional_infos=order_data['additional_infos']
            calculation_infos=order_data['calculation_infos']
            customer_id=order_data['customer_id']
            date=order_data['date']
            origin=order_data['origin']
            payment_infos=data.payment_infos
            status=order_data['status']
            shop_id=data.shop_id

            items_map = {itm["id"]: itm for itm in (order_data.get("items") or [])}

            # Fetch MongoDB order to get denormalized fields (unit_infos, name, ui_id, etc.)
            read_db_order = await OrderReadDbRepo.get_by_id(
                shop_id=data.shop_id,
                order_id=data.order_id,
            )
            if read_db_order:
                for rd_itm in (read_db_order.get("items") or []):
                    rd_id = rd_itm.get("id")
                    if rd_id and rd_id in items_map:
                        # Merge denormalized product fields from MongoDB into items_map
                        for field in ("unit_infos", "category_infos", "name", "ui_id", "variant_infos", "gst"):
                            if field in rd_itm and rd_itm[field] is not None:
                                if field != "gst" or (not items_map[rd_id].get("gst") or items_map[rd_id].get("gst") == "0%"):
                                    items_map[rd_id][field] = rd_itm[field]

            # ── User Context Resolution ──────────────────────────────────────────
            u_ctx = custom_user_info or current_user_ctx.get() or {}
            if not isinstance(u_ctx, dict):
                u_ctx = {}
            u_name = u_ctx.get("name") or u_ctx.get("user_name") or ""
            u_email = u_ctx.get("email") or u_ctx.get("user_email") or ""
            u_id = u_ctx.get("user_id") or u_ctx.get("id") or executing_user_id
            u_role = u_ctx.get("role") or u_ctx.get("user_role") or "User"

            if (not u_name and not u_email):
                orig_user = (read_db_order.get("user_infos") or read_db_order.get("user_info") if read_db_order else None) or order_data.get("user_infos") or order_data.get("user_info") or {}
                if isinstance(orig_user, dict) and (orig_user.get("name") or orig_user.get("user_name") or orig_user.get("email") or orig_user.get("user_email")):
                    u_name = orig_user.get("name") or orig_user.get("user_name") or ""
                    u_email = orig_user.get("email") or orig_user.get("user_email") or ""
                    u_id = u_id or orig_user.get("user_id") or orig_user.get("id")
                    u_role = orig_user.get("role") or orig_user.get("user_role") or u_role
                elif read_db_order and read_db_order.get("added_by") and read_db_order.get("added_by") != "System":
                    u_name = read_db_order.get("added_by")

            added_by_str = u_name or u_email or "System"
            if u_name and u_email and f"- {u_email}" not in added_by_str:
                added_by_str = f"{u_name} - {u_email}"
            elif u_email and not u_name:
                added_by_str = u_email
            elif u_name:
                added_by_str = u_name

            resolved_user_ctx = {
                "user_id": u_id,
                "id": u_id,
                "name": u_name,
                "user_name": u_name,
                "email": u_email,
                "user_email": u_email,
                "role": u_role,
                "user_role": u_role
            }
            current_user_ctx.set(resolved_user_ctx)
            return_toadd=None
            return_items_toadd=[]
            products_toupdate=[]
            customer_outst_toadd={}
            oncredit_amount=0
            total_refund_qty=0
            total_refund_amount=0
            for itm in data.items:
                itm=itm.model_dump()
                ic(itm)
                inc_item_id=itm['order_item_id']
                ic(inc_item_id)
                if inc_item_id not in items_map:
                    ic("Invalid order item id")
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid Order Item"
                    )
                ic(items_map[inc_item_id])
                original_qty = float(items_map[inc_item_id].get('quantity') or 0.0)
                returned_qty = float(items_map[inc_item_id].get('returned_quantity') or 0.0)
                exchanged_qty = float(items_map[inc_item_id].get('exchanged_quantity') or 0.0)
                already_consumed = returned_qty + exchanged_qty

                unit_infos = items_map[inc_item_id].get("unit_infos") or {}
                base_unit_name = unit_infos.get("name", "")
                sub_units = unit_infos.get("sub_units", []) or []

                conversion_factor = 1.0
                entered_unit = itm.get("unit")
                if entered_unit:
                    if entered_unit.lower() == base_unit_name.lower():
                        conversion_factor = 1.0
                    else:
                        matched_sub = next((su for su in sub_units if su and su.get("name", "").lower() == entered_unit.lower()), None)
                        if not matched_sub:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Invalid unit '{entered_unit}'. Configured base unit: '{base_unit_name}', sub units: {[su.get('name') for su in sub_units if su]}"
                            )
                        conversion_factor = float(matched_sub.get("factor", 1.0))

                inc_quantity = itm["quantity"] * conversion_factor

                ic(original_qty, returned_qty, exchanged_qty, already_consumed)

                if already_consumed >= original_qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"All qty for this item has already been returned or exchanged (original: {original_qty}, returned: {returned_qty}, exchanged: {exchanged_qty})"
                    )

                delta = original_qty - already_consumed - inc_quantity
                ic(delta)
                if delta < 0:
                    ic("Invalid order qty")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Return qty ({inc_quantity}) exceeds available qty. Original: {original_qty}, already returned: {returned_qty}, already exchanged: {exchanged_qty}, available: {original_qty - already_consumed}"
                    )
                
                raw_sell_price = float(items_map[inc_item_id]['sell_price'] or 0.0)
                gst_rate = resolve_item_gst_rate(
                    item_dict=items_map[inc_item_id],
                    calculation_infos=calculation_infos,
                    read_db_order=read_db_order
                )
                
                # OrderItems.sell_price is stored as net/raw amount (excl GST).
                # Customer paid inclusive of GST = raw_sell_price * (1 + gst_rate).
                full_sell_price_with_gst = round(raw_sell_price * (1.0 + gst_rate), 2)
                total_return_qty_amount = round(inc_quantity * full_sell_price_with_gst, 2)
                total_refund_amount = round(total_refund_amount + total_return_qty_amount, 2)
                total_refund_qty += inc_quantity

            total_returned_paid_amount = 0
            for key, val in data.payment_infos.items():
                amount = val.get("amount", 0) if isinstance(val, dict) else val
                total_returned_paid_amount += amount
                if key == "ON_CREDIT":
                    oncredit_amount += amount

            total_returned_paid_amount = round(total_returned_paid_amount, 2)
            total_refund_amount = round(total_refund_amount, 2)

            if abs(total_refund_amount - total_returned_paid_amount) > 0.01:
                ic("Return Amount should be properly entered", total_refund_amount, total_returned_paid_amount)
                raise HTTPException(
                    status_code=400,
                    detail=f"Entered refund amount ({total_returned_paid_amount}) does not match required return total ({total_refund_amount})."
                )

            for itm in data.items:
                itm = itm.model_dump()
                inc_item_id = itm['order_item_id']
                unit_infos = items_map[inc_item_id].get("unit_infos") or {}
                base_unit_name = unit_infos.get("name", "")
                sub_units = unit_infos.get("sub_units", []) or []
                conversion_factor = 1.0
                entered_unit = itm.get("unit")
                if entered_unit:
                    if entered_unit.lower() == base_unit_name.lower():
                        conversion_factor = 1.0
                    else:
                        matched_sub = next((su for su in sub_units if su and su.get("name", "").lower() == entered_unit.lower()), None)
                        if matched_sub:
                            conversion_factor = float(matched_sub.get("factor", 1.0))
                inc_quantity = itm["quantity"] * conversion_factor
                raw_sell_price = float(items_map[inc_item_id]['sell_price'] or 0.0)
                gst_rate = resolve_item_gst_rate(
                    item_dict=items_map[inc_item_id],
                    calculation_infos=calculation_infos,
                    read_db_order=read_db_order
                )
                full_sell_price_with_gst = round(raw_sell_price * (1.0 + gst_rate), 2)
                total_return_qty_amount = round(inc_quantity * full_sell_price_with_gst, 2)
                founded_serialno=[]
                existing_serial_ids = [s.get('id') for s in (items_map[inc_item_id].get('serialno_infos') or [])]
                
                # Extract already returned/exchanged serial numbers from MongoDB read DB order
                already_returned_or_exchanged_sns = set()
                if read_db_order:
                    # Collect serial numbers from past returns
                    for ret in (read_db_order.get("returns") or []):
                        for r_item in (ret.get("items") or []):
                            if r_item.get("order_item_id") == inc_item_id:
                                for sn in (r_item.get("serialno_infos") or []):
                                    if sn.get("id"):
                                        already_returned_or_exchanged_sns.add(sn.get("id"))
                    # Collect serial numbers from past exchanges
                    for exc in (read_db_order.get("exchanges") or []):
                        for e_item in (exc.get("items") or []):
                            if e_item.get("order_item_id") == inc_item_id:
                                for sn in (e_item.get("serialno_infos") or []):
                                    if sn.get("id"):
                                        already_returned_or_exchanged_sns.add(sn.get("id"))

                for serialno in (itm.get("serialno_infos") or []):
                    if serialno['id'] not in existing_serial_ids:
                        ic("Serialno not found")
                        raise HTTPException(
                            status_code=400,
                            detail=f"Serial number '{serialno['id']}' not found in the original sold item."
                        )
                    
                    if serialno['id'] in already_returned_or_exchanged_sns:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Serial number '{serialno['id']}' has already been returned or exchanged."
                        )
                    
                    matched_sn = next((s for s in (items_map[inc_item_id].get('serialno_infos') or []) if s.get('id') == serialno['id']), None)
                    if matched_sn:
                        founded_serialno.append(matched_sn)

                is_online_order = str(origin).upper() == "ONLINE"
                return_entity_name = "ONLINE_SALES_RETURN" if is_online_order else "OFFLINE_SALES_RETURN"
                order_ui_id = order_data.get('ui_id') or (read_db_order.get('ui_id') if read_db_order else None) or order_data.get('id')

                products_toupdate.append(
                    {
                        "shop_id": shop_id,
                        "product_id": items_map[inc_item_id]['product_id'],
                        "variant_id": items_map[inc_item_id]['variant_id'],
                        "batch_infos": {"id": items_map[inc_item_id]['batch_id']} if items_map[inc_item_id]['batch_id'] else None,
                        "serialno_infos": founded_serialno,
                        "stocks": inc_quantity,
                        "entity_name": return_entity_name,
                        "type": "INCREMENT",
                        "create_stock_mov_adj": True,
                        "ui_id": order_ui_id or ui_id,
                        "order_ui_id": order_ui_id,
                        "sale_ui_id": order_ui_id,
                        "return_ui_id": ui_id,
                        "entity_id": order_ui_id or ui_id,
                        "order_id": order_id,
                        "added_by": added_by_str,
                        "user_id": u_id,
                        "user_name": u_name,
                        "user_email": u_email,
                        "user_role": u_role,
                        "user_info": resolved_user_ctx,
                        "user_infos": resolved_user_ctx
                    }
                )

                ic(total_refund_amount,total_refund_qty,total_return_qty_amount,total_returned_paid_amount)
                return_items_toadd.append(
                    {
                        'id':generate_uuid(),
                        'return_id':return_id,
                        'order_item_id':itm['order_item_id'],
                        'product_id':items_map[inc_item_id]['product_id'],
                        'quantity':inc_quantity,
                        'entered_qty': itm['quantity'],
                        'entered_unit': itm.get('unit') or base_unit_name,
                        'refund_amount':total_return_qty_amount,
                        'reason':itm['reason'],
                        'serialno_infos': founded_serialno
                    }
                )


            return_toadd={
                "id":return_id,
                "ui_id":ui_id,
                "order_id":order_id,
                "customer_id":customer_id,
                "shop_id":shop_id,
                "status":"COMPLETED",
                "payment_infos":payment_infos,
                "total_refund_qty":total_refund_qty,
                "total_refund_amount":total_refund_amount

            }


            if oncredit_amount:
                if not customer_id:
                    ic("Cant able to add the onccredit payment for the walkincustomers")
                    raise HTTPException(
                        status_code=400,
                        detail="Cant able to add the onccredit payment for the walkincustomers"
                    )
                customer_infos=await get_customer_info(shop_id=data.shop_id,customer_id=customer_id)
                ic(customer_infos)
                outst_infos = (customer_infos or {}).get('outstanding_infos') or {}
                customer_existing_outst = float(outst_infos.get('amount', 0.0))
                if customer_existing_outst <= 0:
                    ic("There is no outstanding for the customer please provide the amount on upi,cash or any other payment method")
                    raise HTTPException(
                        status_code=400,
                        detail="There is no outstanding for the customer please provide the amount on upi,cash or any other payment method"
                    )
                if oncredit_amount > customer_existing_outst:
                    ic("The customer outstanding delta is greater")
                    raise HTTPException(
                        status_code=400,
                        detail="The customer outstanding delta is greater"
                    )
                customer_outst_toadd={
                    "customer_id":customer_id,
                    "shop_id":shop_id,
                    "amount":oncredit_amount
                }

                

            ic(return_toadd,return_items_toadd)

            return_data={"order_return":{"return_toadd":return_toadd,"return_items_toadd":return_items_toadd,"customer_toadd":customer_outst_toadd}}
            ic(return_data)

            saga_id:str=generate_uuid()
            steps={
                "PRODUCT_VERIFY_UPDATE":SagaStepsValueEnum.PENDING,
                # "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
            }

            saga_data=return_data
            saga_data["executing_user_id"] = u_id or executing_user_id
            saga_data["added_by"] = added_by_str
            saga_data["user_id"] = u_id
            saga_data["user_name"] = u_name
            saga_data["user_email"] = u_email
            saga_data["user_role"] = u_role
            saga_data["user_infos"] = resolved_user_ctx
            saga_data["user_info"] = resolved_user_ctx
            if "order_return" in saga_data and isinstance(saga_data["order_return"], dict):
                saga_data["order_return"]["added_by"] = added_by_str
                saga_data["order_return"]["user_id"] = u_id
                saga_data["order_return"]["user_name"] = u_name
                saga_data["order_return"]["user_email"] = u_email
                saga_data["order_return"]["user_role"] = u_role
                saga_data["order_return"]["user_infos"] = resolved_user_ctx
                saga_data["order_return"]["user_info"] = resolved_user_ctx
            await SagaProducer.emit(
                session=self.session,
                saga_payload=CreateSagaStateSchema(
                    id=saga_id,
                    status=SagaStatusEnum.IN_PROGRESS,
                    type="OREDER_RETURNED",
                    steps=steps,
                    execution=SagaStateExecutionTypDict(
                        step="PRODUCT_VERIFY_UPDATE",
                        service="PRODUCTS"
                    ),
                    data=saga_data
                ),
                routing_key="products.service.routing.key",
                exchange_name="products.service.exchange",
                headers={
                    "reply_key":"orders.producer.routing.key",
                    "reply_exchange":"orders.producer.exchange",
                    "reply_entity_name":"create_return",
                    "reply_service_name":"ORDERS_RETURN",
                    "service_name":"PRODUCTS",
                    "entity_name":"update_bulk_prodinv",
                    "body":products_toupdate

                }
            )


            if customer_outst_toadd:
                await rabbitmq_connection.publish_event(
                    routing_key="customers.service.routing.key",
                    exchange_name="customers.service.exchange",
                    payload=customer_outst_toadd,
                    headers={
                        "saga_id":generate_uuid(),
                        "reply_entity_name":"None",
                        "reply_exchange":"None",
                        "reply_key":"None",
                        "service_name":"CUSTOMERS",
                        "entity_name":"clear_customer_outstanding",
                        "service":"CUSTOMERS",
                        "body":{
                            "customer_id":customer_outst_toadd['customer_id'],
                            "shop_id":customer_outst_toadd['shop_id'],
                            "payment_infos":[{"method":'CASH',"amount":customer_outst_toadd['amount']}]
                        }
                    }
                )

            return True
        except Exception as e:
            # Emit Error Notification
            try:
                from helpers.emit_notification import emit_notification
                import asyncio
                asyncio.create_task(emit_notification(
                    title="Order Return Process Failed",
                    message=f"Failed to initiate order return process: {str(e.detail) if hasattr(e, 'detail') else str(e)}",
                    type="error",
                    user_id=executing_user_id or data.shop_id
                ))
            except Exception as notification_error:
                ic(f"Notification error: {notification_error}")
            raise e

        


            



            

        

        
