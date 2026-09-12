from infras.read_db.main import ORDERS_COLLECTION
from schemas.v1.request_scheams.order_schema import GetAllOrderSchema, GetOrderByShopIdSchema, GetOrderByCustomerIdSchema, GetOrderByIdSchema
from icecream import ic
from typing import List, Dict, Union, Optional
import re
from datetime import datetime, timezone as dt_tz


def _check_filter(data, attrs: tuple) -> bool:
    for attr in attrs:
        val = getattr(data, attr, None)
        if val is not None:
            if isinstance(val, str):
                return val.strip().lower() in ("true", "1", "yes")
            return bool(val)
    return False

def is_exclude_online(data) -> bool:
    return _check_filter(data, (
        'exclude_online', 'exclude_online_orders', 'exclude_online_order',
    ))

def is_exclude_offline(data) -> bool:
    return _check_filter(data, (
        'exclude_offline', 'exclude_offline_orders', 'exclude_offline_order', 'exclude_pos', 'exclude_direct',
    ))

def is_exclude_return(data) -> bool:
    return _check_filter(data, (
        'exclude_return', 'exclude_returns', 'exclude_returned',
        'exclude_has_return', 'exclude_has_returns', 'exclude_with_return', 'exclude_with_returns'
    ))

def is_exclude_non_return(data) -> bool:
    return _check_filter(data, (
        'exclude_non_return', 'exclude_non_returns', 'exclude_no_return',
        'exclude_no_returns', 'exclude_without_return', 'exclude_without_returns'
    ))


