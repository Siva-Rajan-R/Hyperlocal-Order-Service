    from models.repo_models.base_repo_model import BaseRepoModel
from sqlalchemy.dialects.postgresql import Insert,JSONB
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema,OrderItemsDbSchema,UpdateOrderDbSchema,UpdateOrderItemDbSchema
from schemas.v1.request_scheams.order_schema import DeleteOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,GetOrderByCustomerIdSchema
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from ..models.order_model import Orders,OrderItems,Exchanges,ReturnItems,Returns,ExchangeItems
from sqlalchemy import select,update,delete,func,or_,and_,String,bindparam,case,text
from datetime import datetime, timezone
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import aliased,selectinload
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
                    "product_id", OrderItems.product_id,
                    "variant_id", OrderItems.variant_id,
                    "batch_id", OrderItems.batch_id,
                    "buy_price", OrderItems.buy_price,
                    "sell_price", OrderItems.sell_price,
                    "quantity", OrderItems.quantity,
                    "entered_qty", OrderItems.entered_qty,
                    "entered_unit", OrderItems.entered_unit,
                    "gst", OrderItems.gst,
                    "additional_infos",OrderItems.additional_infos,
                    "created_at", OrderItems.created_at
                )
            ).filter(OrderItems.id.isnot(None)),

            func.cast("[]", JSONB)
        ).label("items")
    )
    .group_by(OrderItems.order_id)
    .subquery()
)


exchange_group_subq = (
    select(
        Exchanges.original_order_id.label('parent_order_id'),
        Exchanges.replacement_order_id,

        func.jsonb_build_object(
            "id", replacement_order.id,
            "ui_id", replacement_order.ui_id,
            "shop_id", replacement_order.shop_id,
            "origin", replacement_order.origin,
            "status", replacement_order.status,
            
            "customer_id", replacement_order.customer_id,
            "payments", replacement_order.payment_infos,
            "created_at", replacement_order.created_at,
            "updated_at", replacement_order.updated_at,

            "items",
            (
                select(
                    func.coalesce(
                        func.jsonb_agg(
                            func.jsonb_build_object(
                                "id", replacement_order_item.id,
                                "product_id", replacement_order_item.product_id,
                                "variant_id", replacement_order_item.variant_id,
                                "batch_id", replacement_order_item.batch_id,
                                "serialno_infos", replacement_order_item.serialno_infos,
                                "buy_price", replacement_order_item.buy_price,
                                "sell_price", replacement_order_item.sell_price,
                                "quantity", replacement_order_item.quantity,
                                "gst", replacement_order_item.gst,
                                "additional_infos", replacement_order_item.additional_infos,
                                "created_at", replacement_order_item.created_at,
                                "quantity",replacement_order_item.quantity
                            )
                        ),
                        func.cast("[]", JSONB)
                    )
                )
                .where(
                    replacement_order_item.order_id == replacement_order.id
                )
                .scalar_subquery()
            )
        ).label("replacement_order")

    )
    .outerjoin(
        replacement_order,
        replacement_order.id == Exchanges.replacement_order_id
    )
    .group_by(
        Exchanges.original_order_id,
        Exchanges.replacement_order_id,

        replacement_order.id,
        replacement_order.ui_id,
        replacement_order.shop_id,
        replacement_order.origin,
        replacement_order.status,
        replacement_order.customer_id,
        replacement_order.created_at,
        replacement_order.updated_at,
    )
).subquery()



exchanged_items_subq = (
    select(
        exchange_group_subq.c.parent_order_id,

        func.coalesce(
            func.jsonb_agg(
                func.jsonb_build_object(
                    "replacement_order",
                    exchange_group_subq.c.replacement_order
                )
            ),
            func.cast("[]", JSONB)
        ).label("exchanged_items")

    )
    .group_by(exchange_group_subq.c.parent_order_id)
).subquery()

