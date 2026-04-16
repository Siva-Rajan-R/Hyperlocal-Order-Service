from pydantic import BaseModel

class CachingBillingSchema(BaseModel):
    qty:int
    product_price:float
    barcode:str
    product_name:str
    total_price:float