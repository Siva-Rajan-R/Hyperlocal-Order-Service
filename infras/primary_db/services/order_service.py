from core.utils.user_context import current_user_ctx
from core.utils.user_context import get_activity_log_user_info
from ..repos.order_repo import OrdersRepo,OrderItems
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum,OrderReturnTypeEnum
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.read_db.repos.order_repo import OrderReadDbRepo
import asyncpg
from fastapi.exceptions import HTTPException
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,OrderItemsSchema,GetOrderByCustomerIdSchema,UpdateOrderStatusSchema,GetBulkOrdersSchema
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from hyperlocal_platform.core.utils.routingkey_builder import RoutingkeyActions,RoutingkeyState,RoutingkeyVersions,generate_routingkey
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from icecream import ic
from typing import Optional,List
import httpx
from ..main import AsyncSession
from infras.caching.models.cart_model import OrderCartCacheModel
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict,SuccessResponseTypDict,BaseResponseTypDict
from integrations.stock_reservation import commit_reservation
from integrations.utility_service import get_ui_id
from hyperlocal_platform.core.enums.saga_state_enum import SagaStatusEnum,SagaStepsValueEnum
from messaging.saga_producer import SagaProducer,CreateSagaStateSchema,SagaStatusEnum,SagaStateExecutionTypDict





