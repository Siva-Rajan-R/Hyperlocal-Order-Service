from models.repo_models.base_repo_model import BaseRepoModel
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,UpdateOrderStatusDbSchema
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from ..models.order_model import Orders
from sqlalchemy import select,update,delete,func,or_,and_,String
from sqlalchemy.ext.asyncio import AsyncSession
from icecream import ic
from ..main import AsyncOrdersLocalSession
from typing import Optional,List


class OrdersRepo(BaseRepoModel):
    def __init__(self, session:AsyncSession):
        self.order_cols=(
            Orders.id,
            Orders.orders,
            Orders.created_at,
            Orders.origin,
            Orders.status,
            Orders.customer_name,
            Orders.customer_number,
            Orders.total_price,
            Orders.order_by,
            Orders.shop_id
        )
        super().__init__(session)


        
    @start_db_transaction
    async def create(self,data:CreateOrderDbSchema):
        self.session.add(Orders(**data.model_dump(mode='json')))
        return True
    
    @start_db_transaction
    async def update(self,data:UpdateOrderStatusDbSchema):
        """THis only updates the status"""
        data_toupdate=data.model_dump(mode='json',exclude=['id','shop_id'],exclude_none=True,exclude_unset=True)
        if not data_toupdate or len(data_toupdate)<1:
            return True
        
        order_sts_toupdate=update(
            Orders
        ).where(
            Orders.id==data.id,
            Orders.shop_id==data.shop_id
        ).values(
            **data_toupdate
        )

        is_updated=(await self.session.execute(order_sts_toupdate))
        return is_updated


    @start_db_transaction
    async def delete(self,order_id:str,shop_id:str):
        order_todel=(
            delete(Orders)
            .where(Orders.id==order_id,Orders.shop_id==shop_id)
            .returning(Orders.id)
        )

        is_deleted=(await self.session.execute(order_todel)).scalar_one_or_none()

        return is_deleted
    
    async def get(self,limit:int,offset:int,shop_id:str,timezone:TimeZoneEnum,query:str=""):
        if offset<=0:
            offset=1
        cursor=(offset-1)*limit
        search_term=f"%{query}%"

        created_at=func.date(func.timezone(timezone.value,Orders.created_at))

        order_stmt=select(
            *self.order_cols,
            created_at
        ).where(
            Orders.shop_id==shop_id,
            or_(
                Orders.id.ilike(search_term),
                func.cast(Orders.created_at,String).ilike(search_term),
                Orders.origin.ilike(search_term),
                Orders.status.ilike(search_term),
                Orders.customer_name.ilike(search_term),
                Orders.customer_number.ilike(search_term),
                Orders.order_by.ilike(search_term),
                Orders.shop_id.ilike(search_term)
            ),
            Orders.sequence_id>cursor
        ).limit(limit)

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders

    async def getby_id(self,shop_id:str,order_id:str,timezone:TimeZoneEnum):
        created_at=func.date(func.timezone(timezone.value,Orders.created_at))
        order_stmt=select(
            *self.order_cols,
            created_at
        ).where(
            Orders.shop_id==shop_id,
            Orders.id==order_id
        )

        order=(await self.session.execute(order_stmt)).mappings().one_or_none()

        return order
    

    async def search(self,shop_id:str,query:str, limit = 5, *args, **kwargs):
        search_term=f"%{query}%"

        order_stmt=select(
            *self.order_cols,
        ).where(
            Orders.shop_id==shop_id,
            or_(
                Orders.id.ilike(search_term),
                func.cast(Orders.created_at,String).ilike(search_term),
                Orders.origin.ilike(search_term),
                Orders.status.ilike(search_term),
                Orders.customer_name.ilike(search_term),
                Orders.customer_number.ilike(search_term),
                Orders.order_by.ilike(search_term),
                Orders.shop_id.ilike(search_term)
            )
        ).limit(limit)

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders


        
        