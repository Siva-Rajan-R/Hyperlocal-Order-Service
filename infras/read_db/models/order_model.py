from pydantic import BaseModel, ConfigDict, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date

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

class OrderItemsReadModel(BaseModel):
    id: str
    inventory_id: str
    name: str = ""
    buy_price: float = 0.0
    sell_price: float = 0.0
    quantity: float = 0.0
    status: str
    reason: Optional[str] = None
    barcode: Optional[str] = None
    gst: Optional[str] = None
    
    variant_info: Optional[VariantInfo] = None
    batch_info: Optional[BatchInfo] = None
    serialno_info: Optional[SerialInfo] = None
    
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(extra='allow')
    
    @model_validator(mode='before')
    @classmethod
    def map_postgres_data(cls, values: dict):
        if not isinstance(values, dict):
            return values
            
        datas = values.get('datas') or {}
        
        if 'name' not in values and 'product_name' in datas:
            values['name'] = datas['product_name']
        if 'gst' not in values and 'gst' in datas:
            values['gst'] = datas['gst']
            
        variant_id = values.pop('variant_id', None)
        if variant_id and not values.get('variant_info'):
            values['variant_info'] = {
                'variant_id': variant_id,
                'variant_name': datas.get('variant_name', '')
            }
            
        batch_id = values.pop('batch_id', None)
        if batch_id and not values.get('batch_info'):
            values['batch_info'] = {
                'batch_id': batch_id,
                'batch_name': datas.get('batch_name', ''),
                'mfg_date': datas.get('manufacture_date') or datas.get('mfg_date'),
                'exp_date': datas.get('expiry_date') or datas.get('exp_date')
            }
            
        serialno_id = values.pop('serialno_id', None)
        if serialno_id and not values.get('serialno_info'):
            values['serialno_info'] = {
                'serialno_id': serialno_id,
                'serial_numbers': values.pop('serial_numbers', values.pop('inv_serial_numbers', []))
            }
            
        return values
class ReplacementOrderReadModel(BaseModel):
    id: str
    ui_id: Optional[str] = None
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
    total_buyprice: float = 0.0
    total_sellprice: float = 0.0
    total_quantity: float = 0.0
    customer_id: Optional[str] = None
    customer: Optional[dict] = None
    status: str
    origin: str
    type: Optional[str] = None
    payments: Dict[str, float] = {}
    datas: Optional[dict] = None
    items: List[OrderItemsReadModel] = []
    exchanged_items: Optional[List[ExchangedItemReadModel]] = None
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
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
                
        if 'customer_id' in values:
            values['customer_id'] = None
            
        return values
