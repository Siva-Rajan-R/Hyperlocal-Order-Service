import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    import sys
    sys.path.append('d:/projects/airport-marketplace/Services/HyperLocal_Services/Order_Service')
    
    from infras.read_db.repos.order_stats_repo import CustomerStatsReadDbRepo
    
    stats = await CustomerStatsReadDbRepo.update_customer_stats("TEST-SHOP", "c8a1d26e-5f09-5951-bfea-fbf43ca65a45")
    print("UPDATED STATS: ", stats)

asyncio.run(main())
