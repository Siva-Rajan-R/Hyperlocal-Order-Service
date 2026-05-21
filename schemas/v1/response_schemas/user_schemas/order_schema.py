from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum,OrderPaymentEnums
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from datetime import date,datetime


class OrderItemsResponseSchema(BaseModel):
    id:str
    inventory_id:str
    variant_id:Optional[str]=None
    batch_id:Optional[str]=None
    serialno_id:Optional[str]=None
    barcode:Optional[str]=None
    serialno_id:Optional[str]=None
    serial_numbers:Optional[List[str]]=None
    reason:Optional[str]=None
    datas:Optional[dict]=None
    buy_price:float
    sell_price:float
    status:OrderStatusEnum
    gst:Optional[str]=None
    quantity:float
    returned_quantity:Optional[float]=None

    
class OrderCreateResponseSchema(BaseModel):
    id:str
    ui_id:int
    shop_id:str
    customer_id:str
    status:OrderStatusEnum
    type:str
    payments:Dict[OrderPaymentEnums,float]
    datas:Optional[dict]=None
    
    total_quantity:float
    total_buyprice:float
    total_sellprice:float
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime




class OrderUpdateResponseSchema(BaseModel):
    id:str
    ui_id:int
    shop_id:str
    customer_id:str
    type:str
    payments:Dict[OrderPaymentEnums,float]
    datas:Optional[dict]=None
    total_quantity:float
    
    total_buyprice:float
    total_sellprice:float
    status:OrderStatusEnum
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime


class OrderDeleteResponseSchema(BaseModel):
    id:str
    ui_id:int
    shop_id:str
    type:str
    payments:Dict[OrderPaymentEnums,float]
    datas:Optional[dict]=None
    customer_id:str
    total_quantity:float
    
    total_buyprice:float
    total_sellprice:float
    status:OrderStatusEnum
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime


class OrderGetResponseSchema(BaseModel):
    id:str
    ui_id:int
    shop_id:str
    total_quantity:float
    payments:Dict[OrderPaymentEnums,float]
    type:str
    
    datas:Optional[dict]=None
    total_buyprice:float
    total_sellprice:float
    customer_id:str
    status:OrderStatusEnum
    origin:OrderOriginEnum
    items:List[OrderItemsResponseSchema]
    exchanged_items:Optional[list]=None

    created_at:datetime
    updated_at:datetime







