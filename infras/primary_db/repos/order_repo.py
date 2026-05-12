from models.repo_models.base_repo_model import BaseRepoModel
from sqlalchemy.dialects.postgresql import Insert,JSONB
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema
from schemas.v1.request_scheams.order_schema import DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,ReturnOrderSchema
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from ..models.order_model import Orders,OrderItems,ExchangedOrderItems
from sqlalchemy import select,update,delete,func,or_,and_,String
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from icecream import ic
from ..main import AsyncOrdersLocalSession
from typing import Optional,List
original_item = aliased(OrderItems)
replacement_order = aliased(Orders)
replacement_order_item = aliased(OrderItems)

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
                    "status",OrderItems.status,
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




exchanged_items_subq = (
    select(
        ExchangedOrderItems.parent_order_id,

        func.coalesce(
            func.jsonb_agg(
                func.jsonb_build_object(

                    # --------------------------------
                    # EXCHANGE ENTRY ID
                    # --------------------------------

                    "exchange_id",
                    ExchangedOrderItems.id,

                    # --------------------------------
                    # ORIGINAL EXCHANGED ITEM ID
                    # --------------------------------

                    "exchanged_item_id",
                    ExchangedOrderItems.item_id,

                    # --------------------------------
                    # REPLACEMENT ORDER
                    # --------------------------------

                    "replacement_order",

                    func.jsonb_build_object(
                        "id", replacement_order.id,
                        "ui_id", replacement_order.ui_id,
                        "shop_id", replacement_order.shop_id,
                        "origin", replacement_order.origin,
                        "status", replacement_order.status,
                        "payment_method", replacement_order.payment_method,
                        "customer_id", replacement_order.customer_id,
                        "total_buyprice", replacement_order.total_buyprice,
                        "total_sellprice", replacement_order.total_sellprice,
                        "total_quantity", replacement_order.total_quantity,
                        "type", replacement_order.type,
                        "created_at", replacement_order.created_at,
                        "updated_at", replacement_order.updated_at,

                        # --------------------------------
                        # REPLACEMENT ORDER ITEMS
                        # --------------------------------

                        "items",

                        (
                            select(
                                func.coalesce(
                                    func.jsonb_agg(
                                        func.jsonb_build_object(
                                            "id", replacement_order_item.id,
                                            "inventory_id", replacement_order_item.inventory_id,
                                            "variant_id", replacement_order_item.variant_id,
                                            "batch_id", replacement_order_item.batch_id,
                                            "serialno_id", replacement_order_item.serialno_id,
                                            "barcode", replacement_order_item.barcode,
                                            "buy_price", replacement_order_item.buy_price,
                                            "sell_price", replacement_order_item.sell_price,
                                            "quantity", replacement_order_item.quantity,
                                            "gst", replacement_order_item.gst,
                                            "status", replacement_order_item.status,
                                            "serial_numbers", replacement_order_item.serial_numbers,
                                            "created_at", replacement_order_item.created_at
                                        )
                                    ).filter(
                                        replacement_order_item.id.isnot(None)
                                    ),

                                    func.cast("[]", JSONB)
                                )
                            )
                            .where(
                                replacement_order_item.order_id
                                == replacement_order.id
                            )
                            .scalar_subquery()
                        )
                    )

                )
            ).filter(
                ExchangedOrderItems.id.isnot(None)
            ),

            func.cast("[]", JSONB)
        ).label("exchanged_items")
    )

    .outerjoin(
        replacement_order,
        replacement_order.id
        == ExchangedOrderItems.replacement_order_id
    )

    .group_by(
        ExchangedOrderItems.parent_order_id
    )

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
            Orders.type,
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
    async def update(self,data:UpdateOrderDbSchema):
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
    async def update_order_item(self,data:UpdateOrderItemDbSchema):
        """THis only updates the status"""
        data_toupdate=data.model_dump(mode='json',exclude=['id','shop_id'],exclude_none=True,exclude_unset=True)
        if not data_toupdate or len(data_toupdate)<1:
            return True
        
        order_sts_toupdate=update(
            OrderItems
        ).where(
            OrderItems.id==data.id,
            OrderItems.order_id==data.order_id
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

        order_stmt = (
            select(
                *self.order_cols,

                items_subq.c["items"].label("items"),
                exchanged_items_subq.c["exchanged_items"].label("exchanged_items")
            )
            .outerjoin(
                items_subq,
                items_subq.c.order_id == Orders.id
            )
            .outerjoin(
                    exchanged_items_subq,
                    exchanged_items_subq.c.parent_order_id == Orders.id
                )
            .where(
                
                Orders.type!="EXCHANGE",
                or_(
                    Orders.id.ilike(search_term),
                    func.cast(Orders.created_at, String).ilike(search_term),
                    Orders.origin.ilike(search_term),
                    Orders.status.ilike(search_term),
                    Orders.shop_id.ilike(search_term),
                ),
            )
            .offset(cursor)
            .limit(data.limit)
        )
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

        order_stmt=(
            select(
                *self.order_cols,

                items_subq.c["items"].label("items"),
                exchanged_items_subq.c["exchanged_items"].label("exchanged_items")
            )
            .outerjoin(
                items_subq,
                items_subq.c.order_id == Orders.id
            )
            .outerjoin(
                    exchanged_items_subq,
                    exchanged_items_subq.c.parent_order_id == Orders.id
            )
            .where(
                Orders.shop_id==data.shop_id,
                Orders.type!="EXCHANGE",
                or_(
                    Orders.id.ilike(search_term),
                    func.cast(Orders.created_at,String).ilike(search_term),
                    Orders.origin.ilike(search_term),
                    Orders.status.ilike(search_term),
                    Orders.shop_id.ilike(search_term)
                ),
            )
            .offset(offset=cursor).limit(data.limit))

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders

    async def getby_id(self,data:GetOrderByIdSchema)-> dict | None:
        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))
        order_stmt=(
            select(
                *self.order_cols,

                items_subq.c["items"].label("items"),
                exchanged_items_subq.c["exchanged_items"].label("exchanged_items")
            )
            .outerjoin(
                items_subq,
                items_subq.c.order_id == Orders.id
            )
            .outerjoin(
                    exchanged_items_subq,
                    exchanged_items_subq.c.parent_order_id == Orders.id
            )
            .where(
                Orders.type!="EXCHANGE",
                Orders.shop_id==data.shop_id,
                Orders.id==data.id
            )
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


        
        