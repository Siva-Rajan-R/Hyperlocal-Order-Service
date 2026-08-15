import pytest
import uuid
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import HTTPException
from schemas.v1.request_scheams.order_schema import CreateExchangeSchema
from infras.primary_db.services.exchange_service import ExchangeService

@pytest.fixture
def mock_session():
    return AsyncMock()

@pytest.fixture
def exchange_service(mock_session):
    return ExchangeService(session=mock_session)

@pytest.mark.asyncio
@patch('infras.primary_db.services.exchange_service.OrdersRepo')
@patch('infras.primary_db.services.exchange_service.OrderReadDbRepo')
@patch('infras.primary_db.services.exchange_service.get_ui_id', new_callable=AsyncMock)
@patch('infras.primary_db.services.exchange_service.httpx.AsyncClient')
@patch('infras.primary_db.services.exchange_service.SagaProducer.emit', new_callable=AsyncMock)
async def test_equal_exchange(mock_emit, mock_http_client, mock_get_ui_id, mock_read_repo, mock_orders_repo, exchange_service):
    # Mock data
    original_order_id = str(uuid.uuid4())
    shop_id = "shop123"
    order_item_id = str(uuid.uuid4())

    mock_orders_repo_instance = mock_orders_repo.return_value
    mock_orders_repo_instance.getby_id = AsyncMock(return_value={
        "id": original_order_id,
        "shop_id": shop_id,
        "customer_id": "cust123",
        "items": [{
            "id": order_item_id,
            "product_id": "prod1",
            "quantity": 5.0,
            "sell_price": 100.0,
        }]
    })

    mock_read_repo.get_by_id = AsyncMock(return_value={
        "id": original_order_id,
        "returns": [],
        "exchanges": []
    })

    mock_get_ui_id.return_value = {"prefix": "EXC", "current_number": 1}

    mock_client_instance = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "name": "Prod 2",
            "pricing_infos": {"sell_price": 100.0, "buy_price": 50.0},
            "stock_infos": {"physical_stocks": 10.0}
        }
    }
    mock_client_instance.get = AsyncMock(return_value=mock_response)
    mock_http_client.return_value.__aenter__.return_value = mock_client_instance

    data = MagicMock()
    data.original_order_id = original_order_id
    data.shop_id = shop_id
    data.exchange_items = [MagicMock(model_dump=lambda: {"order_item_id": order_item_id, "quantity": 1.0, "unit": None}, serialno_infos=[])]
    data.replacement_items = [MagicMock(model_dump=lambda: {}, product_id="prod2", quantity=1.0, unit=None, batch_id=None, variant_id=None, serialno_infos=[])]
    data.payments = []
    data.reason = "test"

    res = await exchange_service.process_exchange(data)
    
    assert res is True
    # Verify saga was emitted
    mock_emit.assert_called_once()
    saga_payload = mock_emit.call_args[1]["saga_payload"].data
    assert saga_payload["exchange_data"]["amount_diff"] == 0.0
    assert saga_payload["exchange_data"]["payment_status"] == "COMPLETED"

@pytest.mark.asyncio
@patch('infras.primary_db.services.exchange_service.OrdersRepo')
@patch('infras.primary_db.services.exchange_service.OrderReadDbRepo')
@patch('infras.primary_db.services.exchange_service.get_ui_id', new_callable=AsyncMock)
@patch('infras.primary_db.services.exchange_service.httpx.AsyncClient')
async def test_exceeding_quantity_raises_error(mock_http_client, mock_get_ui_id, mock_read_repo, mock_orders_repo, exchange_service):
    original_order_id = str(uuid.uuid4())
    shop_id = "shop123"
    order_item_id = str(uuid.uuid4())

    mock_orders_repo_instance = mock_orders_repo.return_value
    mock_orders_repo_instance.getby_id = AsyncMock(return_value={
        "id": original_order_id,
        "shop_id": shop_id,
        "items": [{
            "id": order_item_id,
            "product_id": "prod1",
            "quantity": 5.0,
            "sell_price": 100.0,
        }]
    })

    # Simulate that 4 items were already exchanged
    mock_read_repo.get_by_id = AsyncMock(return_value={
        "id": original_order_id,
        "returns": [],
        "exchanges": [{"items": [{"order_item_id": order_item_id, "quantity": 4.0}]}]
    })

    mock_get_ui_id.return_value = {"prefix": "EXC", "current_number": 1}

    data = MagicMock()
    data.original_order_id = original_order_id
    data.shop_id = shop_id
    data.exchange_items = [MagicMock(model_dump=lambda: {"order_item_id": order_item_id, "quantity": 2.0, "unit": None}, serialno_infos=[])]

    with pytest.raises(HTTPException) as excinfo:
        await exchange_service.process_exchange(data)
    
    assert excinfo.value.status_code == 400
    assert "exceeds available qty" in str(excinfo.value.detail)

@pytest.mark.asyncio
@patch('infras.primary_db.services.exchange_service.OrdersRepo')
@patch('infras.primary_db.services.exchange_service.OrderReadDbRepo')
@patch('infras.primary_db.services.exchange_service.get_ui_id', new_callable=AsyncMock)
@patch('infras.primary_db.services.exchange_service.httpx.AsyncClient')
@patch('infras.primary_db.services.exchange_service.SagaProducer.emit', new_callable=AsyncMock)
async def test_customer_pays_difference(mock_emit, mock_http_client, mock_get_ui_id, mock_read_repo, mock_orders_repo, exchange_service):
    # Test where replacement costs more
    original_order_id = str(uuid.uuid4())
    shop_id = "shop123"
    order_item_id = str(uuid.uuid4())

    mock_orders_repo_instance = mock_orders_repo.return_value
    mock_orders_repo_instance.getby_id = AsyncMock(return_value={
        "id": original_order_id,
        "shop_id": shop_id,
        "customer_id": "cust123",
        "items": [{
            "id": order_item_id,
            "product_id": "prod1",
            "quantity": 1.0,
            "sell_price": 100.0,
        }]
    })

    mock_read_repo.get_by_id = AsyncMock(return_value={"id": original_order_id, "returns": [], "exchanges": []})
    mock_get_ui_id.return_value = {"prefix": "EXC", "current_number": 1}

    mock_client_instance = MagicMock()
    mock_response = MagicMock()
    # Replacement costs 150
    mock_response.json.return_value = {
        "data": {
            "name": "Prod 2",
            "pricing_infos": {"sell_price": 150.0},
            "stock_infos": {"physical_stocks": 10.0}
        }
    }
    mock_client_instance.get = AsyncMock(return_value=mock_response)
    mock_http_client.return_value.__aenter__.return_value = mock_client_instance

    data = MagicMock()
    data.original_order_id = original_order_id
    data.shop_id = shop_id
    data.exchange_items = [MagicMock(model_dump=lambda: {"order_item_id": order_item_id, "quantity": 1.0, "unit": None}, serialno_infos=[])]
    data.replacement_items = [MagicMock(model_dump=lambda: {}, product_id="prod2", quantity=1.0, unit=None, batch_id=None, variant_id=None, serialno_infos=[])]
    data.payments = [MagicMock(model_dump=lambda: {}, method="CASH", amount=50.0)]
    data.reason = "test"

    res = await exchange_service.process_exchange(data)
    assert res is True
    
    saga_payload = mock_emit.call_args[1]["saga_payload"].data
    assert saga_payload["exchange_data"]["amount_diff"] == 50.0
    assert saga_payload["exchange_data"]["payment_status"] == "COMPLETED"
