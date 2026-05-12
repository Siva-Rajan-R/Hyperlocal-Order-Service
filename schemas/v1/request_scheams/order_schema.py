from pydantic import BaseModel,Field
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum,OrderReturnTypeEnum
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum


class OrderItemsSchema(BaseModel):
    inventory_id:str
    variant_id:Optional[str]=None
    batch_id:Optional[str]=None
    serialno_id:Optional[str]=None
    barcode:Optional[str]=None
    serialno_id:Optional[str]=None
    inv_serial_numbers:Optional[List[str]]=None
    buy_price:float
    sell_price:float
    gst:Optional[str]=None
    quantity:int

class CreateOrderSchema(BaseModel):
    shop_id:str
    customer_id:str
    status:OrderStatusEnum
    payment_method:str
    origin:OrderOriginEnum
    items:List[OrderItemsSchema]



class DeleteOrderSchema(BaseModel):
    id:str
    shop_id:str


class GetAllOrderSchema(BaseModel):
    query:Optional[str]=Field(default="",alias='q')
    limit:Optional[int]=Field(default=10,le=100)
    offset:int=Field(default=1)
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata


class GetOrderByShopIdSchema(BaseModel):
    shop_id:str
    query:Optional[str]=Field(default="",alias='q')
    limit:Optional[int]=Field(default=10,le=100)
    offset:int=Field(default=1)
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata


class GetOrderByIdSchema(BaseModel):
    id:str
    shop_id:str
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata


class ReturnOrderSchema(BaseModel):
    id:str
    item_id:str

class ExchangeOrderSchema(BaseModel):
    shop_id:str
    customer_id:str
    order_id:str
    item_id:str
    payment_method:str
    items:OrderItemsSchema
