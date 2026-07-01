from pydantic import BaseModel
from typing import Optional,List



class CartSerialNoInfos(BaseModel):
    id:str
    name:str

class CartReserveRequest(BaseModel):
    session_id: str
    shop_id: str
    product_id: str
    variant_id: Optional[str] = None
    batch_id: Optional[str] = None
    serialno_infos:Optional[CartSerialNoInfos]=None
    qty: float

class CartCompleteRequest(BaseModel):
    session_id: str
    shop_id: str
    description: Optional[str] = None

class CartCancelRequest(BaseModel):
    session_id: str

class CartRemoveRequest(BaseModel):
    session_id: str
    product_id: str
    variant_id: Optional[str] = None
    batch_id: Optional[str] = None