import pytest
import uuid
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import HTTPException
from infras.primary_db.services.return_service import ReturnService, resolve_item_unit_price, resolve_item_gst_rate


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def return_service(mock_session):
    return ReturnService(session=mock_session)


def test_resolve_item_unit_price_subunit_conversion():
    """
    Test scenario matching ORD-100009:
    - Base unit: Kilogram, sub_unit: g (factor=0.001)
    - Item quantity in base unit: 0.5 kg
    - calculation_infos: entered 500g, final_inclusive: 50.0 (₹50 total billed)
    Effective price per base unit should be ₹100.0/kg.
    """
    item_dict = {
        "id": "item-123",
        "product_id": "prod-1",
        "quantity": 0.5,
        "sell_price": 150.0,
        "total_amount": 75.0,
        "unit_infos": {
            "name": "Kilogram",
            "sub_units": [
                {"name": "g", "factor": 0.001},
                {"name": "mg", "factor": 1e-06}
            ]
        }
    }
    calculation_infos = {
        "items": [
            {
                "product_id": "prod-1",
                "qty": 500,
                "unit": "g",
                "price": 0.15,
                "final_inclusive": 50.0,
                "product_discount_amount": 25.0
            }
        ]
    }
    read_db_order = {
        "items": [item_dict],
        "calculation_infos": calculation_infos
    }

    unit_price = resolve_item_unit_price(item_dict, calculation_infos, read_db_order)
    assert unit_price == 100.0

    # Returning 250g with factor 0.001 gives inc_quantity = 0.25 kg
    inc_quantity = 250 * 0.001
    return_amount = round(inc_quantity * unit_price, 2)
    assert return_amount == 25.0


def test_resolve_item_unit_price_standard_unit():
    """
    Standard pieces scenario:
    - Base unit: Piece
    - Quantity: 2 pieces
    - calculation_infos: qty: 2, final_inclusive: 200.0
    Price per base unit should be 100.0.
    """
    item_dict = {
        "id": "item-456",
        "product_id": "prod-2",
        "quantity": 2.0,
        "sell_price": 100.0,
        "total_amount": 200.0
    }
    calculation_infos = {
        "items": [
            {
                "order_item_id": "item-456",
                "product_id": "prod-2",
                "qty": 2.0,
                "final_inclusive": 200.0
            }
        ]
    }

    unit_price = resolve_item_unit_price(item_dict, calculation_infos)
    assert unit_price == 100.0


@pytest.mark.asyncio
@patch('infras.primary_db.services.return_service.OrdersRepo')
@patch('infras.primary_db.services.return_service.OrderReadDbRepo')
@patch('infras.primary_db.services.return_service.get_ui_id', new_callable=AsyncMock)
@patch('infras.primary_db.services.return_service.SagaProducer.emit', new_callable=AsyncMock)
async def test_process_return_subunit_refund_calculation(mock_emit, mock_get_ui_id, mock_read_repo, mock_orders_repo, return_service):
    """
    End-to-end test of ReturnService.process_return with sub-units:
    - User returns 250g of a 500g item billed at ₹50.
    - Required refund is ₹25.00.
    - User submits ₹25.00 refund payment.
    - Should succeed without raising "Entered refund amount does not match required return total".
    """
    order_id = str(uuid.uuid4())
    shop_id = "shop123"
    order_item_id = str(uuid.uuid4())

    item_dict = {
        "id": order_item_id,
        "product_id": "prod-1",
        "variant_id": None,
        "batch_id": None,
        "quantity": 0.5,
        "sell_price": 150.0,
        "total_amount": 75.0,
        "unit_infos": {
            "name": "Kilogram",
            "sub_units": [
                {"name": "g", "factor": 0.001}
            ]
        }
    }

    calc_infos = {
        "items": [
            {
                "product_id": "prod-1",
                "qty": 500,
                "unit": "g",
                "price": 0.15,
                "final_inclusive": 50.0,
                "product_discount_amount": 25.0
            }
        ]
    }

    mock_orders_repo_instance = mock_orders_repo.return_value
    mock_orders_repo_instance.getby_id = AsyncMock(return_value={
        "id": order_id,
        "shop_id": shop_id,
        "customer_id": None,
        "date": "2026-11-15",
        "origin": "OFFLINE",
        "status": "COMPLETED",
        "additional_infos": {},
        "calculation_infos": calc_infos,
        "items": [item_dict]
    })

    mock_read_repo.get_by_id = AsyncMock(return_value={
        "id": order_id,
        "shop_id": shop_id,
        "items": [item_dict],
        "calculation_infos": calc_infos,
        "returns": [],
        "exchanges": []
    })

    mock_get_ui_id.return_value = {"prefix": "RET", "current_number": 1}

    # Request data: return 250 g for 25.0 refund
    item_req = MagicMock()
    item_req.model_dump = lambda: {
        "order_item_id": order_item_id,
        "quantity": 250,
        "unit": "g",
        "reason": "Customer Request",
        "serialno_infos": []
    }

    data = MagicMock()
    data.order_id = order_id
    data.shop_id = shop_id
    data.items = [item_req]
    data.payment_infos = {"CASH": 25.0}

    await return_service.process_return(data)

    assert mock_emit.called
    emitted_payload = mock_emit.call_args[1]["saga_payload"].data
    return_toadd = emitted_payload["order_return"]["return_toadd"]
    return_items_toadd = emitted_payload["order_return"]["return_items_toadd"]

    assert return_toadd["total_refund_amount"] == 25.0
    assert return_toadd["total_refund_qty"] == 0.25
    assert len(return_items_toadd) == 1
    assert return_items_toadd[0]["quantity"] == 0.25
    assert return_items_toadd[0]["entered_qty"] == 250
    assert return_items_toadd[0]["entered_unit"] == "g"
    assert return_items_toadd[0]["refund_amount"] == 25.0