class OrdersService:
    def __init__(self,session:AsyncSession):
         self.session=session
    async def create(self, data: CreateOrderSchema, executing_user_id: Optional[str] = None):
        cart = OrderCartCacheModel(data.session_id)
        cart_data = await cart.get_cart()
        ic(cart_data)
        if not cart_data:
            # Self-heal: If session expired or empty, attempt auto-initialization from calculation_infos items
            calc_items = data.calculation_infos.get("items", []) if isinstance(data.calculation_infos, dict) else []
            if calc_items:
                from schemas.v1.request_scheams.cart_schema import CartReserveRequest
                from integrations.stock_reservation import create_reservation
                ic("Cart session missing or expired in Redis; auto-populating from calculation_infos items")
                for ci in calc_items:
                    prod_id = ci.get("product_id") or ci.get("id")
                    if prod_id:
                        try:
                            reserve_req = CartReserveRequest(
                                session_id=data.session_id,
                                shop_id=data.shop_id,
                                product_id=prod_id,
                                qty=float(ci.get("qty", 1)),
                                unit=ci.get("unit"),
                                variant_id=ci.get("variant_id"),
                                batch_id=ci.get("batch_id")
                            )
                            await create_reservation(reserve_req)
                        except Exception as e:
                            ic(f"Auto-reservation of item {prod_id} failed: {e}")
                cart_data = await cart.get_cart()

        if not cart_data:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Creating order",
                    description="Cart session is invalid, expired, or empty",
                    success=False
                )
            )
        ui_id_val = None
        try:
            ui_id_res = await get_ui_id(shop_id=data.shop_id)
            if isinstance(ui_id_res, dict) and "prefix" in ui_id_res:
                ui_id_val = f"{ui_id_res.get('prefix')}-{ui_id_res.get('current_number')}"
        except Exception as e:
            ic(f"Failed to fetch UI ID for order: {e}")

        if not ui_id_val:
            import datetime
            ui_id_val = f"ORD-{int(datetime.datetime.utcnow().timestamp())}"

        reservation_complete_res=await commit_reservation(session_id=data.session_id, entity_id=ui_id_val, origin=data.origin, order_data=data)
        if not reservation_complete_res:
            ic("Cant able to reserve the stocks please try again")
            return False
    
        await cart.delete_cart()
            

        saga_id:str=generate_uuid()
        product_ids=[]
        for item in cart_data:
            ic(item)
            product_ids.append(item['product_id'])
        ic(cart_data)
        order_data={**data.model_dump(mode="json"),"items":cart_data, "ui_id": ui_id_val}

        saga_data={"orders":order_data, "executing_user_id": executing_user_id, "user_infos": current_user_ctx.get(), "user_info": current_user_ctx.get()}
        ic(product_ids)

        if data.customer_id:
            await SagaProducer.emit(
                session=self.session,
                saga_payload=CreateSagaStateSchema(
                    id=saga_id,
                    status=SagaStatusEnum.IN_PROGRESS,
                    type="ORDER_CREATED",
                    steps={
                        "VERIFY_CUSTOMER":SagaStepsValueEnum.PENDING,
                        "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
                    },
                    execution=SagaStateExecutionTypDict(
                        step="VERIFY_CUSTOMER",
                        service="CUSTOMERS"
                    ),
                    data=saga_data
                ),
                routing_key="customers.service.routing.key",
                exchange_name="customers.service.exchange",
                headers={
                    "reply_key":"orders.producer.routing.key",
                    "reply_exchange":"orders.producer.exchange",
                    "reply_entity_name":"create_order",
                    "reply_service_name":"ORDERS",
                    "service_name":"CUSTOMERS",
                    "entity_name":"get_customer_by_id",
                    "body":{
                        "shop_id":data.shop_id,
                        "id":data.customer_id
                    }
                }
            )
        else:
                       
            if product_ids:
                await SagaProducer.emit(
                    session=self.session,
                    saga_payload=CreateSagaStateSchema(
                        id=saga_id,
                        status=SagaStatusEnum.IN_PROGRESS,
                        type="ORDER_CREATED",
                        steps={
                            "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
                        },
                        execution=SagaStateExecutionTypDict(
                            step="FETCHING_PRODUCTS",
                            service="PRODUCTS"
                        ),
                        data=saga_data
                    ),
                    routing_key="products.service.routing.key",
                    exchange_name="products.service.exchange",
                    headers={
                        "reply_key":"orders.producer.routing.key",
                        "reply_exchange":"orders.producer.exchange",
                        "reply_entity_name":"create_order",
                        "reply_service_name":"ORDERS",
                        "service_name":"PRODUCTS",
                        "entity_name":"get_bulk_product_by_id",
                        "body":{
                            "shop_id":data.shop_id,
                            "id":list(set(product_ids))
                        }
                    }
                )


        return {
            "id": ui_id_val,
            "ui_id": ui_id_val,
            "order_id": ui_id_val,
            "session_id": data.session_id,
            "saga_id": saga_id
        }
    

    async def _consume_and_assign_accept_serials(self, data: UpdateOrderStatusSchema, order_items: list):
        """Validate and consume serial numbers via Inventory Service when accepting an order."""
        import os

        inv_base_url = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8004")
        assignments = data.serial_assignments or []

        def _norm_serials(raw_list: list) -> list[str]:
            out: list[str] = []
            for entry in raw_list or []:
                if isinstance(entry, dict):
                    val = entry.get("id") or entry.get("name") or entry.get("serial") or entry.get("serial_no")
                else:
                    val = entry
                if val is not None and str(val).strip():
                    out.append(str(val).strip())
            return out

        def _extract_item(itm) -> dict:
            if isinstance(itm, dict):
                return itm
            return dict(itm._mapping) if hasattr(itm, "_mapping") else dict(itm)

        normalized_items = [_extract_item(i) for i in (order_items or [])]

        # Match incoming assignments to specific order_items
        by_item_id: dict[str, list[str]] = {}
        by_key: dict[tuple, list[str]] = {}
        for a in assignments:
            serial_vals = _norm_serials(a.serialno_infos)
            if not serial_vals:
                continue
            if a.order_item_id:
                by_item_id[str(a.order_item_id)] = serial_vals
            else:
                key = (str(a.product_id), str(a.variant_id or ""), str(a.batch_id or ""))
                by_key[key] = serial_vals

        items_missing_serials = [
            itm for itm in normalized_items
            if not (itm.get("serialno_infos") and len(itm.get("serialno_infos") or []) > 0)
        ]

        # Check Inventory Service to enforce serial selection for any serial-tracked product
        serial_product_ids: set[str] = set()
        if items_missing_serials:
            prod_ids = list({str(i.get("product_id")) for i in items_missing_serials if i.get("product_id")})
            if prod_ids:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        inv_resp = await client.post(
                            f"{inv_base_url}/inventories/by/ids",
                            json={"shop_id": data.shop_id, "id": prod_ids, "include_serialno": False},
                        )
                        if inv_resp.status_code == 200:
                            inv_payload = inv_resp.json()
                            inv_list = inv_payload.get("data") if isinstance(inv_payload, dict) else inv_payload
                            for p in (inv_list or []):
                                if isinstance(p, dict) and (p.get("type_infos") or {}).get("has_serialno"):
                                    if p.get("id"):
                                        serial_product_ids.add(str(p.get("id")))
                except Exception as exc:
                    ic(f"Could not verify product serial tracking before accept: {exc}")

        consume_payload_items = []
        matched_item_ids: list[str] = []

        for itm in normalized_items:
            existing_serials = itm.get("serialno_infos") or []
            if existing_serials:
                continue

            item_id = str(itm.get("id") or "")
            prod_id = str(itm.get("product_id") or "")
            var_id = itm.get("variant_id")
            batch_id = itm.get("batch_id")
            qty = int(round(float(itm.get("quantity") or 0)))

            chosen = by_item_id.get(item_id)
            if chosen is None:
                chosen = by_key.get((prod_id, str(var_id or ""), str(batch_id or "")))

            if prod_id in serial_product_ids or chosen is not None:
                if not chosen or len(chosen) != qty:
                    item_name = itm.get("name") or prod_id
                    raise HTTPException(
                        status_code=400,
                        detail=f"Please select {qty} serial number(s) for '{item_name}' before accepting the order.",
                    )
                consume_payload_items.append({
                    "order_item_id": item_id or None,
                    "product_id": prod_id,
                    "variant_id": var_id,
                    "batch_id": batch_id,
                    "serials": chosen,
                })
                matched_item_ids.append(item_id)

        if not consume_payload_items:
            return

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{inv_base_url}/inventories/serials/consume",
                    json={"shop_id": data.shop_id, "items": consume_payload_items},
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to contact inventory service to assign serials: {exc}")

        if resp.status_code != 200:
            err_msg = "Failed to assign serial numbers"
            try:
                err_body = resp.json()
                detail = err_body.get("detail", err_body)
                if isinstance(detail, dict):
                    err_msg = detail.get("msg") or detail.get("description") or err_msg
                elif isinstance(detail, str):
                    err_msg = detail
            except Exception:
                pass
            raise HTTPException(status_code=resp.status_code if 400 <= resp.status_code < 500 else 400, detail=err_msg)

        resp_data = resp.json()
        assigned_items = resp_data.get("assigned_items") or []
        order_repo = OrdersRepo(session=self.session)
        for idx, assigned in enumerate(assigned_items):
            target_item_id = assigned.get("order_item_id") or (matched_item_ids[idx] if idx < len(matched_item_ids) else None)
            if target_item_id:
                await order_repo.assign_order_item_serials(
                    order_id=data.id,
                    item_id=str(target_item_id),
                    serialno_infos=assigned.get("serialno_infos") or [],
                )


    async def update(self, data: UpdateOrderStatusSchema, executing_user_id: Optional[str] = None, executing_user_info: Optional[dict] = None, request_origin: str = ""):
        # 1. Resolve executing user information
        u_info = executing_user_info or {}
        if not u_info:
            try:
                from core.utils.user_context import current_user_ctx
                u_info = current_user_ctx.get() or {}
            except Exception:
                u_info = {}
        
        user_name = u_info.get("name") or u_info.get("user_name") or ""
        user_email = u_info.get("email") or ""
        u_id = executing_user_id or u_info.get("user_id") or u_info.get("id") or ""
        u_role = u_info.get("role") or ""

        if user_name and user_email and f"- {user_email}" not in user_name:
            user_display = f"{user_name} - {user_email}"
        elif user_email:
            user_display = user_email
        elif user_name:
            user_display = user_name
        else:
            user_display = "Staff"

        # 2. Fetch existing order data
        old_order_row = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
        old_order_dict = dict(old_order_row._mapping) if old_order_row and hasattr(old_order_row, "_mapping") else (dict(old_order_row) if old_order_row else {})
        old_status = str(old_order_dict.get("status") or "").upper()
        new_status = (data.status.value if hasattr(data.status, "value") else str(data.status)).upper() if data.status else None

        # 3. Update status history and tracking in additional_infos
        incoming_add = data.additional_infos if isinstance(data.additional_infos, dict) else {}
        existing_add = old_order_dict.get("additional_infos") or {}
        if not isinstance(existing_add, dict):
            existing_add = {}
        else:
            existing_add = dict(existing_add)

        for k, v in incoming_add.items():
            if v is not None:
                existing_add[k] = v

        cancelled_source = None
        cancelled_actor = None
        cancelled_via = None
        if new_status in ("CANCELED", "CANCELLED", "REJECTED"):
            raw_src = str(
                incoming_add.get("cancelled_by_source")
                or incoming_add.get("canceled_by_source")
                or request_origin
                or ""
            ).strip().upper()
            raw_label = str(
                incoming_add.get("cancelled_by")
                or incoming_add.get("cancelled_by_label")
                or ""
            ).strip().upper()
            role_upper = str(u_role or "").strip().upper()

            is_customer_cancel = (
                "DIGITAL" in raw_src
                or "CUSTOMER" in raw_src
                or "MOBILE" in raw_src
                or raw_label == "CUSTOMER"
                or ("DIGITALSTORE" in raw_label)
                or (not raw_src and role_upper in ("USER", "CUSTOMER"))
            )
            if is_customer_cancel:
                cancelled_source = "DIGITAL_STORE"
                cancelled_actor = "Customer"
                cancelled_via = "Cancelled by Customer"
            else:
                cancelled_source = "INVENTQ"
                cancelled_actor = "InventQ"
                cancelled_via = "Cancelled manually by InventQ"

        status_history = existing_add.get("status_history") or []
        if not isinstance(status_history, list):
            status_history = []
        
        from datetime import datetime, timezone
        history_entry = {
            "from_status": old_status,
            "to_status": new_status,
            "updated_by": user_display,
            "user_id": u_id,
            "user_email": user_email,
            "user_name": user_name,
            "user_role": u_role,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if cancelled_source:
            history_entry["cancelled_by_source"] = cancelled_source
            history_entry["cancelled_by"] = cancelled_actor
            history_entry["cancelled_by_label"] = cancelled_via
        status_history.append(history_entry)
        existing_add["status_history"] = status_history
        existing_add["status_updated_by"] = user_display
        if new_status in ("ACCEPTED", "ACCEPT"):
            existing_add["accepted_by"] = user_display
        elif new_status in ("CANCELED", "CANCELLED", "REJECTED"):
            existing_add["canceled_by"] = user_display
            existing_add["rejected_by"] = user_display
            existing_add["cancelled_by"] = cancelled_actor
            existing_add["cancelled_by_source"] = cancelled_source
            existing_add["cancelled_by_label"] = cancelled_via
            existing_add["cancelled_by_user"] = user_display
        elif new_status in ("OUT_FOR_DELIVERY", "OUT-FOR-DELIVERY", "OUT FOR DELIVERY"):
            existing_add["dispatched_by"] = user_display
        elif new_status in ("DELIVERED",):
            existing_add["delivered_by"] = user_display

        data.additional_infos = existing_add

        if new_status in ("ACCEPTED", "ACCEPT") and old_status not in ("ACCEPTED", "ACCEPT"):
            await self._consume_and_assign_accept_serials(
                data=data,
                order_items=old_order_dict.get("items") or [],
            )

        from schemas.v1.db_schemas.order_schema import UpdateOrderDbSchema
        repo_data = UpdateOrderDbSchema(
            **data.model_dump(
                mode='json',
                exclude_unset=True,
                exclude_none=True,
                exclude={'serial_assignments'},
            )
        )
        res = await OrdersRepo(session=self.session).update(data=repo_data)
        if res:
            await self.session.commit()
            
            # --- Delivery Code Logic ---
            from infras.read_db.repos.delivery_code_repo import DeliveryCodeRepo
            if new_status in ("OUT_FOR_DELIVERY", "OUT-FOR-DELIVERY", "OUT FOR DELIVERY"):
                await DeliveryCodeRepo.generate_and_store_code(shop_id=data.shop_id, order_id=data.id)
            elif new_status in ("CANCELED", "CANCELLED", "DELIVERED", "REJECTED"):
                await DeliveryCodeRepo.delete_code(shop_id=data.shop_id, order_id=data.id)
            # ---------------------------

            # --- Restore Stock on Order Cancel / Reject ---
            if new_status in ("CANCELED", "CANCELLED", "REJECTED") and old_status not in ("CANCELED", "CANCELLED", "REJECTED"):
                orig_val = old_order_dict.get("origin", "")
                is_online = "ONLINE" in str(getattr(orig_val, "value", orig_val)).upper()
                order_ui_id = old_order_dict.get("ui_id") or data.id
                items = old_order_dict.get("items") or []

                if not items:
                    try:
                        read_order = await OrderReadDbRepo.get_by_id(shop_id=data.shop_id, order_id=data.id)
                        if read_order:
                            items = read_order.get("items") or []
                    except Exception as e:
                        ic(f"Could not load items from read_db for stock restoration: {e}")

                products_toupdate = []
                for itm in items:
                    itm_d = dict(itm) if isinstance(itm, dict) else (dict(itm._mapping) if hasattr(itm, "_mapping") else itm.__dict__)
                    prod_id = itm_d.get("product_id")
                    qty = float(itm_d.get("qty") or itm_d.get("quantity") or 0)
                    if not prod_id or qty <= 0:
                        continue
                    
                    b_id = itm_d.get("batch_id")
                    v_id = itm_d.get("variant_id")
                    
                    note_action = "online sale" if is_online else "sales"
                    products_toupdate.append({
                        "shop_id": data.shop_id,
                        "product_id": prod_id,
                        "variant_id": v_id,
                        "batch_infos": {"id": b_id} if b_id else None,
                        "serialno_infos": itm_d.get("serialno_infos") or itm_d.get("serial_numbers") or [],
                        "stocks": qty,
                        "entity_name": "ONLINE_SALES" if is_online else "OFFLINE_SALES",
                        "type": "INCREMENT",
                        "create_stock_mov_adj": True,
                        "ui_id": order_ui_id,
                        "order_ui_id": order_ui_id,
                        "sale_ui_id": order_ui_id,
                        "entity_id": order_ui_id,
                        "order_id": data.id,
                        "added_by": user_display,
                        "user_id": u_id,
                        "user_name": user_name,
                        "user_email": user_email,
                        "user_role": u_role,
                        "user_info": u_info,
                        "user_infos": u_info,
                        "description": f"Stock increase via {note_action} ({order_ui_id})"
                    })

                if products_toupdate:
                    restored_via_http = False
                    try:
                        import httpx
                        import os
                        inv_service_url = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8004").rstrip("/")
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            http_resp = await client.post(
                                f"{inv_service_url}/inventories/bulk-update",
                                json=products_toupdate
                            )
                            if http_resp.status_code == 200:
                                restored_via_http = True
                                ic(f"Direct HTTP stock restoration succeeded for order {order_ui_id}")
                            else:
                                ic(f"Direct HTTP stock restoration returned status {http_resp.status_code}: {http_resp.text}")
                    except Exception as http_err:
                        ic(f"Direct HTTP stock restoration failed: {http_err}")

                    if not restored_via_http:
                        try:
                            from messaging.main import RabbitMQMessagingConfig
                            rabbitmq_msg_obj = RabbitMQMessagingConfig()
                            await rabbitmq_msg_obj.publish_event(
                                routing_key="products.service.routing.key",
                                exchange_name="products.service.exchange",
                                payload={"body": products_toupdate},
                                headers={
                                    "service_name": "PRODUCTS",
                                    "entity_name": "update_bulk_prodinv",
                                    "body": products_toupdate
                                }
                            )
                            ic(f"Published stock restoration event for order {order_ui_id}")
                        except Exception as e:
                            ic(f"Failed to publish inventory restoration on order cancel/reject: {e}")

            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=data.id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))

            if new_status in ("DELIVERED", "COMPLETED"):
                await OrderReadDbRepo.settle_delivered_order_payment(order_id=data.id, shop_id=data.shop_id)

            # Dispatch order status change notification
            if new_status and new_status != old_status:
                try:
                    from integrations.notification_service import send_notification
                    from infras.read_db.main import ORDERS_COLLECTION as _READ_ORDERS_COL
                    order_doc = dict(order_data) if order_data else old_order_dict
                    order_ui_id = str(order_doc.get("ui_id") or old_order_dict.get("ui_id") or data.id)

                    read_doc = None
                    try:
                        read_doc = await _READ_ORDERS_COL.find_one(
                            {"id": data.id},
                            {"_id": 0, "user_id": 1, "customer_id": 1, "online_details": 1, "additional_infos": 1, "origin": 1}
                        )
                    except Exception:
                        read_doc = None

                    online_d = (read_doc.get("online_details") if read_doc else None) or order_doc.get("online_details") or {}
                    add_d = (read_doc.get("additional_infos") if read_doc else None) or existing_add or {}
                    cust_user_id = (
                        (read_doc.get("user_id") if read_doc else None)
                        or order_doc.get("user_id")
                        or online_d.get("user_id")
                        or add_d.get("user_id")
                        or (read_doc.get("customer_id") if read_doc else None)
                        or order_doc.get("customer_id")
                    )

                    orig_val = (read_doc.get("origin") if read_doc else None) or order_doc.get("origin") or ""
                    is_online_order = "ONLINE" in str(getattr(orig_val, "value", orig_val)).upper()

                    if cust_user_id and is_online_order:
                        cancel_detail_text = cancelled_via or "Cancelled"
                        status_map = {
                            "ACCEPTED": ("Order Accepted", f"Great news! Your order #{order_ui_id} has been accepted and will be prepared soon.", "success"),
                            "CONFIRMED": ("Order Confirmed", f"Your order #{order_ui_id} has been confirmed by the store.", "success"),
                            "PREPARING": ("Order Being Prepared", f"Your order #{order_ui_id} is currently being packed.", "info"),
                            "PROCESSING": ("Order Processing", f"Your order #{order_ui_id} is being processed.", "info"),
                            "OUT_FOR_DELIVERY": ("Order Out for Delivery!", f"Your order #{order_ui_id} is out for delivery.", "info"),
                            "DELIVERED": ("Order Delivered!", f"Your order #{order_ui_id} has been delivered. Enjoy your purchase!", "success"),
                            "COMPLETED": ("Order Completed!", f"Your order #{order_ui_id} is completed.", "success"),
                            "CANCELED": ("Order Cancelled", f"Your order #{order_ui_id} status: {cancel_detail_text}.", "error"),
                            "CANCELLED": ("Order Cancelled", f"Your order #{order_ui_id} status: {cancel_detail_text}.", "error"),
                            "REJECTED": ("Order Rejected", f"Sorry, your order #{order_ui_id} was rejected by the store.", "error"),
                        }
                        title, msg, n_type = status_map.get(
                            new_status,
                            ("Order Status Updated", f"Your order #{order_ui_id} status changed to {new_status.replace('_', ' ').title()}.", "info"),
                        )
                        await send_notification(
                            title=title,
                            message=msg,
                            notif_type=n_type,
                            user_id=str(cust_user_id),
                            user_ids=[str(cust_user_id)],
                            additional_metadata={
                                "event_type": "ORDER_STATUS",
                                "audience": "customer",
                                "shop_id": data.shop_id,
                                "order_id": str(data.id),
                                "order_ui_id": order_ui_id,
                                "status": new_status,
                                "old_status": old_status,
                                **({"cancelled_by": cancelled_actor, "cancelled_by_source": cancelled_source, "cancelled_by_label": cancelled_via} if cancelled_source else {}),
                            },
                        )

                    if new_status in ("CANCELED", "CANCELLED") and is_online_order and data.shop_id:
                        await send_notification(
                            title=f"Order #{order_ui_id} Cancelled",
                            message=f"Online order #{order_ui_id} ({cancelled_via or 'Cancelled'}).",
                            notif_type="warning",
                            user_id=str(data.shop_id),
                            user_ids=[str(data.shop_id)],
                            additional_metadata={
                                "event_type": "ORDER_STATUS",
                                "audience": "shop",
                                "shop_id": data.shop_id,
                                "order_id": str(data.id),
                                "order_ui_id": order_ui_id,
                                "status": new_status,
                                "target_shop": True,
                                **({"cancelled_by": cancelled_actor, "cancelled_by_source": cancelled_source, "cancelled_by_label": cancelled_via} if cancelled_source else {}),
                            },
                        )
                except Exception as ne:
                    ic(f"Failed dispatching order status notification: {ne}")

            try:
                from messaging.main import RabbitMQMessagingConfig
                rabbitmq_msg_obj = RabbitMQMessagingConfig()
                analytics_payload = {
                    "shop_id": data.shop_id,
                    "entity_name": "ORDER",
                    "entity_id": str(data.id),
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
                ic(f"Failed to publish analytics event on order update: {e}")

        return res
    

    async def delete(self,data:DeleteOrderSchema):
        res = await OrdersRepo(session=self.session).delete(data=data)
        if res:
            await self.session.commit()
            await OrderReadDbRepo.delete_order(order_id=data.id, shop_id=data.shop_id)
            
            try:
                order_doc = await OrderReadDbRepo.get_by_id(data.id, data.shop_id) if hasattr(OrderReadDbRepo, "get_by_id") else None
                effective_ui_id = (order_doc.get("ui_id") if isinstance(order_doc, dict) else None) or getattr(data, "ui_id", None) or f"Order #{data.id[:8]}"
                order_name = effective_ui_id
                from messaging.main import RabbitMQMessagingConfig
                rabbitmq_msg_obj = RabbitMQMessagingConfig()
                await rabbitmq_msg_obj.publish_event(
                    routing_key="activity_logs.routing.key",
                    exchange_name="activity_logs.exchange",
                    payload={
                        "shop_id": data.shop_id,
                        **get_activity_log_user_info(),
                        "service": "Order",
                        "action": "DELETED",
                        "entity_type": "ORDER",
                        "entity_id": str(effective_ui_id),
                        "entity_name": str(order_name),
                        "description": f"Deleted Order ({effective_ui_id})",
                        "changes": []
                    },
                    headers={}
                )
            except Exception as e:
                ic(f"Failed to publish activity log: {e}")
        return res
    
    async def get(self,data:GetAllOrderSchema):
        res = await OrdersRepo(session=self.session).get(data=data)
        return res
    

    async def getby_shop_id(self,data:GetOrderByShopIdSchema):
        res = await OrdersRepo(session=self.session).getby_shop_id(data=data)
        return res
    
    async def getby_customer_id(self,data:GetOrderByCustomerIdSchema):
        res = await OrdersRepo(session=self.session).getby_customer_id(data=data)
        return res
    
    

    async def getby_id(self,data:GetOrderByIdSchema):
        return await OrdersRepo(session=self.session).getby_id(data=data)
    
    async def search(self,query:str,shop_id:str,limit:int=5):
        return await OrdersRepo(session=self.session).search(shop_id=shop_id,query=query,limit=limit)

    async def get_bulk_orders(self, data: GetBulkOrdersSchema):
        res = await OrderReadDbRepo.get_bulk_orders(shop_id=data.shop_id, order_ids=data.order_ids)
        if not res:
            res = await OrdersRepo(session=self.session).get_bulk_orders(shop_id=data.shop_id, order_ids=data.order_ids)
        return res

        