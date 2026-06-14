import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['OrdersDb']
    col = db['orders_collection']
    
    cursor = col.find({"shop_id": "TEST-SHOP"}).sort("created_at", -1).limit(10)
    orders = await cursor.to_list(10)
    for o in orders:
        print(f"Order {o.get('ui_id')} - customer_id: {o.get('customer_id')} - customer: {o.get('customer')} - total: {o.get('total_sellprice')} - payments: {o.get('payments')}")

asyncio.run(main())
