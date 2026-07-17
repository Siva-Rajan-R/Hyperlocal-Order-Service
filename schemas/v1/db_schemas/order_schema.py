from pydantic import BaseModel
from core.data_formats.enums.order_enum import OrderStatusEnum, OrderOriginEnum, OrderPaymentEnums
from typing import Optional, List, Dict
from datetime import datetime

class OrderItemsDbSchema(BaseModel):
    id: str
    order_id: str
    product_id: str
    variant_id: Optional[str] = None
    batch_id: Optional[str] = None
    buy_price: float
    sell_price: float
    quantity: float
    gst: Optional[str] = None
    additional_infos: Optional[dict] = None
    
class CreateOrderDbSchema(BaseModel):
    id: str
    ui_id: str
    shop_id: str
    customer_id: Optional[str] = None
    status: str
    origin: str
    calculation_infos: dict = {}
    charges_infos: dict = {}
    item_infos: dict = {}
    payment_infos: dict = {}
    date: datetime
    additional_infos: Optional[dict] = None

class UpdateOrderDbSchema(BaseModel):
    id: str
    shop_id: str
    status: Optional[str] = None
    origin: Optional[str] = None
    payment_infos: Optional[dict] = None

class UpdateOrderItemDbSchema(BaseModel):
    id: str
    order_id: str
    status: Optional[str] = None

class CreateReturnDbSchema(BaseModel):
    id: str
    ui_id: str
    order_id: str
    shop_id: str
    customer_id: Optional[str] = None
    total_refund_amount: float = 0.0
    total_refund_qty: float = 0.0
    payment_infos: dict = {}
    status: str

class CreateReturnItemDbSchema(BaseModel):
    id: str
    return_id: str
    order_item_id: str
    product_id: str
    quantity: float
    refund_amount: float = 0.0
    reason: Optional[str] = None

class CreateExchangeDbSchema(BaseModel):
    id: str
    ui_id: str
    original_order_id: str
    replacement_order_id: str
    shop_id: str
    customer_id: Optional[str] = None
    additional_amount_paid: float
    amount_refunded: float
    clear_outstanding_amount: float
    reason: Optional[str] = None
    status: str

class CreateExchangeItemDbSchema(BaseModel):
    id: str
    exchange_id: str
    return_order_item_id: str
    replacement_product_id: str
    quantity_returned: float
    quantity_replaced: float = 0.0
    reason: Optional[str] = None
