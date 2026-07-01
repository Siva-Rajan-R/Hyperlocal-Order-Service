from motor.motor_asyncio import AsyncIOMotorClient
from core.configs.settings_config import SETTINGS
import asyncio
from icecream import ic

MONGO_CLIENT=AsyncIOMotorClient(SETTINGS.MONGO_DB_URL)


DB=MONGO_CLIENT["OrdersDb"]

ORDERS_COLLECTION=DB['OrdersCollection']
ORDER_STATS_COLLECTION=DB['order_stats_collection']
CUSTOMER_STATS_COLLECTION=DB['customer_stats_collection']