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
    product_id: str
    variant_id:Optional[str]=None
    batch_id:Optional[str]=None
    serialno_infos:Optional[str]=None
    barcode:Optional[str]=None
    quantity:float

class CreateOrderSchema(BaseModel):
    shop_id: str
    session_id: str
    customer_id: Optional[str] = None
    status: OrderStatusEnum
    origin: OrderOriginEnum
    type: Optional[str] = None
    calculation_infos: dict = {}
    charges_infos: dict = {}
    payment_infos: dict = {}
    additional_infos: Optional[dict] = None
    
    # Optional fields for online order user info
    user_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    address_id: Optional[str] = None
    full_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = None

    from pydantic import model_validator
    @model_validator(mode="after")
    def validate_online_order(self):
        origin_val = self.origin.value if hasattr(self.origin, 'value') else self.origin
        if origin_val == "ONLINE" or origin_val == OrderOriginEnum.ONLINE:
            mandatory_fields = ["user_id", "name", "phone", "address_id", "full_address", "city", "pincode", "state"]
            for field in mandatory_fields:
                if not getattr(self, field):
                    raise ValueError(f"{field} is mandatory for ONLINE orders")
        return self



class DeleteOrderSchema(BaseModel):
    id:str
    shop_id:str

class VerifyDeliverySchema(BaseModel):
    shop_id: str
    order_id: str
    code: Optional[str] = None
    otp: Optional[str] = None
    delivery_otp: Optional[str] = None


class GetAllOrderSchema(BaseModel):
    shop_id:Optional[str]=None
    query:Optional[str]=Field(default="",alias='q')
    limit:Optional[int]=Field(default=10,le=100)
    offset:int=Field(default=1)
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata
    from_date:Optional[str]=None
    to_date:Optional[str]=None
    status:Optional[str]=None
    origin:Optional[str]=None
    payment_method:Optional[str]=None
    payment_status:Optional[str]=None
    online_only:Optional[bool]=None
    exclude_online:Optional[bool]=None
    exclude_online_orders:Optional[bool]=None
    exclude_online_order:Optional[bool]=None
    exclude_offline:Optional[bool]=None
    exclude_offline_orders:Optional[bool]=None
    exclude_offline_order:Optional[bool]=None
    exclude_pos:Optional[bool]=None
    exclude_direct:Optional[bool]=None
    exclude_return:Optional[bool]=None
    exclude_returns:Optional[bool]=None
    exclude_returned:Optional[bool]=None
    exclude_has_return:Optional[bool]=None
    exclude_has_returns:Optional[bool]=None
    exclude_with_return:Optional[bool]=None
    exclude_with_returns:Optional[bool]=None
    exclude_non_return:Optional[bool]=None
    exclude_non_returns:Optional[bool]=None
    exclude_no_return:Optional[bool]=None
    exclude_no_returns:Optional[bool]=None
    exclude_without_return:Optional[bool]=None
    exclude_without_returns:Optional[bool]=None
    exclude_accepted:Optional[bool]=None
    exclude_accept:Optional[bool]=None
    exclude_pending:Optional[bool]=None
    exclude_pendings:Optional[bool]=None
    exclude_canceled:Optional[bool]=None
    exclude_cancelled:Optional[bool]=None
    exclude_canceleed:Optional[bool]=None
    exclude_cancle:Optional[bool]=None
    exclude_cancel:Optional[bool]=None
    exclude_out_for_delivery:Optional[bool]=None
    exclude_out_for_deleivery:Optional[bool]=None
    exclude_delivered:Optional[bool]=None
    exclude_delevered:Optional[bool]=None
    online_delivered_only:Optional[bool]=None


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
    payment_status:Optional[str]=None
    online_only:Optional[bool]=None
    exclude_online:Optional[bool]=None
    exclude_online_orders:Optional[bool]=None
    exclude_online_order:Optional[bool]=None
    exclude_offline:Optional[bool]=None
    exclude_offline_orders:Optional[bool]=None
    exclude_offline_order:Optional[bool]=None
    exclude_pos:Optional[bool]=None
    exclude_direct:Optional[bool]=None
    exclude_return:Optional[bool]=None
    exclude_returns:Optional[bool]=None
    exclude_returned:Optional[bool]=None
    exclude_has_return:Optional[bool]=None
    exclude_has_returns:Optional[bool]=None
    exclude_with_return:Optional[bool]=None
    exclude_with_returns:Optional[bool]=None
    exclude_non_return:Optional[bool]=None
    exclude_non_returns:Optional[bool]=None
    exclude_no_return:Optional[bool]=None
    exclude_no_returns:Optional[bool]=None
    exclude_without_return:Optional[bool]=None
    exclude_without_returns:Optional[bool]=None
    exclude_accepted:Optional[bool]=None
    exclude_accept:Optional[bool]=None
    exclude_pending:Optional[bool]=None
    exclude_pendings:Optional[bool]=None
    exclude_canceled:Optional[bool]=None
    exclude_cancelled:Optional[bool]=None
    exclude_canceleed:Optional[bool]=None
    exclude_cancle:Optional[bool]=None
    exclude_cancel:Optional[bool]=None
    exclude_out_for_delivery:Optional[bool]=None
    exclude_out_for_deleivery:Optional[bool]=None
    exclude_delivered:Optional[bool]=None
    exclude_delevered:Optional[bool]=None
    online_delivered_only:Optional[bool]=None


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
    payment_status:Optional[str]=None
    online_only:Optional[bool]=None
    exclude_online:Optional[bool]=None
    exclude_online_orders:Optional[bool]=None
    exclude_online_order:Optional[bool]=None
    exclude_offline:Optional[bool]=None
    exclude_offline_orders:Optional[bool]=None
    exclude_offline_order:Optional[bool]=None
    exclude_pos:Optional[bool]=None
    exclude_direct:Optional[bool]=None
    exclude_return:Optional[bool]=None
    exclude_returns:Optional[bool]=None
    exclude_returned:Optional[bool]=None
    exclude_has_return:Optional[bool]=None
    exclude_has_returns:Optional[bool]=None
    exclude_with_return:Optional[bool]=None
    exclude_with_returns:Optional[bool]=None
    exclude_non_return:Optional[bool]=None
    exclude_non_returns:Optional[bool]=None
    exclude_no_return:Optional[bool]=None
    exclude_no_returns:Optional[bool]=None
    exclude_without_return:Optional[bool]=None
    exclude_without_returns:Optional[bool]=None
    exclude_accepted:Optional[bool]=None
    exclude_accept:Optional[bool]=None
    exclude_pending:Optional[bool]=None
    exclude_pendings:Optional[bool]=None
    exclude_canceled:Optional[bool]=None
    exclude_cancelled:Optional[bool]=None
    exclude_canceleed:Optional[bool]=None
    exclude_cancle:Optional[bool]=None
    exclude_cancel:Optional[bool]=None
    exclude_out_for_delivery:Optional[bool]=None
    exclude_out_for_deleivery:Optional[bool]=None
    exclude_delivered:Optional[bool]=None
    exclude_delevered:Optional[bool]=None
    online_delivered_only:Optional[bool]=None


