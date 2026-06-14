import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['CustomersDb']
    col = db['customers_collection']
    
    docs = await col.find({"shop_id": "TEST-SHOP"}).to_list(10)
    for d in docs:
        print(d.get('id'), d.get('name'))

asyncio.run(main())
