from typing import List, Optional
import json
from ..main import RedisRepo,redis_client
from icecream import ic

class OrderCartCacheModel:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cache_key = f"ORDER-CART:{session_id}"

    async def get_cart(self) -> Optional[List[dict]]:
        data = await RedisRepo.get(key=self.cache_key)
        ic(data)
        return data

    async def set_cart(self, items: List[dict], ttl: int = 180) -> bool:
        return await RedisRepo.set(key=self.cache_key, value=items, expire=ttl)

    async def add_or_update_item(self, item: dict, ttl: int = 180) -> bool:
        cart = await self.get_cart() or []
        
        # Check if item exists (by product_id, variant_id, batch_id)
        found = False
        for i in range(len(cart)):
            if cart[i].get('product_id') == item.get('product_id') and \
               cart[i].get('variant_id') == item.get('variant_id') and \
               cart[i].get('batch_id') == item.get('batch_id'):
                # Update quantity
                cart[i]['qty'] = item.get('qty', 0)
                cart[i]['serialno_infos']=item.get("serialno_infos",[])
                found = True
                break
                
        if not found:
            cart.append(item)
            
        return await self.set_cart(items=cart, ttl=ttl)
    
    async def remove_item(self, product_id: str, variant_id: Optional[str], batch_id: Optional[str], ttl: int) -> Optional[dict]:
        cart_data = await self.get_cart()
        ic(cart_data)
        if not cart_data:
            return None
            
        items = cart_data
        removed_item = None
        
        for i, existing_item in enumerate(items):
            if existing_item.get("product_id") == product_id and \
                existing_item.get("variant_id") == variant_id and \
                existing_item.get("batch_id") == batch_id:
                removed_item = items.pop(i)
                break
                
        cart_data=items
        await self.set_cart(items=cart_data, ttl=ttl)
        return removed_item

    async def delete_cart(self) -> bool:
        return await RedisRepo.unlink(keys=[self.cache_key])
