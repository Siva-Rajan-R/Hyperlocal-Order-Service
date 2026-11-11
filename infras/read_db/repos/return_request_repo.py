import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
from icecream import ic

from schemas.v1.request_scheams.order_schema import CreateReturnRequestSchema, UpdateReturnRequestStatusSchema

class ReturnRequestRepo:
    # Pluggable collections for testing and runtime
    orders_col = None
    return_requests_col = None

    @classmethod
    def get_orders_collection(cls):
        if cls.orders_col is not None:
            return cls.orders_col
        from ..main import ORDERS_COLLECTION
        return ORDERS_COLLECTION

    @classmethod
    def get_return_requests_collection(cls):
        if cls.return_requests_col is not None:
            return cls.return_requests_col
        from ..main import RETURN_REQUESTS_COLLECTION
        return RETURN_REQUESTS_COLLECTION

    @classmethod
    async def create_request(
        cls,
        data: CreateReturnRequestSchema,
        session=None,
        user_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processes a customer return request for an order.
        Validates:
        1. Order must exist.
        2. All chosen items MUST be present in that order; otherwise reject.
        3. Detailed description must be provided.
        """
        if not data.description or not data.description.strip():
            raise HTTPException(
                status_code=400,
                detail="Detailed description is required for a return request."
            )

        if not data.items:
            raise HTTPException(
                status_code=400,
                detail="At least one item must be selected for return."
            )

        orders_collection = cls.get_orders_collection()
        return_requests_collection = cls.get_return_requests_collection()

        # 1. Fetch Order from MongoDB or PostgreSQL
        order = None
        try:
            # Query by id or ui_id
            order = await orders_collection.find_one(
                {"$or": [{"id": data.order_id}, {"ui_id": data.order_id}]},
                {"_id": 0}
            )
        except Exception as e:
            ic(f"Error fetching order from MongoDB: {e}")

        if not order and session and data.shop_id:
            try:
                from infras.primary_db.repos.order_repo import OrdersRepo
                from schemas.v1.request_scheams.order_schema import GetOrderByIdSchema
                pg_order = await OrdersRepo(session=session).getby_id(
                    data=GetOrderByIdSchema(id=data.order_id, shop_id=data.shop_id)
                )
                if pg_order:
                    order = dict(pg_order._mapping) if hasattr(pg_order, "_mapping") else dict(pg_order)
            except Exception as e:
                ic(f"Error fetching order from PG: {e}")

        if not order:
            raise HTTPException(
                status_code=404,
                detail=f"Order '{data.order_id}' not found."
            )

        order_status = str(order.get("status") or "").strip().upper()
        if order_status in ("CANCELED", "CANCELLED", "REFUNDED", "REJECTED"):
            raise HTTPException(
                status_code=400,
                detail=f"Return requests cannot be created for orders with status '{order_status}'."
            )

        # 2. Extract and index all items present in the order
        raw_items = order.get("items") or []
        calc_items = (order.get("calculation_infos") or {}).get("items") or []

        order_items_by_id: Dict[str, dict] = {}
        order_items_by_prod_id: Dict[str, dict] = {}

        def _index_item(itm: dict):
            if not isinstance(itm, dict):
                return
            i_id = str(itm.get("id") or itm.get("order_item_id") or "").strip()
            p_id = str(itm.get("product_id") or "").strip()
            if i_id:
                order_items_by_id[i_id] = itm
            if p_id:
                order_items_by_prod_id[p_id] = itm

        for item in raw_items:
            _index_item(item)
        for item in calc_items:
            _index_item(item)

        # 3. Validate that each chosen item is present in the order
        enriched_items = []
        for req_item in data.items:
            matched = None
            item_id_ref = str(req_item.order_item_id or "").strip()
            prod_id_ref = str(req_item.product_id or "").strip()

            if item_id_ref and item_id_ref in order_items_by_id:
                matched = order_items_by_id[item_id_ref]
            elif prod_id_ref and prod_id_ref in order_items_by_prod_id:
                matched = order_items_by_prod_id[prod_id_ref]
            elif item_id_ref and item_id_ref in order_items_by_prod_id:
                matched = order_items_by_prod_id[item_id_ref]
            elif prod_id_ref and prod_id_ref in order_items_by_id:
                matched = order_items_by_id[prod_id_ref]

            if not matched:
                ref_name = item_id_ref or prod_id_ref or "unspecified item"
                raise HTTPException(
                    status_code=400,
                    detail=f"Item '{ref_name}' is not present in order '{data.order_id}'. Return request rejected."
                )

            # Validate requested quantity
            available_qty = float(matched.get("quantity") or matched.get("qty") or matched.get("entered_qty") or 1.0)
            req_qty = float(req_item.quantity if req_item.quantity is not None else available_qty)

            if req_qty <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Return quantity for item '{matched.get('name') or ref_name}' must be greater than 0."
                )

            if req_qty > available_qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Return quantity ({req_qty}) exceeds ordered quantity ({available_qty}) for item '{matched.get('name') or ref_name}'."
                )

            unit_price = float(
                matched.get("sell_price") or
                matched.get("price") or
                matched.get("unit_price") or
                0.0
            )
            datas_name = matched.get("datas", {}).get("product_name") if isinstance(matched.get("datas"), dict) else None
            item_name = (
                matched.get("name") or
                matched.get("product_name") or
                datas_name or
                f"Item {matched.get('product_id', '')[:8]}"
            )

            raw_var = (
                matched.get("variant_infos", {}).get("variant_name") if isinstance(matched.get("variant_infos"), dict) else
                matched.get("variant_name") or matched.get("variant")
            )
            variant_name = str(raw_var) if raw_var else None

            enriched_items.append({
                "order_item_id": matched.get("id") or matched.get("order_item_id") or item_id_ref or "",
                "product_id": matched.get("product_id") or prod_id_ref or "",
                "product_name": item_name,
                "variant_name": variant_name,
                "quantity": req_qty,
                "price": round(unit_price, 2),
                "total_amount": round(unit_price * req_qty, 2),
                "unit": req_item.unit or matched.get("entered_unit") or matched.get("unit_name") or "",
                "reason": req_item.reason or data.description.strip(),
            })

        # 4. Extract customer details
        online_details = order.get("online_details") or {}
        customer_obj = order.get("customer") or {}
        add_infos = order.get("additional_infos") or {}

        customer_name = (
            data.customer_name or
            online_details.get("name") or
            customer_obj.get("name") or
            customer_obj.get("customer_name") or
            order.get("customer_name") or
            add_infos.get("customer_name") or
            (user_info.get("name") if user_info else None) or
            "Customer"
        )
        customer_phone = (
            data.customer_phone or
            online_details.get("phone") or
            customer_obj.get("phone") or
            customer_obj.get("mobile_number") or
            order.get("customer_number") or
            add_infos.get("customer_phone") or
            (user_info.get("phone") if user_info else None) or
            "—"
        )
        customer_id = (
            data.customer_id or
            order.get("customer_id") or
            online_details.get("user_id") or
            (user_info.get("user_id") or user_info.get("id") if user_info else None) or
            ""
        )
        customer_email = (
            data.customer_email or
            online_details.get("email") or
            customer_obj.get("email") or
            (user_info.get("email") if user_info else None) or
            ""
        )

        # 5. Create return request document
        request_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        shop_id = data.shop_id or order.get("shop_id") or ""
        order_id = order.get("id") or data.order_id
        order_ui_id = order.get("ui_id") or order_id

        doc = {
            "id": request_id,
            "order_id": order_id,
            "order_ui_id": order_ui_id,
            "shop_id": shop_id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "customer_email": customer_email,
            "items": enriched_items,
            "description": data.description.strip(),
            "status": "PENDING",
            "admin_notes": "",
            "status_history": [{
                "status": "PENDING",
                "updated_by": customer_name,
                "timestamp": now_iso,
                "notes": "Return request submitted"
            }],
            "created_at": now_iso,
            "updated_at": now_iso
        }

        # 6. Save in MongoDB ReturnRequests and update order
        try:
            await return_requests_collection.insert_one(dict(doc))
        except Exception as e:
            ic(f"Error writing to RETURN_REQUESTS_COLLECTION: {e}")

        try:
            await orders_collection.update_one(
                {"id": order_id},
                {"$push": {"return_requests": doc}}
            )
        except Exception as e:
            ic(f"Error appending return_requests to order: {e}")

        # Return sanitized doc (without MongoDB _id)
        doc.pop("_id", None)

        # Dispatch notifications (non-blocking / failure-tolerant)
        try:
            from integrations.notification_service import send_notification
            item_names = ", ".join([str(i.get("product_name") or "Item") for i in enriched_items[:3]])
            if len(enriched_items) > 3:
                item_names += f" +{len(enriched_items) - 3} more"

            await send_notification(
                title=f"New Return Request #{order_ui_id}",
                message=f"{customer_name} requested a return for {item_names}.",
                notif_type="warning",
                user_id=shop_id,
                user_ids=[shop_id] if shop_id else [],
                additional_metadata={
                    "event_type": "RETURN_REQUEST_CREATED",
                    "audience": "shop",
                    "shop_id": shop_id,
                    "order_id": order_id,
                    "order_ui_id": order_ui_id,
                    "request_id": request_id,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "target_shop": True,
                },
            )

            cust_target = (
                online_details.get("user_id")
                or order.get("user_id")
                or customer_id
            )
            if cust_target and cust_target != shop_id:
                await send_notification(
                    title="Return Request Submitted",
                    message=f"Your return request for Order #{order_ui_id} has been submitted and is pending review.",
                    notif_type="info",
                    user_id=str(cust_target),
                    user_ids=[str(cust_target)],
                    additional_metadata={
                        "event_type": "RETURN_REQUEST_CREATED",
                        "audience": "customer",
                        "shop_id": shop_id,
                        "order_id": order_id,
                        "order_ui_id": order_ui_id,
                        "request_id": request_id,
                        "status": "PENDING",
                    },
                )
        except Exception as ne:
            ic(f"Failed sending return create notification: {ne}")

        return doc

    @classmethod
    async def get_by_user_id(
        cls,
        user_id: str,
        limit: int = 50,
        offset: int = 1,
    ) -> List[Dict[str, Any]]:
        if not user_id:
            return []

        orders_collection = cls.get_orders_collection()
        return_requests_collection = cls.get_return_requests_collection()

        try:
            user_orders_cursor = orders_collection.find(
                {
                    "$or": [
                        {"user_id": user_id},
                        {"customer_id": user_id},
                        {"online_details.user_id": user_id},
                        {"additional_infos.user_id": user_id},
                    ]
                },
                {"_id": 0, "id": 1, "ui_id": 1, "return_requests": 1, "shop_id": 1},
            ).limit(500)
            user_orders = await user_orders_cursor.to_list(length=500)
        except Exception as e:
            ic(f"Error looking up orders for user return requests: {e}")
            user_orders = []

        order_ids = []
        order_ui_ids = []
        embedded_requests: List[Dict[str, Any]] = []
        for ord_doc in user_orders:
            oid = ord_doc.get("id")
            ouid = ord_doc.get("ui_id")
            if oid:
                order_ids.append(oid)
            if ouid:
                order_ui_ids.append(ouid)
            for emb in (ord_doc.get("return_requests") or []):
                if isinstance(emb, dict):
                    emb_copy = dict(emb)
                    if not emb_copy.get("order_id") and oid:
                        emb_copy["order_id"] = oid
                    if not emb_copy.get("order_ui_id") and ouid:
                        emb_copy["order_ui_id"] = ouid
                    if not emb_copy.get("shop_id") and ord_doc.get("shop_id"):
                        emb_copy["shop_id"] = ord_doc["shop_id"]
                    embedded_requests.append(emb_copy)

        or_conds: List[Dict[str, Any]] = [
            {"customer_id": user_id},
            {"user_id": user_id},
        ]
        if order_ids:
            or_conds.append({"order_id": {"$in": order_ids}})
        if order_ui_ids:
            or_conds.append({"order_ui_id": {"$in": order_ui_ids}})

        try:
            cursor = return_requests_collection.find({"$or": or_conds}, {"_id": 0}).sort("created_at", -1)
            db_docs = await cursor.to_list(length=500)
        except Exception as e:
            ic(f"Error getting return requests by user_id: {e}")
            db_docs = []

        by_id: Dict[str, Dict[str, Any]] = {}
        for doc in db_docs:
            key = str(doc.get("id") or f"{doc.get('order_id')}:{doc.get('created_at')}")
            by_id[key] = doc
        for emb in embedded_requests:
            key = str(emb.get("id") or f"{emb.get('order_id')}:{emb.get('created_at')}")
            if key not in by_id:
                by_id[key] = emb

        merged = sorted(
            by_id.values(),
            key=lambda d: str(d.get("created_at") or ""),
            reverse=True,
        )
        start = max(0, (offset - 1) * limit)
        return merged[start : start + limit]

    @classmethod
    async def get_by_shop_id(
        cls,
        shop_id: str,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 1
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if shop_id and shop_id != "string" and shop_id != "ALL":
            query["shop_id"] = shop_id

        if order_id:
            query["$or"] = [{"order_id": order_id}, {"order_ui_id": order_id}]

        if status and status.upper() != "ALL":
            query["status"] = status.upper()

        skip_count = max(0, (offset - 1) * limit)
        return_requests_collection = cls.get_return_requests_collection()
        try:
            cursor = return_requests_collection.find(query, {"_id": 0}).sort("created_at", -1).skip(skip_count).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            ic(f"Error getting return requests: {e}")
            return []

    @classmethod
    async def get_by_order_id(cls, order_id: str) -> List[Dict[str, Any]]:
        return_requests_collection = cls.get_return_requests_collection()
        try:
            cursor = return_requests_collection.find(
                {"$or": [{"order_id": order_id}, {"order_ui_id": order_id}]},
                {"_id": 0}
            ).sort("created_at", -1)
            return await cursor.to_list(length=100)
        except Exception as e:
            ic(f"Error getting return requests by order_id: {e}")
            return []

    @classmethod
    async def get_by_id(cls, request_id: str) -> Optional[Dict[str, Any]]:
        return_requests_collection = cls.get_return_requests_collection()
        try:
            return await return_requests_collection.find_one({"id": request_id}, {"_id": 0})
        except Exception as e:
            ic(f"Error getting return request by id: {e}")
            return None

    @classmethod
    async def update_status(
        cls,
        request_id: str,
        data: UpdateReturnRequestStatusSchema,
        user_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Updates the status of a return request to ACCEPTED or REJECTED.
        """
        new_status = (data.status or "").strip().upper()
        if new_status not in ("ACCEPTED", "REJECTED", "PENDING"):
            raise HTTPException(
                status_code=400,
                detail="Invalid status. Status must be 'ACCEPTED' or 'REJECTED'."
            )

        return_requests_collection = cls.get_return_requests_collection()
        orders_collection = cls.get_orders_collection()

        existing = await return_requests_collection.find_one({"id": request_id}, {"_id": 0})
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Return request '{request_id}' not found."
            )

        updater_name = "Merchant"
        if user_info:
            updater_name = user_info.get("name") or user_info.get("user_name") or user_info.get("email") or "Merchant"

        now_iso = datetime.now(timezone.utc).isoformat()
        history_entry = {
            "status": new_status,
            "updated_by": updater_name,
            "timestamp": now_iso,
            "notes": data.admin_notes or f"Status changed to {new_status}"
        }

        update_fields: Dict[str, Any] = {
            "status": new_status,
            "updated_at": now_iso,
        }
        if data.admin_notes is not None:
            update_fields["admin_notes"] = data.admin_notes

        await return_requests_collection.update_one(
            {"id": request_id},
            {
                "$set": update_fields,
                "$push": {"status_history": history_entry}
            }
        )

        # Also update within order if present
        order_id = existing.get("order_id")
        if order_id:
            try:
                await orders_collection.update_one(
                    {"id": order_id, "return_requests.id": request_id},
                    {
                        "$set": {
                            "return_requests.$.status": new_status,
                            "return_requests.$.updated_at": now_iso,
                            "return_requests.$.admin_notes": data.admin_notes or ""
                        }
                    }
                )
            except Exception as e:
                ic(f"Error syncing return request status into order: {e}")

        updated_doc = await return_requests_collection.find_one({"id": request_id}, {"_id": 0})
        result_doc = updated_doc or existing

        # Dispatch notification to customer on return request status change
        try:
            old_status = str(existing.get("status") or "").upper()
            if new_status and new_status != old_status:
                order_id = result_doc.get("order_id") or existing.get("order_id") or ""
                order_ui_id = result_doc.get("order_ui_id") or existing.get("order_ui_id") or order_id
                shop_id = result_doc.get("shop_id") or existing.get("shop_id") or ""

                # Resolve authenticated customer user_id
                target_user_id = result_doc.get("user_id") or result_doc.get("customer_id") or ""
                if order_id:
                    try:
                        ord_doc = await orders_collection.find_one(
                            {"$or": [{"id": order_id}, {"ui_id": order_id}]},
                            {"_id": 0, "user_id": 1, "online_details": 1, "additional_infos": 1, "customer_id": 1}
                        )
                        if ord_doc:
                            online_d = ord_doc.get("online_details") or {}
                            add_d = ord_doc.get("additional_infos") or {}
                            resolved = (
                                ord_doc.get("user_id")
                                or online_d.get("user_id")
                                or add_d.get("user_id")
                                or ord_doc.get("customer_id")
                            )
                            if resolved:
                                target_user_id = resolved
                    except Exception:
                        pass

                if target_user_id:
                    from integrations.notification_service import send_notification
                    notes_suffix = f" Note: {data.admin_notes.strip()}" if data.admin_notes and data.admin_notes.strip() else ""
                    if new_status == "ACCEPTED":
                        title = "Return Request Accepted"
                        msg = f"Your return request for Order #{order_ui_id} was accepted by the seller.{notes_suffix}"
                        n_type = "success"
                    elif new_status == "REJECTED":
                        title = "Return Request Rejected"
                        msg = f"Your return request for Order #{order_ui_id} was rejected.{notes_suffix}"
                        n_type = "error"
                    elif new_status == "COMPLETED":
                        title = "Return Refund Completed"
                        msg = f"Your return for Order #{order_ui_id} has been completed.{notes_suffix}"
                        n_type = "success"
                    else:
                        title = "Return Request Updated"
                        msg = f"Your return request for Order #{order_ui_id} status is now {new_status}.{notes_suffix}"
                        n_type = "info"

                    await send_notification(
                        title=title,
                        message=msg,
                        notif_type=n_type,
                        user_id=str(target_user_id),
                        user_ids=[str(target_user_id)],
                        additional_metadata={
                            "event_type": "RETURN_REQUEST_STATUS",
                            "audience": "customer",
                            "shop_id": shop_id,
                            "order_id": order_id,
                            "order_ui_id": order_ui_id,
                            "request_id": request_id,
                            "status": new_status,
                        },
                    )
        except Exception as ne:
            ic(f"Failed sending return status notification: {ne}")

        return result_doc
