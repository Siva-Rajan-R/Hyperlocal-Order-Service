import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    
    # 1. Fetch Purchases
    purchase_db = client['PurchaseDb']
    purchases = await purchase_db['purchase_collection'].find({}).to_list(100)
    
    # 2. Extract inventory_id -> supplier_id
    inv_to_supplier = {}
    for p in purchases:
        supplier_id = p.get('supplier_id')
        for prod in p.get('products', []):
            inv_to_supplier[prod.get('inventory_id')] = supplier_id
            
    print(f'Mapping: {inv_to_supplier}')
    
    # 3. Update orders
    orders_col = client['OrdersDb']['orders_collection']
    orders = await orders_col.find({}).to_list(100)
    for order in orders:
        updated = False
        items = order.get('items', [])
        for item in items:
            inv_id = item.get('inventory_id')
            if inv_id in inv_to_supplier and item.get('datas', {}).get('supplier', '') in ('', None):
                item.setdefault('datas', {})['supplier'] = inv_to_supplier[inv_id]
                updated = True
        
        if updated:
            await orders_col.update_one({'_id': order['_id']}, {'$set': {'items': items}})
            print(f'Updated order {order.get("_id")}')
            
    # Also update ORDER_STATS_COLLECTION (maybe just clear it to force rebuild)
    await client['OrdersDb']['order_stats_collection'].delete_many({})

asyncio.run(main())
