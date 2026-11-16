import pytest
import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import HTTPException
from schemas.v1.request_scheams.order_schema import CreateOrderSchema
from core.data_formats.enums.order_enum import OrderStatusEnum, OrderOriginEnum
from infras.primary_db.services.order_service import OrdersService


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def order_service(mock_session):
    return OrdersService(session=mock_session)


@pytest.mark.asyncio
async def test_order_overpayment_rejected_dict(order_service):
    """
    If total bill is 5000, and payments are CASH=5000, ON_CREDIT=1000 (total 6000),
    OrdersService.create must raise HTTPException 400 Bad Request.
    """
    order_data = CreateOrderSchema(
        shop_id="test-shop-id",
        session_id="test-session-id",
        customer_id="test-cust-id",
        status=OrderStatusEnum.COMPLETED,
        origin=OrderOriginEnum.OFFLINE,
        calculation_infos={
            "grand_total": 5000.0,
            "total": 5000.0,
        },
        payment_infos={
            "CASH": 5000.0,
            "ON_CREDIT": 1000.0,
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await order_service.create(data=order_data)

    assert exc_info.value.status_code == 400
    assert "cannot exceed the bill amount" in exc_info.value.detail
    assert "₹6,000.00" in exc_info.value.detail
    assert "₹5,000.00" in exc_info.value.detail


@pytest.mark.asyncio
async def test_order_overpayment_rejected_list(order_service):
    """
    Test when payment_infos is passed as list of objects exceeding bill total.
    """
    order_data = CreateOrderSchema(
        shop_id="test-shop-id",
        session_id="test-session-id",
        customer_id="test-cust-id",
        status=OrderStatusEnum.COMPLETED,
        origin=OrderOriginEnum.OFFLINE,
        calculation_infos={
            "grand_total": 5000.0,
        },
        payment_infos=[
            {"mode": "cash", "amount": 5000.0},
            {"mode": "credit", "amount": 1000.0},
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await order_service.create(data=order_data)

    assert exc_info.value.status_code == 400
    assert "cannot exceed the bill amount" in exc_info.value.detail


@pytest.mark.asyncio
async def test_order_payment_within_tolerance(order_service):
    """
    If total bill is 5000 and total paid is 5000.009 (within 0.01 tolerance),
    it should pass the payment check and proceed (failing later only at cart check).
    """
    order_data = CreateOrderSchema(
        shop_id="test-shop-id",
        session_id="nonexistent-session",
        customer_id="test-cust-id",
        status=OrderStatusEnum.COMPLETED,
        origin=OrderOriginEnum.OFFLINE,
        calculation_infos={
            "grand_total": 5000.0,
        },
        payment_infos={
            "CASH": 5000.005,
        }
    )

    # It passes payment validation and fails at empty cart check
    with pytest.raises(HTTPException) as exc_info:
        await order_service.create(data=order_data)

    # Empty cart check raises 400 with "Cart session is invalid, expired, or empty"
    assert exc_info.value.status_code == 400
    assert "Cart session is invalid" in str(exc_info.value.detail)
