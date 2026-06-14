import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['OrdersDb']
    col = db['customer_stats_collection']
    
    docs = await col.find().to_list(100)
    for d in docs:
        print(d)

asyncio.run(main())
