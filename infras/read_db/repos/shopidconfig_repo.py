from motor.motor_asyncio import AsyncIOMotorDatabase
from ..main import DB
from ..models.shopidconfig_model import ShopIdConfigReadModel
from icecream import ic

class ShopIdConfigReadDbRepo:
    collection_name = "shop_id_configs"

    @classmethod
    async def get_db(cls) -> AsyncIOMotorDatabase:
        return DB

    @classmethod
    async def upsert_config(cls, data: ShopIdConfigReadModel):
        try:
            db = await cls.get_db()
            collection = db[cls.collection_name]
            await collection.update_one(
                {"shop_id": data.shop_id},
                {"$set": data.model_dump()},
                upsert=True
            )
            return True
        except Exception as e:
            ic(f"Error in ShopIdConfigReadDbRepo upsert_config: {e}")
            return False

    @classmethod
    async def get_config(cls, shop_id: str) -> dict:
        try:
            db = await cls.get_db()
            collection = db[cls.collection_name]
            doc = await collection.find_one({"shop_id": shop_id})
            return doc.get("config", {}) if doc else {}
        except Exception as e:
            ic(f"Error in ShopIdConfigReadDbRepo get_config: {e}")
            return {}
