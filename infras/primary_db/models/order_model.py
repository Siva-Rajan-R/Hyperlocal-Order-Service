from sqlalchemy import Column, String,ForeignKey,Integer,TIMESTAMP,func,Float,BigInteger,Identity,ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from ..main import BASE

class Orders(BASE):
    __tablename__="orders"
    id=Column(String,primary_key=True)
    sequence_id=Column(BigInteger,Identity(always=True),nullable=False)
    ui_id=Column(BigInteger,Identity(always=True),nullable=False)
    shop_id=Column(String,nullable=False)
    total_buyprice=Column(Float,nullable=False)
    total_sellprice=Column(Float,nullable=False)
    total_quantity=Column(BigInteger,nullable=False)
    customer_id=Column(String,nullable=True)
    status=Column(String,nullable=False)
    origin=Column(String,nullable=False)
    type=Column(String,nullable=True)
    payment_method=Column(String,nullable=False)

    created_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())


class OrderItems(BASE):
    __tablename__="orders_products"
    id=Column(String,primary_key=True)
    order_id=Column(String,nullable=False)
    inventory_id=Column(String,nullable=False)
    variant_id=Column(String,nullable=True)
    batch_id=Column(String,nullable=True)
    serialno_id=Column(String,nullable=True)
    barcode=Column(String,nullable=True)

    serial_numbers=Column(ARRAY(String),nullable=True)


    buy_price=Column(Float,nullable=False)
    sell_price=Column(Float,nullable=False)

    gst=Column(String,nullable=True)

    quantity=Column(BigInteger,nullable=False)

    status=Column(String,nullable=False)
    created_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())



class ExchangedOrderItems(BASE):
    __tablename__="exchanged_order_items"
    id=Column(String,primary_key=True)

    parent_order_id=Column(String,nullable=False)
    item_id=Column(String,nullable=False)
    replacement_order_id =Column(String,nullable=False)

    created_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at=Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

