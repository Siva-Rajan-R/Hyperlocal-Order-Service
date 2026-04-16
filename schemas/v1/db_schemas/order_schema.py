from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict

class CreateOrderDbSchema(BaseModel):
    id:str
    shop_id:str
    orders:List[OrderItemValueTypDict]
    total_price:float
    customer_number:str
    customer_name:str
    order_by:str
    status:OrderStatusEnum
    origin:OrderOriginEnum



class UpdateOrderStatusDbSchema(BaseModel):
    id:str
    shop_id:str
    status:Optional[OrderStatusEnum]=None
    origin:Optional[OrderOriginEnum]=None