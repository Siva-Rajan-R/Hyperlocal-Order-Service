import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['CustomersDb']
    col = db['customers_collection']
    
    doc = await col.find_one({"id": "c8a1d26e-5f09-5951-bfea-fbf43ca65a45"})
    print("CUSTOMER DOC: ", doc)

asyncio.run(main())
