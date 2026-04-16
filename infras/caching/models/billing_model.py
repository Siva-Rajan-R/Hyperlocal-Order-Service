from ..main import redis_client,RedisRepo
from typing import Optional,Dict
from schemas.v1.caching_schemas.billing_schema import CachingBillingSchema

class BillingCacheModel:
    def __init__(self,shop_id:str,cur_user_id:str):
        self.shop_id=shop_id
        self.cur_user_id=cur_user_id
        self.cache_key=f"BILLING-CREATE-{shop_id}-{cur_user_id}"       
    
    async def get_billing_cache(self)->Dict[str,CachingBillingSchema]:
        return await RedisRepo.get(key=self.cache_key)
    
    async def delete_billing_cache(self):
        return await RedisRepo.unlink(keys=[self.cache_key])
    

