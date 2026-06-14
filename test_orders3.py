import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['OrdersDb']
    col = db['orders_collection']
    
    cursor = col.find({"shop_id": "TEST-SHOP", "customer_id": "c8a1d26e-5f09-5951-bfea-fbf43ca65a45"})
    orders = await cursor.to_list(100)
    for o in orders:
        print(f"total: {o.get('total_sellprice')} - datas: {o.get('datas')}")

asyncio.run(main())
