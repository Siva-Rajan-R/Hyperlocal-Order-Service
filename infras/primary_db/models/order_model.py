from ..main import BASE
from sqlalchemy import (
    Column, String, Float, BigInteger,ARRAY,
    TIMESTAMP, func, ForeignKey, Identity
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

class Orders(BASE):
    __tablename__ = "orders"

    id = Column(String, primary_key=True)
    sequence_id = Column(BigInteger, Identity(always=True), nullable=False)

    ui_id = Column(String, nullable=False, index=True)
    shop_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=True)

    status = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    
    calculation_infos = Column(JSONB, nullable=False)
    charges_infos = Column(JSONB, nullable=False)
    item_infos = Column(JSONB, nullable=False, default={})
    payment_infos = Column(ARRAY(JSONB), nullable=False)

    date = Column(TIMESTAMP(timezone=True), nullable=False)

    additional_infos = Column(JSONB)

    created_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

    items = relationship(
        "OrderItems",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    returns = relationship(
        "Returns",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    exchanges = relationship(
        "Exchanges",
        back_populates="original_order",
        cascade="all, delete-orphan",
        foreign_keys="Exchanges.original_order_id"
    )

class OrderItems(BASE):
    __tablename__ = "orders_items"

    id = Column(String, primary_key=True)

    order_id = Column(
        String,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    product_id = Column(String, nullable=False)
    variant_id = Column(String)
    batch_id = Column(String)
    serialno_infos=Column(JSONB,nullable=True)

    gst = Column(String)

    quantity = Column(Float, nullable=False)
    
    buy_price = Column(Float, nullable=False)
    sell_price = Column(Float, nullable=False)

    additional_infos = Column(JSONB)

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

    order = relationship(
        "Orders",
        back_populates="items"
    )

    return_items = relationship(
        "ReturnItems",
        back_populates="order_item",
        cascade="all, delete-orphan"
    )

    exchange_items = relationship(
        "ExchangeItems",
        back_populates="order_item",
        cascade="all, delete-orphan"
    )

class Returns(BASE):
    __tablename__="returns"
    id = Column(String, primary_key=True)
    ui_id = Column(String, nullable=False, index=True)
    sequence_id = Column(BigInteger, Identity(always=True), nullable=False)
    order_id = Column(String, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=True)

    total_refund_amount = Column(Float, nullable=False, default=0.0)
    total_refund_qty=Column(Float, nullable=False, default=0.0)
    payment_infos = Column(JSONB, nullable=False)
    status = Column(String, nullable=False)
    
    created_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

    order = relationship(
        "Orders",
        back_populates="returns"
    )

    items = relationship(
        "ReturnItems",
        back_populates="return_order",
        cascade="all, delete-orphan"
    )

class ReturnItems(BASE):
    __tablename__="return_items"
    id = Column(String, primary_key=True)
    return_id = Column(String, ForeignKey("returns.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(String, ForeignKey("orders_items.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String, nullable=False)
    
    quantity = Column(Float, nullable=False)
    refund_amount = Column(Float, nullable=False, default=0.0)
    reason = Column(String, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

    return_order = relationship(
        "Returns",
        back_populates="items"
    )

    order_item = relationship(
        "OrderItems",
        back_populates="return_items"
    )

class Exchanges(BASE):
    __tablename__="exchanges"
    id = Column(String, primary_key=True)
    ui_id = Column(String, nullable=False, index=True)
    sequence_id = Column(BigInteger, Identity(always=True), nullable=False)
    original_order_id = Column(String, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    replacement_order_id = Column(String, nullable=False)
    shop_id = Column(String, nullable=False)
    customer_id = Column(String, nullable=True)

    total_exchanged_amount = Column(Float, nullable=False, default=0.0)
    total_exchanged_qty = Column(Float, nullable=False, default=0.0)
    total_replacement_amount = Column(Float, nullable=False, default=0.0)
    total_replacement_qty=Column(Float, nullable=False, default=0.0)

    payment_infos = Column(JSONB, nullable=False)
    payment_status=Column(String,nullable=True)
    reason = Column(String, nullable=True)
    status = Column(String, nullable=False)

    created_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

    original_order = relationship(
        "Orders",
        back_populates="exchanges",
        foreign_keys=[original_order_id]
    )

    items = relationship(
        "ExchangeItems",
        back_populates="exchange_order",
        cascade="all, delete-orphan"
    )

class ExchangeItems(BASE):
    __tablename__="exchange_items"
    id = Column(String, primary_key=True)
    exchange_id = Column(String, ForeignKey("exchanges.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(String, ForeignKey("orders_items.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String, nullable=False)

    quantity = Column(Float, nullable=False)
    exchange_amount=Column(Float, nullable=False, default=0.0)
    
    reason = Column(String, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

    exchange_order = relationship(
        "Exchanges",
        back_populates="items"
    )

    order_item = relationship(
        "OrderItems",
        back_populates="exchange_items"
    )
