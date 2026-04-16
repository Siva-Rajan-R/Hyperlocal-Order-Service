from typing import TypedDict


class OrderItemValueTypDict(TypedDict):
    product_name:str
    total_price:float
    quantity:int
    price:float
    barcode:str