from infras.read_db.main import ORDER_DELIVERY_CODES_COLLECTION
import random
import string
import datetime
from icecream import ic
from typing import List, Dict, Optional

class DeliveryCodeRepo:

    @classmethod
    async def generate_and_store_code(cls, shop_id: str, order_id: str) -> str:
        try:
            # Generate a 6-digit random code
            code = ''.join(random.choices(string.digits, k=6))
            
            payload = {
                "shop_id": shop_id,
                "order_id": order_id,
                "code": code,
                "created_at": datetime.datetime.now(datetime.timezone.utc)
            }
            
            # Upsert the code so we don't create multiple if called again
            await ORDER_DELIVERY_CODES_COLLECTION.update_one(
                {"shop_id": shop_id, "order_id": order_id},
                {"$set": payload},
                upsert=True
            )
            ic(f"Delivery code {code} generated for order {order_id}")
            return code
        except Exception as e:
            ic(f"Error generating delivery code: {e}")
            return ""

    @classmethod
    async def verify_code(cls, shop_id: str, order_id: str, code: str) -> bool:
        try:
            # Check if code matches
            doc = await ORDER_DELIVERY_CODES_COLLECTION.find_one({
                "shop_id": shop_id, 
                "order_id": order_id,
                "code": code
            })
            return bool(doc)
        except Exception as e:
            ic(f"Error verifying delivery code: {e}")
            return False

    @classmethod
    async def delete_code(cls, shop_id: str, order_id: str) -> bool:
        try:
            res = await ORDER_DELIVERY_CODES_COLLECTION.delete_one({
                "shop_id": shop_id,
                "order_id": order_id
            })
            return res.deleted_count > 0
        except Exception as e:
            ic(f"Error deleting delivery code: {e}")
            return False

    @classmethod
    async def get_codes_for_orders(cls, order_ids: List[str]) -> Dict[str, str]:
        try:
            cursor = ORDER_DELIVERY_CODES_COLLECTION.find({
                "order_id": {"$in": order_ids}
            })
            docs = await cursor.to_list(length=None)
            return {doc["order_id"]: doc["code"] for doc in docs}
        except Exception as e:
            ic(f"Error fetching bulk delivery codes: {e}")
            return {}
