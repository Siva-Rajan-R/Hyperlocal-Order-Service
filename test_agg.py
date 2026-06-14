import asyncio
import sys
import os

# Add primary directory to path if needed to find configs, though motor doesn't strictly need it
# but to use motor, we might need to find the correct python env. Let's just use the python in env
sys.path.append('d:/projects/airport-marketplace/Services/HyperLocal_Services/Order_Service')

from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['OrdersDb']
    col = db['orders_collection']
    
    sample_order = await col.find_one({"shop_id": "TEST-SHOP", "$or": [{"customer.customer_id": "c8a1d28e-5f09-5951-bfea-fbf43ca65a45"}, {"customer_id": "c8a1d28e-5f09-5951-bfea-fbf43ca65a45"}]})
    print("ORDER: ", sample_order)

asyncio.run(main())
