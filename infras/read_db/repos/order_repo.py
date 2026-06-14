from infras.read_db.main import ORDERS_COLLECTION
from schemas.v1.request_scheams.order_schema import GetAllOrderSchema, GetOrderByShopIdSchema, GetOrderByCustomerIdSchema, GetOrderByIdSchema
from icecream import ic
from typing import List, Dict, Union, Optional
import re

class OrderReadDbRepo:

    @classmethod
    async def replace_order(cls, data: dict):
        try:
            from ..models.order_model import OrderReadModel
            from .order_stats_repo import OrderStatsReadDbRepo
            
            # Format the incoming data using the Pydantic model
            structured_data = OrderReadModel(**data).model_dump(mode="json", exclude_none=True)
            
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
    def _build_search_query(cls, base_query: dict, search_term: str) -> dict:
        if not search_term:
            return base_query
            
        pattern = re.compile(f".*{re.escape(search_term)}.*", re.IGNORECASE)
        search_conds = [
            {"id": {"$regex": pattern}},
            {"origin": {"$regex": pattern}},
            {"status": {"$regex": pattern}},
            {"shop_id": {"$regex": pattern}}
        ]
        
        if not base_query:
            return {"$or": search_conds}
            
        return {"$and": [base_query, {"$or": search_conds}]}

    @classmethod
    async def get_overall_values(cls, query_filter: dict) -> dict:
        try:
            shop_id = query_filter.get("shop_id")
            if isinstance(shop_id, dict):
                # Handle regex or other query structures if any, though shop_id is usually a string
                pass
                
            from .order_stats_repo import OrderStatsReadDbRepo
            
            # Since overall stats are now shop-wide, extract shop_id from query.
            # If shop_id is not directly available or complex, we fallback to a default structure.
            shop_id_val = shop_id if isinstance(shop_id, str) else "UNKNOWN"
            
            # If the query is complex with $and, find the shop_id
            if not isinstance(shop_id, str) and "$and" in query_filter:
                for cond in query_filter["$and"]:
                    if "shop_id" in cond and isinstance(cond["shop_id"], str):
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
                "walkin_customer_count": 0
            }

    @classmethod
    async def get(cls, data: GetAllOrderSchema) -> Union[List[dict], dict]:
        offset = data.offset if data.offset > 0 else 1
        skip = (offset - 1) * data.limit
        
        base_query = {"type": {"$ne": "EXCHANGE"}}
        query = cls._build_search_query(base_query, data.query)
        
        cursor = ORDERS_COLLECTION.find(query).sort("created_at", -1).skip(skip).limit(data.limit)
        orders = await cursor.to_list(length=data.limit)
        
        for order in orders:
            order["_id"] = str(order["_id"])
            
        if data.offset in (0, 1):
            overall_values = await cls.get_overall_values(query)
            return {"overall_datas": overall_values, "datas": orders}
            
        return {"datas": orders}

    @classmethod
    async def getby_shop_id(cls, data: GetOrderByShopIdSchema) -> Union[List[dict], dict]:
        offset = data.offset if data.offset > 0 else 1
        skip = (offset - 1) * data.limit
        
        base_query = {"type": {"$ne": "EXCHANGE"}, "shop_id": data.shop_id}
        query = cls._build_search_query(base_query, data.query)
        
        cursor = ORDERS_COLLECTION.find(query).sort("created_at", -1).skip(skip).limit(data.limit)
        orders = await cursor.to_list(length=data.limit)
        
        for order in orders:
            order["_id"] = str(order["_id"])
            
        if data.offset in (0, 1):
            overall_values = await cls.get_overall_values(query)
            return {"overall_datas": overall_values, "datas": orders}
            
        return {"datas": orders}

    @classmethod
    async def getby_customer_id(cls, data: GetOrderByCustomerIdSchema) -> Union[List[dict], dict]:
        offset = data.offset if data.offset > 0 else 1
        skip = (offset - 1) * data.limit
        
        base_query = {"type": {"$ne": "EXCHANGE"}, "shop_id": data.shop_id, "customer.customer_id": data.customer_id}
        query = cls._build_search_query(base_query, data.query)
        
        cursor = ORDERS_COLLECTION.find(query).sort("created_at", -1).skip(skip).limit(data.limit)
        orders = await cursor.to_list(length=data.limit)
        
        for order in orders:
            order["_id"] = str(order["_id"])
            
        if data.offset in (0, 1):
            overall_values = await cls.get_overall_values(query)
            return {"overall_datas": overall_values, "datas": orders}
            
        return {"datas": orders}

    @classmethod
    async def getby_id(cls, data: GetOrderByIdSchema) -> Optional[dict]:
        query = {"shop_id": data.shop_id, "id": data.id, "type": {"$ne": "EXCHANGE"}}
        order = await ORDERS_COLLECTION.find_one(query)
        
        if order:
            order["_id"] = str(order["_id"])
            
        return order

    @classmethod
    async def search(cls, shop_id: str, query_str: str, limit: int = 5) -> List[dict]:
        base_query = {"shop_id": shop_id}
        query = cls._build_search_query(base_query, query_str)
        
        cursor = ORDERS_COLLECTION.find(query).sort("created_at", -1).limit(limit)
        orders = await cursor.to_list(length=limit)
        
        for order in orders:
            order["_id"] = str(order["_id"])
            
        return orders
