from pydantic import BaseModel,Field
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum,OrderReturnTypeEnum,OrderPaymentEnums
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict
from hyperlocal_platform.core.enums.timezone_enum import TimeZoneEnum

class OrderCustomerSchema(BaseModel):
    customer_id: str
    customer_name: str
    customer_mobile_number: str


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
    datas:Optional[dict]=None
    gst:Optional[str]=None
    quantity:float

class CreateOrderSchema(BaseModel):
    shop_id:str
    customer_id:Optional[str]=None
    customer:Optional[OrderCustomerSchema]=None
    status:OrderStatusEnum
    payments:Dict[OrderPaymentEnums,float]
    datas:Optional[dict]=None
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
    from_date:Optional[str]=None
    to_date:Optional[str]=None
    status:Optional[str]=None
    origin:Optional[str]=None
    payment_method:Optional[str]=None


class GetOrderByShopIdSchema(BaseModel):
    shop_id:str
    query:Optional[str]=Field(default="",alias='q')
    limit:Optional[int]=Field(default=10,le=100)
    offset:int=Field(default=1)
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata
    from_date:Optional[str]=None
    to_date:Optional[str]=None
    status:Optional[str]=None
    origin:Optional[str]=None
    payment_method:Optional[str]=None


class GetOrderByCustomerIdSchema(BaseModel):
    shop_id:str
    customer_id:str
    query:Optional[str]=Field(default="",alias='q')
    limit:Optional[int]=Field(default=10,le=100)
    offset:int=Field(default=1)
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata
    from_date:Optional[str]=None
    to_date:Optional[str]=None
    status:Optional[str]=None
    origin:Optional[str]=None
    payment_method:Optional[str]=None


class GetOrderByIdSchema(BaseModel):
    id:str
    shop_id:str
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata


class ReturnOrderSchema(BaseModel):
    id:str
    item_id:str
    shop_id:str
    customer_id:Optional[str]=None
    customer:Optional[OrderCustomerSchema]=None
    payments:Optional[dict]=None

class ReturnOrderItemsSchema(BaseModel):
    id:str
    quantity:float
    reason:str

class ReturnBulkOrderSchema(BaseModel):
    id:str
    shop_id:str
    customer_id:Optional[str]=None
    customer:Optional[OrderCustomerSchema]=None
    payments:Optional[dict]=None
    items:List[ReturnOrderItemsSchema]


class ExchangeOrderSchema(BaseModel):
    shop_id:str
    customer_id:Optional[str]=None
    customer:Optional[OrderCustomerSchema]=None
    order_id:str
    item_id:str
    payments:Dict[OrderPaymentEnums,float]
    items:OrderItemsSchema

class ExchangeBulkOrderSchema(BaseModel):
    shop_id:str
    customer_id:Optional[str]=None
    customer:Optional[OrderCustomerSchema]=None
    order_id:str
    exchange_items:List[ReturnOrderItemsSchema]
    payments:Dict[OrderPaymentEnums,float]
    items:List[OrderItemsSchema]
