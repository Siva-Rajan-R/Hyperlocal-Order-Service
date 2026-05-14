from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum,OrderPaymentEnums
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict


class OrderItemsDbSchema(BaseModel):
    id:str
    order_id:str
    inventory_id:str
    variant_id:Optional[str]=None
    batch_id:Optional[str]=None
    serialno_id:Optional[str]=None
    barcode:Optional[str]=None
    serialno_id:Optional[str]=None
    inv_serial_numbers:Optional[List[str]]=None
    buy_price:float
    sell_price:float
    reason:Optional[str]=None
    datas:Optional[dict]=None
    status:OrderStatusEnum
    gst:Optional[str]=None
    quantity:int
    
class CreateOrderDbSchema(BaseModel):
    id:str
    shop_id:str
    total_quantity:int
    total_sellprice:int
    total_buyprice:int
    customer_id:str
    payments:Dict[OrderPaymentEnums,float]
    status:OrderStatusEnum
    origin:OrderOriginEnum
    datas:Optional[dict]=None
    type:Optional[str]='NORMAL'

class UpdateOrderDbSchema(BaseModel):
    id:str
    shop_id:str
    total_quantity:Optional[int]=None
    total_sellprice:Optional[int]=None
    total_buyprice:Optional[int]=None
    
    status:Optional[OrderStatusEnum]=None
    origin:Optional[OrderOriginEnum]=None


class UpdateOrderItemDbSchema(BaseModel):
    id:str
    order_id:str
    status:Optional[OrderStatusEnum]=None

class ReturnBulkOrderDbSchema(BaseModel):
    id:str
    items_id:List[str]
    status:str
