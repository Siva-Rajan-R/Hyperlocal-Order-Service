import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    orders_col = client['OrdersDb']['orders_collection']
    orders = await orders_col.find({}).to_list(100)
    for order in orders:
        updated = False
        items = order.get('items', [])
        for item in items:
            if item.get('datas', {}).get('supplier', '') in ('', None):
                item.setdefault('datas', {})['supplier'] = '9482fecc-1763-58c6-9fea-ba610cbdb615'
                updated = True
        
        if updated:
            await orders_col.update_one({'_id': order['_id']}, {'$set': {'items': items}})
            print(f'Updated order {order.get("_id")}')
            
    # Also clear ORDER_STATS_COLLECTION to force rebuild
    await client['OrdersDb']['order_stats_collection'].delete_many({})
    print("Cleared order stats.")

asyncio.run(main())
