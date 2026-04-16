from ..main import ORDERS_COLLECTION
from motor.motor_asyncio import AsyncIOMotorCollection

from typing import Optional


class ReadDbBaseRepo:
    def __init__(self,collection:AsyncIOMotorCollection):
        self.collection=collection
        
    async def create(self,data:dict):
        res=await self.collection.insert_one(data)
        return res
    
    async def update(self,data:dict,conditions:dict):
        payload=data
        if not payload:
            return False
        
        is_updated=await self.collection.update_one(
            conditions,
            {"$set":payload}
        )

        if is_updated.matched_count==0:
            return False
        
        return True
    
    async def delete(self,conditions:dict):
        if len(conditions)<=0:
            return False
        
        is_deleted=await self.collection.delete_one(
            conditions
        )

        if is_deleted.deleted_count==0:
            return False
        
        return True
    
    async def get(
        self,
        queries: dict,
        offset: Optional[int] = None,
        limit: Optional[int] = None
    ):
        cursor = self.collection.find(queries,{'_id':0})

        if offset is not None and limit is None:
            raise ValueError("offset cannot be used without limit")

        if offset is not None and limit is not None:
            if offset < 1:
                offset = 1

            skip = (offset - 1) * limit
            cursor = cursor.skip(skip).limit(limit)

        elif limit is not None:
            cursor = cursor.limit(limit)

        # fetch
        results = await cursor.to_list()
        return results
        
    async def get_one(self,queries:dict):
        cursor=(await self.collection.find_one(queries,{'_id':0}))

        result=cursor

        return result