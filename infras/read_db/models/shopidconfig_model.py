from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any

class ModuleConfigSchema(BaseModel):
    prefix: str
    start_from: int

class ShopIdConfigReadModel(BaseModel):
    shop_id: str
    config: Dict[str, ModuleConfigSchema] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
