from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class OrderStatsReadModel(BaseModel):
    shop_id: str
    total_orders: int = 0
    total_order_value: float = 0.0
    total_returns: int = 0
    total_exchanged: int = 0
    registered_customer_count: int = 0
    walkin_customer_count: int = 0
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(extra='allow')