class OrderReadDbRepo:

    @classmethod
    def _build_search_query(cls, base_query: dict, search_term: str) -> dict:
        if not search_term:
            return base_query

        pattern = re.compile(f".*{re.escape(search_term)}.*", re.IGNORECASE)
        search_conds = [
            {"id": {"$regex": pattern}},
            {"ui_id": {"$regex": pattern}},
            {"origin": {"$regex": pattern}},
            {"status": {"$regex": pattern}},
            {"shop_id": {"$regex": pattern}},
        ]

        if not base_query:
            return {"$or": search_conds}

        return {"$and": [base_query, {"$or": search_conds}]}

    @classmethod
    def _build_filter_query(cls, base_query: dict, data) -> dict:
        """Build a MongoDB query dict from any order request schema."""
        try:
            import pytz
        except ImportError:
            pytz = None

        and_clauses = []
        if base_query:
            and_clauses.append(base_query)

        # --- status ---
        status = getattr(data, "status", None)
        if status:
            status_val = str(status.value if hasattr(status, "value") else status).strip().lower()
            if status_val in ("complete", "completed"):
                and_clauses.append({"status": {"$in": ["COMPLETED", "completed", "complete"]}})
            elif status_val in ("pending", "prning"):
                and_clauses.append({"status": {"$in": ["PENDING", "pending", "PRNING", "prning"]}})
            elif status_val in ("cancelled", "canceled", "cnacedeld"):
                and_clauses.append({"status": {"$in": ["CANCELLED", "CANCELED", "cancelled", "canceled", "cnacedeld"]}})
            elif status_val == "online":
                and_clauses.append({
                    "$or": [
                        {"origin": re.compile("^online$", re.IGNORECASE)},
                        {"online_details": {"$exists": True, "$ne": None}},
                    ]
                })
            elif status_val == "offline":
                and_clauses.append({
                    "origin": {"$nin": ["ONLINE", "online", "Online"]},
                    "$or": [
                        {"online_details": {"$exists": False}},
                        {"online_details": None}
                    ]
                })
            else:
                and_clauses.append({"status": re.compile(f"^{re.escape(status_val)}$", re.IGNORECASE)})

        # --- origin ---
        origin = getattr(data, "origin", None)
        if origin:
            origin_val = str(origin.value if hasattr(origin, "value") else origin).strip().upper()
            if origin_val == "ONLINE":
                and_clauses.append({
                    "$or": [
                        {"origin": re.compile("^online$", re.IGNORECASE)},
                        {"online_details": {"$exists": True, "$ne": None}},
                    ]
                })
            else:
                and_clauses.append({"origin": re.compile(f"^{re.escape(origin_val)}$", re.IGNORECASE)})

        # --- exclude_online / exclude_offline / online_only ---
        ex_online = is_exclude_online(data) or (getattr(data, 'online_only', None) is False)
        ex_offline = is_exclude_offline(data) or (getattr(data, 'online_only', None) is True)

        if ex_online and ex_offline:
            and_clauses.append({"_id": {"$exists": False}})  # Contradiction: match none
        elif ex_online:
            and_clauses.append({
                "origin": {"$nin": ["ONLINE", "online", "Online"]},
                "$or": [
                    {"online_details": {"$exists": False}},
                    {"online_details": None}
                ]
            })
        elif ex_offline:
            and_clauses.append({
                "$or": [
                    {"origin": re.compile("^online$", re.IGNORECASE)},
                    {"online_details": {"$exists": True, "$ne": None}},
                ]
            })

        # --- exclude_return / exclude_non_return ---
        ex_ret = is_exclude_return(data)
        ex_non_ret = is_exclude_non_return(data)

        if ex_ret and ex_non_ret:
            and_clauses.append({"_id": {"$exists": False}})  # Contradiction: match none
        elif ex_ret:
            and_clauses.append({
                "$or": [
                    {"returns": {"$exists": False}},
                    {"returns": None},
                    {"returns": {"$size": 0}},
                    {"returns": []}
                ]
            })
        elif ex_non_ret:
            and_clauses.append({
                "$and": [
                    {"returns": {"$exists": True, "$ne": None, "$ne": []}},
                    {"returns.0": {"$exists": True}}
                ]
            })

        # --- payment_method ---
        payment_method = getattr(data, "payment_method", None)
        if payment_method:
            pm = str(payment_method).upper()
            and_clauses.append({
                "$or": [
                    {f"payment_infos.{pm}": {"$exists": True}},
                    {"payment_infos": {"$elemMatch": {"mode": re.compile(f"^{re.escape(pm)}$", re.IGNORECASE)}}},
                ]
            })

        # --- payment_status (via pending_amount field stored in MongoDB) ---
        payment_status_filter = getattr(data, "payment_status", None)
        if payment_status_filter:
            p_status = str(payment_status_filter).lower().replace("_", " ").strip()
            if p_status == "paid":
                and_clauses.append({"pending_amount": {"$in": [0, 0.0]}})
            elif p_status in ("not paid", "unpaid"):
                and_clauses.append({"pending_amount": {"$gt": 0}, "payment_status": re.compile("^pending$", re.IGNORECASE)})
            elif p_status in ("partially paid", "partialy paid", "partially_paid"):
                and_clauses.append({"pending_amount": {"$gt": 0}, "payment_status": {"$not": re.compile("^pending$", re.IGNORECASE)}})

        # --- date range (timezone-aware) ---
        tz_str = "Asia/Kolkata"
        if hasattr(data, "timezone") and getattr(data, "timezone"):
            tz_val = getattr(data, "timezone")
            tz_str = tz_val.value if hasattr(tz_val, "value") else str(tz_val)

        user_tz = None
        if pytz:
            try:
                user_tz = pytz.timezone(tz_str)
            except Exception:
                user_tz = pytz.timezone("Asia/Kolkata")

        from_date = getattr(data, "from_date", None)
        to_date = getattr(data, "to_date", None)

        if from_date and user_tz:
            from_str = str(from_date).strip()
            if len(from_str) <= 10:
                from_str += " 00:00:00"
            try:
                from_dt = user_tz.localize(
                    datetime.strptime(from_str[:19], "%Y-%m-%d %H:%M:%S")
                ).astimezone(dt_tz.utc)
                and_clauses.append(
                    {"$or": [{"created_at": {"$gte": from_dt}}, {"date": {"$gte": from_dt}}]}
                )
            except Exception as ex:
                ic(f"[ReadDB] from_date parse error: {ex}")

        if to_date and user_tz:
            to_str = str(to_date).strip()
            if len(to_str) <= 10:
                to_str += " 23:59:59"
            try:
                to_dt = user_tz.localize(
                    datetime.strptime(to_str[:19], "%Y-%m-%d %H:%M:%S")
                ).astimezone(dt_tz.utc)
                and_clauses.append(
                    {"$or": [{"created_at": {"$lte": to_dt}}, {"date": {"$lte": to_dt}}]}
                )
            except Exception as ex:
                ic(f"[ReadDB] to_date parse error: {ex}")

        # --- text search ---
        search_term = getattr(data, "query", None) or getattr(data, "q", None)
        if search_term and str(search_term).strip():
            pattern = re.compile(f".*{re.escape(str(search_term).strip())}.*", re.IGNORECASE)
            and_clauses.append({
                "$or": [
                    {"id": {"$regex": pattern}},
                    {"ui_id": {"$regex": pattern}},
                    {"origin": {"$regex": pattern}},
                    {"status": {"$regex": pattern}},
                    {"shop_id": {"$regex": pattern}},
                ]
            })

        if not and_clauses:
            return {}
        if len(and_clauses) == 1:
            return and_clauses[0]
        return {"$and": and_clauses}

    @classmethod
    async def replace_order(cls, data: dict):
        try:
            from ..models.order_model import OrderReadModel
            from .order_stats_repo import OrderStatsReadDbRepo

            structured_data = OrderReadModel(**data).model_dump(mode="json", exclude_none=True)
            structured_data.pop("_id", None)

            existing_doc = await ORDERS_COLLECTION.find_one({"id": structured_data["id"]})
            if existing_doc:
                for key in ["calculation_infos", "charges_infos", "item_infos", "additional_infos", "online_details", "payment_infos"]:
                    if not structured_data.get(key) and existing_doc.get(key):
                        structured_data[key] = existing_doc[key]

                for key in ["returns", "exchanges"]:
                    old_arr = existing_doc.get(key) or []
                    new_arr = structured_data.get(key) or []
                    merged_dict = {x["id"]: x for x in old_arr if "id" in x}
                    for x in new_arr:
                        if "id" in x:
                            merged_dict[x["id"]] = x
                    structured_data[key] = list(merged_dict.values())

                if existing_doc.get("customer") and not structured_data.get("customer"):
                    structured_data["customer"] = existing_doc["customer"]

                pg_items_map = {item["id"]: item for item in structured_data.get("items", [])}
                existing_items = {item["id"]: item for item in existing_doc.get("items", []) if item.get("id")}

                merged_items = []
                for item_id, existing_item in existing_items.items():
                    if item_id in pg_items_map:
                        merged = dict(existing_item)
                        pg_item = pg_items_map[item_id]
                        for pg_key in ["status", "returned_quantity", "exchanged_quantity", "entered_qty", "entered_unit"]:
                            if pg_item.get(pg_key) is not None:
                                merged[pg_key] = pg_item[pg_key]
                        merged_items.append(merged)
                    else:
                        merged_items.append(existing_item)

                for item_id, pg_item in pg_items_map.items():
                    if item_id not in existing_items:
                        merged_items.append(pg_item)

                final_merged_items = []
                for item in merged_items:
                    add_info = item.get("additional_infos") or {}
                    if not add_info.get("is_replacement"):
                        final_merged_items.append(item)

                structured_data["items"] = final_merged_items

            res = await ORDERS_COLLECTION.replace_one(
                {"id": structured_data["id"]},
                structured_data,
                upsert=True
            )

            if res.acknowledged and "shop_id" in structured_data:
                import asyncio
                asyncio.create_task(OrderStatsReadDbRepo.update_stats(structured_data["shop_id"]))
                customer = structured_data.get("customer")
                if customer and customer.get("customer_id"):
                    from .order_stats_repo import CustomerStatsReadDbRepo
                    asyncio.create_task(CustomerStatsReadDbRepo.update_customer_stats(structured_data["shop_id"], customer["customer_id"]))

            return bool(res.acknowledged)
        except Exception as e:
            ic(f"Error replacing order in Read DB: {e}")
            return False

    @classmethod
    async def get_all(cls) -> List[dict]:
        try:
            cursor = ORDERS_COLLECTION.find({}, {"_id": 0})
            return await cursor.to_list(length=None)
        except Exception as e:
            ic(f"Error in get_all: {e}")
            return []

    @classmethod
    async def get_by_shop_id(cls, shop_id: str) -> List[dict]:
        """Simple internal fetch by shop_id only — no pagination/filtering."""
        try:
            cursor = ORDERS_COLLECTION.find({"shop_id": shop_id}, {"_id": 0})
            return await cursor.to_list(length=None)
        except Exception as e:
            ic(f"Error in get_by_shop_id: {e}")
            return []

    @classmethod
    async def get_by_id(cls, shop_id: str, order_id: str) -> Optional[dict]:
        try:
            return await ORDERS_COLLECTION.find_one(
                {"shop_id": shop_id, "id": order_id},
                {"_id": 0}
            )
        except Exception as e:
            ic(f"Error in get_by_id: {e}")
            return None

    @classmethod
    async def delete_order(cls, order_id: str, shop_id: str):
        try:
            res = await ORDERS_COLLECTION.delete_one({"id": order_id, "shop_id": shop_id})
            if res.deleted_count:
                from .order_stats_repo import OrderStatsReadDbRepo
                import asyncio
                asyncio.create_task(OrderStatsReadDbRepo.update_stats(shop_id))
            return bool(res.deleted_count)
        except Exception as e:
            ic(f"Error deleting order from Read DB: {e}")
            return False

    @classmethod
    async def get_overall_values(cls, query_filter: dict) -> dict:
        try:
            from .order_stats_repo import OrderStatsReadDbRepo
            shop_id_val = "UNKNOWN"
            shop_id = query_filter.get("shop_id")
            if isinstance(shop_id, str):
                shop_id_val = shop_id
            elif "$and" in query_filter:
                for cond in query_filter["$and"]:
                    if isinstance(cond, dict) and "shop_id" in cond and isinstance(cond["shop_id"], str):
                        shop_id_val = cond["shop_id"]
                        break
            stats = await OrderStatsReadDbRepo.get_stats(shop_id_val)
            return stats
        except Exception as e:
            ic(f"Error getting overall values: {e}")
            return {
                "total_order_value": 0,
                "total_orders": 0,
                "total_returns": 0,
                "total_exchanged": 0,
                "registered_customer_count": 0,
                "walkin_customer_count": 0,
            }

    @classmethod
    async def get(cls, data: GetAllOrderSchema) -> Union[List[dict], dict]:
        """Fetch all orders with full filtering, pagination, and search."""
        try:
            offset = data.offset if data.offset > 0 else 1
            skip = (offset - 1) * data.limit

            base_query = {"type": {"$ne": "EXCHANGE"}}
            query = cls._build_filter_query(base_query, data)
            ic(f"[ReadDB] get() query: {query}")

            cursor = ORDERS_COLLECTION.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(data.limit)
            orders = await cursor.to_list(length=data.limit)

            if data.offset in (0, 1):
                overall_values = await cls.get_overall_values(query)
                return {"overall_datas": overall_values, "datas": orders}

            return {"datas": orders}
        except Exception as e:
            ic(f"[ReadDB] Error in get(): {e}")
            return {"datas": []}

    @classmethod
    async def get_by_shop_id_filtered(cls, data: GetOrderByShopIdSchema) -> Union[List[dict], dict]:
        """Fetch orders by shop with full filtering, pagination, and search."""
        try:
            offset = data.offset if data.offset > 0 else 1
            skip = (offset - 1) * data.limit

            base_query = {"type": {"$ne": "EXCHANGE"}, "shop_id": data.shop_id}
            query = cls._build_filter_query(base_query, data)
            ic(f"[ReadDB] get_by_shop_id_filtered() query: {query}")

            cursor = ORDERS_COLLECTION.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(data.limit)
            orders = await cursor.to_list(length=data.limit)

            if data.offset in (0, 1):
                overall_values = await cls.get_overall_values(query)
                return {"overall_datas": overall_values, "datas": orders}

            return {"datas": orders}
        except Exception as e:
            ic(f"[ReadDB] Error in get_by_shop_id_filtered(): {e}")
            return {"datas": []}

    @classmethod
    async def getby_customer_id(cls, data: GetOrderByCustomerIdSchema) -> Union[List[dict], dict]:
        """Fetch orders by customer with full filtering, pagination, and search."""
        try:
            offset = data.offset if data.offset > 0 else 1
            skip = (offset - 1) * data.limit

            base_query = {
                "type": {"$ne": "EXCHANGE"},
                "shop_id": data.shop_id,
                "customer.customer_id": data.customer_id,
            }
            query = cls._build_filter_query(base_query, data)
            ic(f"[ReadDB] getby_customer_id() query: {query}")

            cursor = ORDERS_COLLECTION.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(data.limit)
            orders = await cursor.to_list(length=data.limit)

            if data.offset in (0, 1):
                overall_values = await cls.get_overall_values(query)
                return {"overall_datas": overall_values, "datas": orders}

            return {"datas": orders}
        except Exception as e:
            ic(f"[ReadDB] Error in getby_customer_id(): {e}")
            return {"datas": []}

    @classmethod
    async def search(cls, shop_id: str, query_str: str, limit: int = 5) -> List[dict]:
        base_query = {"shop_id": shop_id}
        query = cls._build_search_query(base_query, query_str)
        cursor = ORDERS_COLLECTION.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    @classmethod
    async def get_bulk_orders(cls, shop_id: str, order_ids: List[str]) -> List[dict]:
        try:
            query = {"shop_id": shop_id, "id": {"$in": order_ids}}
            cursor = ORDERS_COLLECTION.find(query, {"_id": 0})
            return await cursor.to_list(length=len(order_ids))
        except Exception as e:
            ic(f"Error in get_bulk_orders: {e}")
            return []

    @classmethod
    async def get_by_user_id(cls, user_id: str, limit: int = 10, offset: int = 1) -> dict:
        try:
            skip = (offset - 1) * limit
            query = {"online_details.user_id": user_id}
            cursor = ORDERS_COLLECTION.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
            orders = await cursor.to_list(length=limit)
            return {"datas": orders}
        except Exception as e:
            ic(f"Error in get_by_user_id: {e}")
            return {"datas": []}

    @classmethod
    async def get_bulk_orders_without_shop(cls, order_ids: List[str]) -> List[dict]:
        try:
            cursor = ORDERS_COLLECTION.find({"id": {"$in": order_ids}}, {"_id": 0})
            return await cursor.to_list(length=len(order_ids))
        except Exception as e:
            ic(f"Error in get_bulk_orders_without_shop: {e}")
            return []