class OrdersRepo(BaseRepoModel):
    
    def __init__(self, session:AsyncSession):
        self.order_cols=(
            Orders.id,
            Orders.sequence_id,
            Orders.shop_id,
            Orders.ui_id,
            Orders.origin,
            Orders.status,
            Orders.customer_id,
            Orders.calculation_infos,
            Orders.charges_infos,
            Orders.item_infos,
            Orders.payment_infos,
            Orders.date,
            Orders.additional_infos,
            Orders.created_at,
            Orders.updated_at,
            
        )
        super().__init__(session)

    def _build_filter_conds(self, data):
        from ..models.order_model import OnlineOrderModel
        import pytz

        conds = []
        if hasattr(data, 'shop_id') and getattr(data, 'shop_id'):
            conds.append(Orders.shop_id == data.shop_id)
        if hasattr(data, 'customer_id') and getattr(data, 'customer_id'):
            conds.append(Orders.customer_id == data.customer_id)
        if hasattr(data, 'status') and getattr(data, 'status'):
            status_val = str(data.status).strip().lower()
            if status_val in ["complete", "completed"]:
                conds.append(func.lower(Orders.status).in_(["completed", "complete"]))
            elif status_val in ["pending", "prning"]:
                conds.append(func.lower(Orders.status).in_(["pending", "prning"]))
            elif status_val in ["cancelled", "canceled", "cnacedeld"]:
                conds.append(func.lower(Orders.status).in_(["cancelled", "canceled", "cnacedeld"]))
            elif status_val in ["online", "offline"]:
                if status_val == "online":
                    conds.append(or_(func.lower(Orders.origin) == "online", Orders.id.in_(select(OnlineOrderModel.order_id))))
                else:
                    conds.append(func.lower(Orders.origin) == "offline")
            else:
                conds.append(func.lower(Orders.status) == status_val)
        if hasattr(data, 'origin') and getattr(data, 'origin'):
            origin_val = str(data.origin).strip().lower()
            if origin_val == "online":
                conds.append(or_(func.lower(Orders.origin) == "online", Orders.id.in_(select(OnlineOrderModel.order_id))))
            else:
                conds.append(func.lower(Orders.origin) == origin_val)
        if hasattr(data, 'payment_method') and getattr(data, 'payment_method'):
            conds.append(func.cast(Orders.payment_infos, String).ilike(f"%{data.payment_method.upper()}%"))

        # Timezone-aware date range filtering
        tz_str = "Asia/Kolkata"
        if hasattr(data, 'timezone') and getattr(data, 'timezone'):
            tz_val = getattr(data, 'timezone')
            tz_str = tz_val.value if hasattr(tz_val, 'value') else str(tz_val)
        try:
            user_tz = pytz.timezone(tz_str)
        except Exception:
            user_tz = pytz.timezone('Asia/Kolkata')

        if hasattr(data, 'from_date') and getattr(data, 'from_date'):
            from_str = str(getattr(data, 'from_date')).strip()
            if len(from_str) <= 10:
                from_str += ' 00:00:00'
            try:
                from_dt_naive = datetime.strptime(from_str[:19], "%Y-%m-%d %H:%M:%S")
                from_dt_loc = user_tz.localize(from_dt_naive)
                from_dt_utc = from_dt_loc.astimezone(timezone.utc)
                conds.append(or_(Orders.created_at >= from_dt_utc, Orders.date >= from_dt_utc))
            except Exception as ex:
                ic(f"Error parsing from_date: {ex}")

        if hasattr(data, 'to_date') and getattr(data, 'to_date'):
            to_str = str(getattr(data, 'to_date')).strip()
            if len(to_str) <= 10:
                to_str += ' 23:59:59'
            try:
                to_dt_naive = datetime.strptime(to_str[:19], "%Y-%m-%d %H:%M:%S")
                to_dt_loc = user_tz.localize(to_dt_naive)
                to_dt_utc = to_dt_loc.astimezone(timezone.utc)
                conds.append(or_(Orders.created_at <= to_dt_utc, Orders.date <= to_dt_utc))
            except Exception as ex:
                ic(f"Error parsing to_date: {ex}")

        if hasattr(data, 'online_only') and getattr(data, 'online_only') is not None:
            if data.online_only:
                conds.append(or_(func.lower(Orders.origin) == "online", Orders.id.in_(select(OnlineOrderModel.order_id))))
            else:
                conds.append(and_(func.lower(Orders.origin) != "online", Orders.id.not_in(select(OnlineOrderModel.order_id))))
        if hasattr(data, 'payment_status') and getattr(data, 'payment_status'):
            from sqlalchemy import Float
            total_paid_object = select(func.coalesce(func.sum(func.cast(text("value"), Float)), 0.0)).select_from(func.jsonb_each(Orders.payment_infos)).scalar_subquery()
            total_paid_array = select(func.coalesce(func.sum(func.cast(text("value->>'amount'"), Float)), 0.0)).select_from(func.jsonb_array_elements(Orders.payment_infos)).scalar_subquery()
            total_paid = case(
                (func.jsonb_typeof(Orders.payment_infos) == 'array', total_paid_array),
                else_=total_paid_object
            )
            total_cost = func.coalesce(
                func.cast(Orders.calculation_infos['total_sellprice'].astext, Float),
                func.cast(Orders.item_infos['total_order_amount'].astext, Float),
                0.0
            )
            p_status = data.payment_status.lower().replace("_", " ").strip()
            if p_status == "paid":
                conds.append(total_paid >= total_cost)
            elif p_status in ["not paid", "unpaid"]:
                conds.append(total_paid == 0.0)
            elif p_status in ["partially paid", "partialy paid", "partially_paid", "partialy_paid"]:
                conds.append(and_(total_paid > 0.0, total_paid < total_cost))
        if hasattr(data, 'query') and getattr(data, 'query'):
            search_term = f"%{data.query}%"
            conds.append(
                or_(
                    Orders.id.ilike(search_term),
                    Orders.ui_id.ilike(search_term),
                    func.cast(Orders.created_at, String).ilike(search_term),
                    Orders.origin.ilike(search_term),
                    Orders.status.ilike(search_term),
                    Orders.shop_id.ilike(search_term)
                )
            )
        return conds


    async def get_next_sequence(self, shop_id: str, start_from: int = 1) -> int:
        seq_name = f"seq_order_{shop_id.replace('-', '_').lower()}"
        await self.session.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START WITH {start_from}"))
        res = await self.session.execute(text(f"SELECT nextval('{seq_name}')"))
        return res.scalar_one()


    @start_db_transaction
    async def create(self,data:CreateOrderDbSchema)-> dict | None:
        stmt=(
            Insert(
                Orders
            )
            .values(**data.model_dump())
            .returning(*self.order_cols)
        )
        res=(await self.session.execute(stmt)).mappings().one_or_none()
        # self.session.commit()
        return res

    @start_db_transaction
    async def create_online_order(self, order_id: str, user_id: str, user_address_id: str):
        from infras.primary_db.models.order_model import OnlineOrderModel
        online_order = OnlineOrderModel(
            order_id=order_id,
            user_id=user_id,
            user_address_id=user_address_id
        )
        self.session.add(online_order)
        await self.session.flush()
        return online_order
    
    @start_db_transaction
    async def create_items(self,data:OrderItemsDbSchema)->dict | None:
        stmt=(
            Insert(
                OrderItems
            )
            .values(**data.model_dump())
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
        
        if "payment_infos" in data_toupdate:
            if isinstance(data_toupdate["payment_infos"], dict):
                data_toupdate["payment_infos"] = [data_toupdate["payment_infos"]]
        
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
        ).returning(OrderItems.id)

        is_updated=(await self.session.execute(order_sts_toupdate)).scalar_one_or_none()
        return is_updated
    

    @start_db_transaction
    async def update_order_item_bulk_adv(self,data:List[dict]):
        ic(data)
        if not data:
            return []
        ic("jumped")
        stmt = (
            update(OrderItems.__table__)
            .where(
                OrderItems.order_id == bindparam('b_order_id'),
                OrderItems.id==bindparam("b_item_id")
            )
            .values(
                status=bindparam("b_status"),
                reason=bindparam("b_reason"),
                returned_quantity=bindparam("b_returned_quantity")
            )
            .execution_options(synchronize_session=False)
        )

        res = await self.session.execute(stmt,data)
        ic(res)
        ic(res.rowcount)
        return res


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

        stmt = (
            select(Orders)
            .options(
                # Order Items
                selectinload(Orders.items).selectinload(OrderItems.return_items),
                selectinload(Orders.items).selectinload(OrderItems.exchange_items),

                # Returns
                selectinload(Orders.returns).selectinload(Returns.items),

                # Exchanges
                selectinload(Orders.exchanges).selectinload(Exchanges.items),
            )
            .where(*self._build_filter_conds(data))
            .offset(cursor)
            .limit(data.limit)
        )

        result = await self.session.execute(stmt)
        orders = result.scalars().all()

        if not orders:
            return []
        responses = []
        for order in orders:
            response = {
                "id": order.id,
                "sequence_id": order.sequence_id,
                "ui_id": order.ui_id,
                "shop_id": order.shop_id,
                "customer_id": order.customer_id,
                "status": order.status,
                "origin": order.origin,
                "calculation_infos": order.calculation_infos,
                "charges_infos": order.charges_infos,
                "payment_infos": order.payment_infos,
                "date": order.date,
                "additional_infos": order.additional_infos,
                "created_at": order.created_at,
                "updated_at": order.updated_at,

                "items": [],
                "returns": [],
                "exchanges": []
            }

            # -------------------------
            # Order Items
            # -------------------------
            for item in order.items:
                response["items"].append({
                    "id": item.id,
                    "product_id": item.product_id,
                    "variant_id": item.variant_id,
                    "batch_id": item.batch_id,
                    "serialno_infos": item.serialno_infos,
                    "gst": item.gst,
                    "quantity": item.quantity,
                    "buy_price": item.buy_price,
                    "sell_price": item.sell_price,
                    "additional_infos": item.additional_infos,

                    "returned_quantity": sum(
                        ri.quantity
                        for ri in item.return_items
                    ),

                    "exchanged_quantity": sum(
                        ei.quantity
                        for ei in item.exchange_items
                    ),

                    "returns": [
                        {
                            "id": ri.id,
                            "return_id": ri.return_id,
                            "quantity": ri.quantity,
                            "refund_amount": ri.refund_amount,
                            "reason": ri.reason,
                            "created_at": ri.created_at
                        }
                        for ri in item.return_items
                    ],

                    "exchanges": [
                        {
                            "id": ei.id,
                            "exchange_id": ei.exchange_id,
                            "quantity": ei.quantity,
                            "exchange_amount": ei.exchange_amount,
                            "reason": ei.reason,
                            "created_at": ei.created_at
                        }
                        for ei in item.exchange_items
                    ]
                })

            # -------------------------
            # Returns
            # -------------------------
            for ret in order.returns:
                response["returns"].append({
                    "id": ret.id,
                    "sequence_id": ret.sequence_id,
                    "status": ret.status,
                    "total_refund_amount": ret.total_refund_amount,
                    "total_refund_qty": ret.total_refund_qty,
                    "payment_infos": ret.payment_infos,
                    "created_at": ret.created_at,
                    "updated_at": ret.updated_at,

                    "items": [
                        {
                            "id": item.id,
                            "order_item_id": item.order_item_id,
                            "product_id": item.product_id,
                            "quantity": item.quantity,
                            "refund_amount": item.refund_amount,
                            "reason": item.reason,
                        }
                        for item in ret.items
                    ]
                })

            # -------------------------
            # Exchanges
            # -------------------------
            for exch in order.exchanges:
                response["exchanges"].append({
                    "id": exch.id,
                    "sequence_id": exch.sequence_id,
                    "status": exch.status,
                    "payment_status": exch.payment_status,
                    "reason": exch.reason,

                    "replacement_order_id": exch.replacement_order_id,

                    "total_exchanged_amount": exch.total_exchanged_amount,
                    "total_exchanged_qty": exch.total_exchanged_qty,

                    "total_replacement_amount": exch.total_replacement_amount,
                    "total_replacement_qty": exch.total_replacement_qty,

                    "payment_infos": exch.payment_infos,

                    "created_at": exch.created_at,
                    "updated_at": exch.updated_at,

                    "items": [
                        {
                            "id": item.id,
                            "order_item_id": item.order_item_id,
                            "product_id": item.product_id,
                            "quantity": item.quantity,
                            "exchange_amount": item.exchange_amount,
                            "reason": item.reason,
                        }
                        for item in exch.items
                    ]
                })
            responses.append(response)

        return responses
    

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
            .where(*self._build_filter_conds(data))
            .offset(offset=cursor).limit(data.limit))

        orders=(await self.session.execute(order_stmt)).mappings().all()

        return orders
    

    async def getby_customer_id(self,data:GetOrderByCustomerIdSchema)-> List[dict] | list:
        offset=data.offset
        if offset<=0:
            offset=1
        cursor=(offset-1)*data.limit
        search_term=f"%{data.query}%"
        ic(data.shop_id)
        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))

        stmt = (
            select(Orders)
            .options(
                # Order Items
                selectinload(Orders.items).selectinload(OrderItems.return_items),
                selectinload(Orders.items).selectinload(OrderItems.exchange_items),

                # Returns
                selectinload(Orders.returns).selectinload(Returns.items),

                # Exchanges
                selectinload(Orders.exchanges).selectinload(Exchanges.items),
            )
            .where(*self._build_filter_conds(data))
            .offset(cursor)
            .limit(data.limit)
        )

        result = await self.session.execute(stmt)
        orders = result.scalars().all()

        if not orders:
            return []

        responses = []
        for order in orders:
            response = {
                "id": order.id,
                "sequence_id": order.sequence_id,
                "ui_id": order.ui_id,
                "shop_id": order.shop_id,
                "customer_id": order.customer_id,
                "status": order.status,
                "origin": order.origin,
                "calculation_infos": order.calculation_infos,
                "charges_infos": order.charges_infos,
                "payment_infos": order.payment_infos,
                "date": order.date,
                "additional_infos": order.additional_infos,
                "created_at": order.created_at,
                "updated_at": order.updated_at,

                "items": [],
                "returns": [],
                "exchanges": []
            }

            # -------------------------
            # Order Items
            # -------------------------
            for item in order.items:
                response["items"].append({
                    "id": item.id,
                    "product_id": item.product_id,
                    "variant_id": item.variant_id,
                    "batch_id": item.batch_id,
                    "serialno_infos": item.serialno_infos,
                    "gst": item.gst,
                    "quantity": item.quantity,
                    "buy_price": item.buy_price,
                    "sell_price": item.sell_price,
                    "additional_infos": item.additional_infos,

                    "returned_quantity": sum(
                        ri.quantity
                        for ri in item.return_items
                    ),

                    "exchanged_quantity": sum(
                        ei.quantity
                        for ei in item.exchange_items
                    ),

                    "returns": [
                        {
                            "id": ri.id,
                            "return_id": ri.return_id,
                            "quantity": ri.quantity,
                            "refund_amount": ri.refund_amount,
                            "reason": ri.reason,
                            "created_at": ri.created_at
                        }
                        for ri in item.return_items
                    ],

                    "exchanges": [
                        {
                            "id": ei.id,
                            "exchange_id": ei.exchange_id,
                            "quantity": ei.quantity,
                            "exchange_amount": ei.exchange_amount,
                            "reason": ei.reason,
                            "created_at": ei.created_at
                        }
                        for ei in item.exchange_items
                    ]
                })

            # -------------------------
            # Returns
            # -------------------------
            for ret in order.returns:
                response["returns"].append({
                    "id": ret.id,
                    "sequence_id": ret.sequence_id,
                    "status": ret.status,
                    "total_refund_amount": ret.total_refund_amount,
                    "total_refund_qty": ret.total_refund_qty,
                    "payment_infos": ret.payment_infos,
                    "created_at": ret.created_at,
                    "updated_at": ret.updated_at,

                    "items": [
                        {
                            "id": item.id,
                            "order_item_id": item.order_item_id,
                            "product_id": item.product_id,
                            "quantity": item.quantity,
                            "refund_amount": item.refund_amount,
                            "reason": item.reason,
                        }
                        for item in ret.items
                    ]
                })

            # -------------------------
            # Exchanges
            # -------------------------
            for exch in order.exchanges:
                response["exchanges"].append({
                    "id": exch.id,
                    "sequence_id": exch.sequence_id,
                    "status": exch.status,
                    "payment_status": exch.payment_status,
                    "reason": exch.reason,

                    "replacement_order_id": exch.replacement_order_id,

                    "total_exchanged_amount": exch.total_exchanged_amount,
                    "total_exchanged_qty": exch.total_exchanged_qty,

                    "total_replacement_amount": exch.total_replacement_amount,
                    "total_replacement_qty": exch.total_replacement_qty,

                    "payment_infos": exch.payment_infos,

                    "created_at": exch.created_at,
                    "updated_at": exch.updated_at,

                    "items": [
                        {
                            "id": item.id,
                            "order_item_id": item.order_item_id,
                            "product_id": item.product_id,
                            "quantity": item.quantity,
                            "exchange_amount": item.exchange_amount,
                            "reason": item.reason,
                        }
                        for item in exch.items
                    ]
                })
            responses.append(response)

        return responses

    async def getby_id(self,data:GetOrderByIdSchema)-> dict | None:
        created_at=func.date(func.timezone(data.timezone.value,Orders.created_at))
        stmt = (
            select(Orders)
            .options(
                # Order Items
                selectinload(Orders.items).selectinload(OrderItems.return_items),
                selectinload(Orders.items).selectinload(OrderItems.exchange_items),

                # Returns
                selectinload(Orders.returns).selectinload(Returns.items),

                # Exchanges
                selectinload(Orders.exchanges).selectinload(Exchanges.items),
            )
            .where(Orders.id == data.id,Orders.shop_id==data.shop_id)
        )

        result = await self.session.execute(stmt)
        order = result.scalar_one_or_none()

        if order is None:
            return None

        response = {
            "id": order.id,
            "sequence_id": order.sequence_id,
            "ui_id": order.ui_id,
            "shop_id": order.shop_id,
            "customer_id": order.customer_id,
            "status": order.status,
            "origin": order.origin,
            "calculation_infos": order.calculation_infos,
            "charges_infos": order.charges_infos,
            "payment_infos": (
                {k: v for p in order.payment_infos if isinstance(p, dict) for k, v in p.items()}
                if isinstance(order.payment_infos, list)
                else (order.payment_infos or {})
            ),
            "date": order.date,
            "additional_infos": order.additional_infos,
            "created_at": order.created_at,
            "updated_at": order.updated_at,

            "items": [],
            "returns": [],
            "exchanges": []
        }

        # -------------------------
        # Order Items
        # -------------------------
        for item in order.items:
            response["items"].append({
                "id": item.id,
                "product_id": item.product_id,
                "variant_id": item.variant_id,
                "batch_id": item.batch_id,
                "serialno_infos": item.serialno_infos,
                "gst": item.gst,
                "quantity": item.quantity,
                "buy_price": item.buy_price,
                "sell_price": item.sell_price,
                "additional_infos": item.additional_infos,

                "returned_quantity": sum(
                    ri.quantity
                    for ri in item.return_items
                ),

                "exchanged_quantity": sum(
                    ei.quantity
                    for ei in item.exchange_items
                ),

                "returns": [
                    {
                        "id": ri.id,
                        "return_id": ri.return_id,
                        "quantity": ri.quantity,
                        "refund_amount": ri.refund_amount,
                        "reason": ri.reason,
                        "created_at": ri.created_at
                    }
                    for ri in item.return_items
                ],

                "exchanges": [
                    {
                        "id": ei.id,
                        "exchange_id": ei.exchange_id,
                        "quantity": ei.quantity,
                        "exchange_amount": ei.exchange_amount,
                        "reason": ei.reason,
                        "created_at": ei.created_at
                    }
                    for ei in item.exchange_items
                ]
            })

        # -------------------------
        # Returns
        # -------------------------
        for ret in order.returns:
            response["returns"].append({
                "id": ret.id,
                "sequence_id": ret.sequence_id,
                "status": ret.status,
                "total_refund_amount": ret.total_refund_amount,
                "total_refund_qty": ret.total_refund_qty,
                "payment_infos": ret.payment_infos,
                "created_at": ret.created_at,
                "updated_at": ret.updated_at,

                "items": [
                    {
                        "id": item.id,
                        "order_item_id": item.order_item_id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "refund_amount": item.refund_amount,
                        "reason": item.reason,
                    }
                    for item in ret.items
                ]
            })

        # -------------------------
        # Exchanges
        # -------------------------
        for exch in order.exchanges:
            response["exchanges"].append({
                "id": exch.id,
                "sequence_id": exch.sequence_id,
                "status": exch.status,
                "payment_status": exch.payment_status,
                "reason": exch.reason,

                "replacement_order_id": exch.replacement_order_id,

                "total_exchanged_amount": exch.total_exchanged_amount,
                "total_exchanged_qty": exch.total_exchanged_qty,

                "total_replacement_amount": exch.total_replacement_amount,
                "total_replacement_qty": exch.total_replacement_qty,

                "payment_infos": exch.payment_infos,

                "created_at": exch.created_at,
                "updated_at": exch.updated_at,

                "items": [
                    {
                        "id": item.id,
                        "order_item_id": item.order_item_id,
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "exchange_amount": item.exchange_amount,
                        "reason": item.reason,
                    }
                    for item in exch.items
                ]
            })

        return response
    

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

    async def get_overall_values(self, data: GetAllOrderSchema | GetOrderByShopIdSchema | GetOrderByCustomerIdSchema) -> dict:
        conds = self._build_filter_conds(data)

        total_val = func.coalesce(
            func.cast(Orders.calculation_infos['total_sellprice'].astext, Float),
            func.cast(Orders.item_infos['total_order_amount'].astext, Float),
            0.0
        )

        stmt_orders = select(
            func.coalesce(func.sum(total_val), 0.0).label("total_order_value"),
            func.count(Orders.id).label("total_orders")
        ).where(*conds)
        
        res_orders = (await self.session.execute(stmt_orders)).mappings().one_or_none()

        stmt_items = select(
            func.coalesce(func.sum(case((OrderItems.status == 'REFUNDED', 1), else_=0)), 0).label("total_returns"),
            func.coalesce(func.sum(case((OrderItems.status == 'EXCHANGED', 1), else_=0)), 0).label("total_exchanged")
        ).select_from(Orders).outerjoin(OrderItems, Orders.id == OrderItems.order_id).where(*conds)
        
        res_items = (await self.session.execute(stmt_items)).mappings().one_or_none()

        return {
            "total_order_value": res_orders["total_order_value"] if res_orders else 0.0,
            "total_orders": res_orders["total_orders"] if res_orders else 0,
            "total_returns": res_items["total_returns"] if res_items else 0,
            "total_exchanged": res_items["total_exchanged"] if res_items else 0
        }

    async def get_bulk_orders(self, shop_id: str, order_ids: List[str]) -> List[dict]:
        stmt = (
            select(Orders)
            .options(
                selectinload(Orders.items).selectinload(OrderItems.return_items),
                selectinload(Orders.items).selectinload(OrderItems.exchange_items),
                selectinload(Orders.returns).selectinload(Returns.items),
                selectinload(Orders.exchanges).selectinload(Exchanges.items),
            )
            .where(Orders.id.in_(order_ids), Orders.shop_id == shop_id)
        )

        result = await self.session.execute(stmt)
        orders = result.scalars().all()

        response_list = []
        for order in orders:
            response = {
                "id": order.id,
                "sequence_id": order.sequence_id,
                "ui_id": order.ui_id,
                "shop_id": order.shop_id,
                "customer_id": order.customer_id,
                "status": order.status,
                "origin": order.origin,
                "calculation_infos": order.calculation_infos,
                "charges_infos": order.charges_infos,
                "payment_infos": order.payment_infos,
                "date": order.date,
                "additional_infos": order.additional_infos,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "items": [],
                "returns": [],
                "exchanges": []
            }

            for item in order.items:
                response["items"].append({
                    "id": item.id,
                    "product_id": item.product_id,
                    "variant_id": item.variant_id,
                    "batch_id": item.batch_id,
                    "serialno_infos": item.serialno_infos,
                    "gst": item.gst,
                    "quantity": item.quantity,
                    "buy_price": item.buy_price,
                    "sell_price": item.sell_price,
                    "additional_infos": item.additional_infos,
                    "returned_quantity": sum(ri.quantity for ri in item.return_items),
                    "exchanged_quantity": sum(ei.quantity for ei in item.exchange_items),
                    "returns": [
                        {
                            "id": ri.id,
                            "quantity": ri.quantity,
                            "created_at": ri.created_at,
                            "updated_at": ri.updated_at
                        }
                        for ri in item.return_items
                    ],
                    "exchanges": [
                        {
                            "id": ei.id,
                            "quantity": ei.quantity,
                            "created_at": ei.created_at,
                            "updated_at": ei.updated_at
                        }
                        for ei in item.exchange_items
                    ]
                })

            for ret in order.returns:
                response["returns"].append({
                    "id": ret.id,
                    "reason": ret.reason,
                    "status": ret.status,
                    "created_at": ret.created_at,
                    "updated_at": ret.updated_at,
                    "items": [
                        {
                            "id": ri.id,
                            "order_item_id": ri.order_item_id,
                            "quantity": ri.quantity,
                            "created_at": ri.created_at,
                            "updated_at": ri.updated_at
                        }
                        for ri in ret.items
                    ]
                })

            for exch in order.exchanges:
                response["exchanges"].append({
                    "id": exch.id,
                    "reason": exch.reason,
                    "status": exch.status,
                    "created_at": exch.created_at,
                    "updated_at": exch.updated_at,
                    "items": [
                        {
                            "id": ei.id,
                            "order_item_id": ei.order_item_id,
                            "quantity": ei.quantity,
                            "created_at": ei.created_at,
                            "updated_at": ei.updated_at
                        }
                        for ei in exch.items
                    ]
                })
            response_list.append(response)

        return response_list