class GetOrderByIdSchema(BaseModel):
    id:str
    shop_id:str
    timezone:Optional[TimeZoneEnum]=TimeZoneEnum.Asia_Kolkata


class ReturnSerialnoInfoSchema(BaseModel):
    id: str
    name: str

class ReturnItemRequestSchema(BaseModel):
    order_item_id: str
    quantity: float
    reason: Optional[str] = None
    serialno_infos: Optional[List[ReturnSerialnoInfoSchema]] = None
    unit: Optional[str] = None

class CreateReturnSchema(BaseModel):
    shop_id: str
    order_id: str
    payment_infos:dict
    items: List[ReturnItemRequestSchema]

class ExchangeItemSchema(BaseModel):
    """Item the customer is returning (exchanging OUT)"""
    order_item_id: str             # the original order item ID being exchanged
    quantity: float                # how many they are returning
    unit: Optional[str] = None     # optional sub-unit (e.g. 'g', 'mg')
    reason: Optional[str] = None
    serialno_infos: Optional[List[ReturnSerialnoInfoSchema]] = None

class ReplacementItemSchema(BaseModel):
    """Item the customer is receiving (exchanging IN)"""
    product_id: str
    variant_id: Optional[str] = None
    batch_id: Optional[str] = None
    quantity: float
    unit: Optional[str] = None     # optional sub-unit for replacement item qty
    serialno_infos: Optional[List[ReturnSerialnoInfoSchema]] = None

class ExchangePaymentSchema(BaseModel):
    method: str                    # e.g. CASH, UPI, ON_CREDIT
    amount: float

class CreateExchangeSchema(BaseModel):
    shop_id: str
    original_order_id: str
    customer_id: Optional[str] = None   # required if using ON_CREDIT payment
    reason: Optional[str] = None
    payments: List[ExchangePaymentSchema] = []
    exchange_items: List[ExchangeItemSchema]       # items being returned by customer
    replacement_items: List[ReplacementItemSchema]  # items customer is taking instead


class UpdateOrderStatusSchema(BaseModel):
    id: str
    shop_id: str
    status: Optional[OrderStatusEnum] = None
    payment_infos: Optional[dict] = None

class GetBulkOrdersSchema(BaseModel):
    shop_id: str
    order_ids: List[str]

