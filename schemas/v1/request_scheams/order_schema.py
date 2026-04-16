from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict

class CreateOrderSchema(BaseModel):
    shop_id:str
    orders:List[str]
    customer_number:str
    customer_name:str
    status:OrderStatusEnum
    origin:OrderOriginEnum

    model_config={
        'extra':'allow'
    }

class UpdateOrderStatusSchema(BaseModel):
    id:str
    shop_id:str
    status:Optional[OrderStatusEnum]=None
    origin:Optional[OrderOriginEnum]=None
    