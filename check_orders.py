import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import json

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    orders_col = client['OrdersDb']['orders_collection']
    orders = await orders_col.find({}).to_list(100)
    for order in orders:
        items = order.get('items', [])
        for item in items:
            print(f"Order {order['_id']}: {item.get('name')} (Inv: {item.get('inventory_id')})")
            print(f"Datas: {item.get('datas')}")

asyncio.run(main())
