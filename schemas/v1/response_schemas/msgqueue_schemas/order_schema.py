from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum,OrderOriginEnum,OrderPaymentEnums
from core.data_formats.typ_dicts.order_typdict import OrderItemValueTypDict
from typing import Optional,List,Dict,Union
from datetime import date,datetime


class SerialInfo(BaseModel):
    serialno_id: str
    serial_numbers: List[str] = []

class VariantInfo(BaseModel):
    variant_id: str
    variant_name: str

class BatchInfo(BaseModel):
    batch_id: str
    batch_name: str
    mfg_date: Optional[str] = None
    exp_date: Optional[str] = None

class OrderItemsResponseSchema(BaseModel):
    id:str
    inventory_id:str
    variant_info:Optional[VariantInfo]=None
    batch_info:Optional[BatchInfo]=None
    serialno_info:Optional[SerialInfo]=None
    barcode:Optional[str]=None
    buy_price:float
    sell_price:float
    
    status:OrderStatusEnum
    reason:Optional[str]=None
    datas:Optional[dict]=None
    gst:Optional[str]=None
    quantity:int

    
class OrderCreateResponseSchema(BaseModel):
    id:str
    ui_id:Union[str, int]
    shop_id:str
    customer:Optional[dict]=None
    type:str
    payments:Dict[OrderPaymentEnums,float]
    datas:Optional[dict]=None
    
    total_quantity:int
    total_buyprice:float
    total_sellprice:float
    status:OrderStatusEnum
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime




class OrderUpdateResponseSchema(BaseModel):
    id:str
    ui_id:Union[str, int]
    shop_id:str
    total_quantity:int
    payments:Dict[OrderPaymentEnums,float]
    type:str
    
    datas:Optional[dict]=None
    total_buyprice:float
    total_sellprice:float
    customer:Optional[dict]=None
    status:OrderStatusEnum
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime


class OrderDeleteResponseSchema(BaseModel):
    id:str
    ui_id:Union[str, int]
    shop_id:str
    total_quantity:int
    payments:Dict[OrderPaymentEnums,float]
    total_buyprice:float
    type:str
    
    datas:Optional[dict]=None
    total_sellprice:float
    customer:Optional[dict]=None
    status:OrderStatusEnum
    origin:OrderOriginEnum

    created_at:datetime
    updated_at:datetime


class ReplacementOrderResponseSchema(BaseModel):
    id: str
    ui_id: Optional[Union[str, int]] = None
    shop_id: str
    origin: str
    status: str
    customer_id: Optional[str] = None
    total_buyprice: float = 0.0
    total_sellprice: float = 0.0
    total_quantity: float = 0.0
    type: Optional[str] = None
    payments: Dict[str, float] = {}
    datas: Optional[dict] = None
    items: List[OrderItemsResponseSchema] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ExchangedItemResponseSchema(BaseModel):
    exchanged_items: List[str] = []
    replacement_order: Optional[ReplacementOrderResponseSchema] = None

class OrderGetResponseSchema(BaseModel):
    id:str
    ui_id:Union[str, int]
    shop_id:str
    total_quantity:int
    payments:Dict[OrderPaymentEnums,float]
    total_buyprice:float
    total_sellprice:float
    type:str
    
    datas:Optional[dict]=None
    customer:Optional[dict]=None
    status:OrderStatusEnum
    origin:OrderOriginEnum
    items:List[OrderItemsResponseSchema]
    returns:Optional[List[dict]]=None
    exchanged_items:Optional[List[ExchangedItemResponseSchema]]=None

    created_at:datetime
    updated_at:datetime







