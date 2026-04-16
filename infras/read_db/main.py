from motor.motor_asyncio import AsyncIOMotorClient
from core.configs.settings_config import SETTINGS
import asyncio
from icecream import ic

MONGO_CLIENT=AsyncIOMotorClient(SETTINGS.MONGO_DB_URL)


DB=MONGO_CLIENT["orders_db"]

ORDERS_COLLECTION=DB['orders_collection']