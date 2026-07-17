from pydantic import BaseModel, ConfigDict, model_validator, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

class SerialInfo(BaseModel):
    id: str
    serial_numbers: List[str] = []

class VariantInfo(BaseModel):
    variant_id: str
    variant_name: str

class BatchInfo(BaseModel):
    batch_id: str
    batch_name: str
    mfg_date: Optional[str] = None
    exp_date: Optional[str] = None

class OrderItemsReadModel(BaseModel):
    id: str
    product_id: str
    ui_id: str = ""
    name: str = ""
    
    category_name: Optional[str] = None
    unit_name: Optional[str] = None
    
    variant_infos: Optional[VariantInfo] = None
    batch_infos: Optional[BatchInfo] = None
    serialno_infos: Optional[List[dict]] = None
    
    buy_price: float = 0.0
    sell_price: float = 0.0
    quantity: float = 0.0
    entered_qty: Optional[float] = None
    entered_unit: Optional[str] = None
    returned_quantity: Optional[float] = None
    total_amount: float = 0.0
    
    status: Optional[str] = "PENDING"
    reason: Optional[str] = None
    gst: Optional[str] = None
    
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(extra='allow')
    
class ReplacementOrderReadModel(BaseModel):
    id: str
    ui_id: Optional[str] = None
    shop_id: str
    origin: str
    status: str
    customer_id: Optional[str] = None
    type: Optional[str] = None

    calculation_infos: dict = {}
    charges_infos: dict = {}
    item_infos: dict = {}
    payment_infos: Union[dict, list] = {}
    date: Optional[datetime] = None
    additional_infos: Optional[dict] = None
    online_details: Optional[dict] = None
    
    datas: Optional[dict] = None
    items: List[OrderItemsReadModel] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ExchangedItemReadModel(BaseModel):
    exchanged_items: List[str] = []
    replacement_order: Optional[ReplacementOrderReadModel] = None

class OrderReadModel(BaseModel):
    id: str
    sequence_id: Optional[int] = None
    ui_id: Optional[str] = None
    shop_id: str
    customer_id: Optional[str] = None
    customer: Optional[dict] = None
    
    status: str
    origin: str
    type: Optional[str] = None
    
    calculation_infos: dict = {}
    charges_infos: dict = {}
    item_infos: dict = {}
    payment_infos: Union[dict, list] = {}
    date: Optional[datetime] = None
    additional_infos: Optional[dict] = None
    online_details: Optional[dict] = None
    
    datas: Optional[dict] = None
    items: List[OrderItemsReadModel] = []
    exchanged_items: Optional[List[ExchangedItemReadModel]] = None
    
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    
    model_config = ConfigDict(extra='allow')

    @model_validator(mode='before')
    @classmethod
    def map_order_data(cls, values: dict):
        if not isinstance(values, dict):
            return values
            
        datas = values.get('datas') or {}
        customer_id = values.get('customer_id')
        
        if not values.get('customer'):
            if 'customer' in datas:
                values['customer'] = datas['customer']
            elif customer_id:
                values['customer'] = {'customer_id': customer_id}
                
        return values
