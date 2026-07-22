from infras.primary_db.services.order_service import OrdersService
from sqlalchemy.ext.asyncio import AsyncSession
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum
from icecream import ic
from . import HTTPException
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from core.errors.messaging_errors import BussinessError,FatalError,RetryableError
from core.data_formats.enums.order_enum import OrderOriginEnum,OrderStatusEnum
from schemas.v1.request_scheams.order_schema import CreateOrderSchema,GetAllOrderSchema,GetOrderByIdSchema,GetOrderByShopIdSchema,DeleteOrderSchema,GetOrderByCustomerIdSchema,UpdateOrderStatusSchema,GetBulkOrdersSchema
from schemas.v1.response_schemas.user_schemas.order_schema import OrderGetResponseSchema,OrderCreateResponseSchema,OrderUpdateResponseSchema,OrderDeleteResponseSchema
from hyperlocal_platform.core.models.req_res_models import ErrorResponseTypDict,SuccessResponseTypDict,BaseResponseTypDict

from infras.caching.models.billing_model import BillingCacheModel,CachingBillingSchema
from infras.read_db.repos.order_repo import OrderReadDbRepo

class HandleOrderRequest:

    def __init__(self,session:AsyncSession,cur_user_id:str,shop_id:str):
        self.session=session
        self.cur_user_id=cur_user_id
        self.shop_id=shop_id

        
    async def create(self, data: CreateOrderSchema):

        res = await OrdersService(session=self.session).create(data=data, executing_user_id=self.cur_user_id)
        if not res:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponseTypDict(
                    status_code=400,
                    msg="Error : Creating order",
                    description="Invalid Data for order",
                    success=False
                )
            )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=201,
                msg="Order Created Successfully",
                success=True
            ),
            data=res
        )
    
    async def update(self,data:UpdateOrderStatusSchema):
        res=await OrdersService(session=self.session).update(data=data, executing_user_id=self.cur_user_id)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Updating order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
        
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order Updated Successfully",
                success=True
            )
        )
    


    async def delete(self,data:DeleteOrderSchema):
        res=await OrdersService(session=self.session).delete(data=data)
        if not res:
            raise HTTPException(
                    status_code=400,
                    detail=ErrorResponseTypDict(
                        status_code=400,
                        msg="Error : Deleting order",
                        description="Invalid Data for order",
                        success=False
                    )
                )
            
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                msg="Order deleted Successfully",
                success=True
            ),
            data=OrderDeleteResponseSchema(**res) if res else None
        )
    
    def _map_order_fields(self, r: dict) -> dict:
        calc_infos = r.get('calculation_infos', {})
        r['total_quantity'] = calc_infos.get('total_quantity', 0.0)
        r['total_buyprice'] = calc_infos.get('total_buyprice', 0.0)
        r['total_sellprice'] = calc_infos.get('total_sellprice', 0.0)
        
        payments = {}
        payment_infos = r.get('payment_infos') or {}
        if isinstance(payment_infos, dict):
            payments = payment_infos
        elif isinstance(payment_infos, list):
            for p in payment_infos:
                if isinstance(p, dict):
                    mode = p.get('mode')
                    amount = p.get('amount', 0.0)
                    if mode:
                        payments[mode] = payments.get(mode, 0.0) + amount
        r['payments'] = payments
        
        if 'items' in r:
            mapped_items = []
            for item in r.get('items', []):
                item['inventory_id'] = item.get('product_id', '')
                item['variant_info'] = item.get('variant_infos')
                item['batch_info'] = item.get('batch_infos')
                item['serialno_info'] = item.get('serialno_infos')
                mapped_items.append(item)
            r['items'] = mapped_items
        return r

    async def get(self,data:GetAllOrderSchema):
        from infras.primary_db.services.order_service import OrdersService
        res=await OrdersService(session=self.session).get(data=data)
        ic(res)

        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )
    
    async def getby_shop_id(self,data:GetOrderByShopIdSchema):
        from infras.primary_db.services.order_service import OrdersService
        res=await OrdersService(session=self.session).getby_shop_id(data=data)
        out_data = res.get("datas", res) if isinstance(res, dict) and "datas" in res else res
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=out_data
        )
    
    async def getby_customer_id(self,data:GetOrderByCustomerIdSchema):
        from infras.primary_db.services.order_service import OrdersService
        res=await OrdersService(session=self.session).getby_customer_id(data=data)
        out_data = res.get("datas", res) if isinstance(res, dict) and "datas" in res else res
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=out_data
        )
    
    async def getby_id(self,data:GetOrderByIdSchema):
        res=await OrderReadDbRepo.get_by_id(shop_id=data.shop_id,order_id=data.id)
        if not res:
            from infras.primary_db.services.order_service import OrdersService
            res = await OrdersService(session=self.session).getby_id(data=data)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )
    
    async def search(self,limit:int,shop_id:str,query:str=""):
        res=await OrderReadDbRepo.search(query_str=query,shop_id=shop_id,limit=limit)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )
    
    async def get_customer_stats(self, shop_id: str, customer_id: str):
        from infras.read_db.repos.order_stats_repo import CustomerStatsReadDbRepo
        res = await CustomerStatsReadDbRepo.get_customer_stats(shop_id=shop_id, customer_id=customer_id)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Customer stats fetched successfully"
            ),
            data=res
        )

    async def get_dashboard_stats(self, shop_id: str, start_date: str, end_date: str, supplier_id: Optional[str] = None, category: Optional[str] = None):
        from infras.read_db.repos.order_stats_repo import DashboardStatsRepo
        from datetime import datetime
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        res = await DashboardStatsRepo.get_dashboard_stats(shop_id=shop_id, start_date=start, end_date=end, supplier_id=supplier_id, category=category)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Dashboard stats fetched successfully"
            ),
            data=res
        )

    async def get_bulk_orders(self, data: GetBulkOrdersSchema):
        res = await OrdersService(session=self.session).get_bulk_orders(data=data)
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Bulk orders fetched successfully"
            ),
            data=res
        )

    async def getby_user_id(self, user_id: str, limit: int = 10, offset: int = 1):
        res = await OrderReadDbRepo.get_by_user_id(user_id=user_id, limit=limit, offset=offset)
        if not res or not res.get("datas"):
            # Fallback to PG
            from infras.primary_db.models.order_model import OnlineOrderModel
            from sqlalchemy import select
            stmt = select(OnlineOrderModel.order_id).where(OnlineOrderModel.user_id == user_id)
            order_ids = (await self.session.execute(stmt)).scalars().all()
            if order_ids:
                res_bulk = await OrderReadDbRepo.get_bulk_orders_without_shop(order_ids=order_ids)
                res = {"datas": res_bulk}
        return SuccessResponseTypDict(
            detail=BaseResponseTypDict(
                status_code=200,
                success=True,
                msg="Order fetched successfully"
            ),
            data=res
        )

