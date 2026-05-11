from models.repo_models.base_repo_model import BaseRepoModel
from sqlalchemy.dialects.postgresql import Insert,JSONB
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema
from schemas.v1.request_scheams.order_schema import DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from ..models.order_model import Orders,OrderItems
from sqlalchemy import select,update,delete,func,or_,and_,String
from sqlalchemy.ext.asyncio import AsyncSession
from icecream import ic
from ..main import AsyncOrdersLocalSession
from typing import Optional,List


items_subq = (
    select(
        OrderItems.order_id,

        func.coalesce(
            func.jsonb_agg(
                func.jsonb_build_object(
                    "id", OrderItems.id,
                    "inventory_id", OrderItems.inventory_id,
                    "variant_id", OrderItems.variant_id,
                    "batch_id", OrderItems.batch_id,
                    "serialno_id", OrderItems.serialno_id,
                    "barcode", OrderItems.barcode,
                    "buy_price", OrderItems.buy_price,
                    "sell_price", OrderItems.sell_price,
                    "quantity", OrderItems.quantity,
                    "gst", OrderItems.gst,
                    "serial_numbers", OrderItems.serial_numbers,
                    "created_at", OrderItems.created_at
                )
            ).filter(OrderItems.id.isnot(None)),

            func.cast("[]", JSONB)
        ).label("items")
    )
    .group_by(OrderItems.order_id)
    .subquery()
)
class OrdersRepo(BaseRepoModel):
    
    def __init__(self, session:AsyncSession):
        self.order_cols=(
            Orders.id,
            Orders.sequence_id,
            Orders.shop_id,
            Orders.ui_id,
            Orders.origin,
            Orders.status,
            Orders.payment_method,
            Orders.customer_id,
            Orders.total_buyprice,
            Orders.total_sellprice,
            Orders.total_quantity,
            Orders.created_at,
            Orders.updated_at,
            
        )
        super().__init__(session)


        
    @start_db_transaction
    async def create(self,data:CreateOrderDbSchema)-> dict | None:
        stmt=(
            Insert(
                Orders
            )
            .values(**data.model_dump(mode='json'))
            .returning(*self.order_cols)
        )
        res=(await self.session.execute(stmt)).mappings().one_or_none()
        return res
    
    @start_db_transaction
    async def create_items(self,data:OrderItemsDbSchema)->dict | None:
        stmt=(
            Insert(
                OrderItems
            )
            .values(**data.model_dump(mode='json'))
            .returning(*self.order_cols)
        )
        res=(await self.session.execute(stmt)).mappings().one_or_none()
        return res
    
    @start_db_transaction
    async def create_bulk(self,datas: List[Orders])->bool:
        self.session.add_all(datas)
        return True
    
    @start_db_transaction
    async def create_bulk_items(self,datas: List[OrderItems])-> bool:
        self.session.add_all(datas)
        return True
    
    @start_db_transaction
    async def update(self,data:CreateOrderDbSchema):
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
    async def delete(self,data:DeleteOrderSchema)-> dict:
        order_todel=(
            delete(Orders)
            .where(Orders.id==data.id,Orders.shop_id==data.shop_id)
            .returning(*self.order_cols)
        )

        is_deleted=(await self.session.execute(order_todel)).mappings().one_or_none()

        return is_deleted
    
    async def get(self,data:GetAllOrderSchema)-> List[dict] | list:

        offset=data.offset
        if offset<=0:
            offset=1
        cursor=(offset-1)*data.limit
        search_term=f"%{data.query}%"

        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))

        order_stmt=select(
            *self.order_cols,
            items_subq.c['items']
        ).outerjoin(
            items_subq,
            items_subq.c.order_id == Orders.id
        ).where(
            or_(
                Orders.id.ilike(search_term),
                func.cast(Orders.created_at,String).ilike(search_term),
                Orders.origin.ilike(search_term),
                Orders.status.ilike(search_term),
                Orders.shop_id.ilike(search_term)
            ),
        ).offset(offset=cursor).limit(data.limit)

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders
    

    async def getby_shop_id(self,data:GetOrderByShopIdSchema)-> List[dict] | list:
        offset=data.offset
        if offset<=0:
            offset=1
        cursor=(offset-1)*data.limit
        search_term=f"%{data.query}%"
        ic(data.shop_id)
        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))

        order_stmt=select(
            *self.order_cols,
            items_subq.c['items']
        ).outerjoin(
            items_subq,
            items_subq.c.order_id == Orders.id,
        ).where(
            Orders.shop_id==data.shop_id,
            or_(
                Orders.id.ilike(search_term),
                func.cast(Orders.created_at,String).ilike(search_term),
                Orders.origin.ilike(search_term),
                Orders.status.ilike(search_term),
                Orders.shop_id.ilike(search_term)
            ),
        ).offset(offset=cursor).limit(data.limit)

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders

    async def getby_id(self,data:GetOrderByIdSchema)-> dict | None:
        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))
        order_stmt=select(
            *self.order_cols,
            items_subq.c['items']
        ).outerjoin(
            items_subq,
            items_subq.c.order_id == Orders.id
        ).where(
            Orders.shop_id==data.shop_id,
            Orders.id==data.id
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


        
        