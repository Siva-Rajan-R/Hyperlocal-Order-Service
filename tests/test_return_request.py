import pytest
import uuid
import sys
import os
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

# Ensure paths
base_dir = os.path.abspath('.')
order_service_dir = os.path.join(base_dir, 'Apis', 'Hyperlocal-Order-Service')
site_pkgs = os.path.join(order_service_dir, '.venv', 'Lib', 'site-packages')
sys.path.insert(0, site_pkgs)
sys.path.insert(0, order_service_dir)
sys.path.insert(0, base_dir)

from schemas.v1.request_scheams.order_schema import (
    CreateReturnRequestSchema,
    CustomerReturnItemSchema,
    UpdateReturnRequestStatusSchema
)
from infras.read_db.repos.return_request_repo import ReturnRequestRepo

@pytest.fixture
def sample_order():
    return {
        "id": "ord-uuid-1234",
        "ui_id": "ORD-5544",
        "shop_id": "shop-test-1",
        "customer_id": "cust-99",
        "customer_name": "Sivarajan",
        "customer_number": "+919876543210",
        "status": "DELIVERED",
        "origin": "ONLINE",
        "online_details": {
            "name": "Sivarajan",
            "phone": "+919876543210",
            "email": "siva@example.com"
        },
        "items": [
            {
                "id": "item-1",
                "product_id": "prod-1",
                "name": "Organic Honey 500g",
                "variant_infos": {"variant_name": "500g Glass Jar"},
                "quantity": 2.0,
                "sell_price": 350.0,
                "total_amount": 700.0,
                "entered_unit": "jar"
            },
            {
                "id": "item-2",
                "product_id": "prod-2",
                "name": "Basmati Rice 5kg",
                "variant_infos": {"variant_name": "5kg Bag"},
                "quantity": 3.0,
                "sell_price": 450.0,
                "total_amount": 1350.0,
                "entered_unit": "bag"
            }
        ]
    }


@pytest.mark.asyncio
async def test_create_return_request_success(sample_order):
    mock_orders = MagicMock()
    mock_orders.find_one = AsyncMock(return_value=sample_order)
    mock_orders.update_one = AsyncMock(return_value=MagicMock())

    mock_returns = MagicMock()
    mock_returns.insert_one = AsyncMock(return_value=MagicMock())

    ReturnRequestRepo.orders_col = mock_orders
    ReturnRequestRepo.return_requests_col = mock_returns

    req1 = CreateReturnRequestSchema(
        order_id="ord-uuid-1234",
        shop_id="shop-test-1",
        description="Damaged packaging during delivery",
        items=[
            CustomerReturnItemSchema(order_item_id="item-1", quantity=1.0, reason="Broken jar lid"),
            CustomerReturnItemSchema(order_item_id="item-2", quantity=2.0, reason="Torn rice sack")
        ]
    )
    res1 = await ReturnRequestRepo.create_request(req1)
    assert res1["order_id"] == "ord-uuid-1234"
    assert res1["order_ui_id"] == "ORD-5544"
    assert res1["status"] == "PENDING"
    assert res1["customer_name"] == "Sivarajan"
    assert res1["customer_phone"] == "+919876543210"
    assert len(res1["items"]) == 2
    assert res1["items"][0]["product_name"] == "Organic Honey 500g"
    assert res1["items"][0]["quantity"] == 1.0
    assert res1["items"][0]["price"] == 350.0
    assert res1["items"][0]["total_amount"] == 350.0
    assert res1["items"][1]["product_name"] == "Basmati Rice 5kg"
    assert res1["items"][1]["quantity"] == 2.0
    assert res1["items"][1]["price"] == 450.0
    assert res1["items"][1]["total_amount"] == 900.0


@pytest.mark.asyncio
async def test_reject_when_item_not_present_in_order(sample_order):
    mock_orders = MagicMock()
    mock_orders.find_one = AsyncMock(return_value=sample_order)
    ReturnRequestRepo.orders_col = mock_orders

    req2 = CreateReturnRequestSchema(
        order_id="ord-uuid-1234",
        shop_id="shop-test-1",
        description="Returning wrong product",
        items=[
            CustomerReturnItemSchema(order_item_id="non-existent-item-999", quantity=1.0)
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        await ReturnRequestRepo.create_request(req2)
    assert exc_info.value.status_code == 400
    assert "not present in order" in exc_info.value.detail
    assert "rejected" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_reject_when_quantity_exceeds_ordered(sample_order):
    mock_orders = MagicMock()
    mock_orders.find_one = AsyncMock(return_value=sample_order)
    ReturnRequestRepo.orders_col = mock_orders

    req3 = CreateReturnRequestSchema(
        order_id="ord-uuid-1234",
        shop_id="shop-test-1",
        description="Return too many items",
        items=[
            CustomerReturnItemSchema(order_item_id="item-1", quantity=10.0)
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        await ReturnRequestRepo.create_request(req3)
    assert exc_info.value.status_code == 400
    assert "exceeds ordered quantity" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reject_when_no_items_or_no_description():
    req_no_items = CreateReturnRequestSchema(order_id="o1", description="", items=[])
    with pytest.raises(HTTPException) as exc1:
        await ReturnRequestRepo.create_request(req_no_items)
    assert exc1.value.status_code == 400

    req_no_desc = CreateReturnRequestSchema(
        order_id="o1",
        description="   ",
        items=[CustomerReturnItemSchema(order_item_id="i1", quantity=1.0)]
    )
    with pytest.raises(HTTPException) as exc2:
        await ReturnRequestRepo.create_request(req_no_desc)
    assert exc2.value.status_code == 400


@pytest.mark.asyncio
async def test_update_status_accept_and_reject():
    req_doc = {
        "id": "req-uuid-8888",
        "order_id": "ord-uuid-1234",
        "status": "PENDING",
        "status_history": []
    }
    mock_returns = MagicMock()
    mock_returns.find_one = AsyncMock(side_effect=[
        req_doc,
        {**req_doc, "status": "ACCEPTED", "admin_notes": "Accepted. Pickup scheduled."},
        {**req_doc, "status": "ACCEPTED"},
        {**req_doc, "status": "REJECTED", "admin_notes": "Rejected. Item seal was broken."}
    ])
    mock_returns.update_one = AsyncMock(return_value=MagicMock())
    ReturnRequestRepo.return_requests_col = mock_returns

    accept_res = await ReturnRequestRepo.update_status(
        request_id="req-uuid-8888",
        data=UpdateReturnRequestStatusSchema(status="ACCEPTED", admin_notes="Accepted. Pickup scheduled."),
        user_info={"name": "Merchant Admin"}
    )
    assert accept_res["status"] == "ACCEPTED"
    assert accept_res["admin_notes"] == "Accepted. Pickup scheduled."

    reject_res = await ReturnRequestRepo.update_status(
        request_id="req-uuid-8888",
        data=UpdateReturnRequestStatusSchema(status="REJECTED", admin_notes="Rejected. Item seal was broken."),
        user_info={"name": "Merchant Admin"}
    )
    assert reject_res["status"] == "REJECTED"
    assert reject_res["admin_notes"] == "Rejected. Item seal was broken."


@pytest.mark.asyncio
async def test_reject_invalid_status_transition():
    with pytest.raises(HTTPException) as exc_info:
        await ReturnRequestRepo.update_status(
            request_id="req-uuid-8888",
            data=UpdateReturnRequestStatusSchema(status="INVALID_STATUS")
        )
    assert exc_info.value.status_code == 400
    assert "Invalid status" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_by_shop_id_and_order_id():
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[
        {"id": "r1", "order_id": "ord-uuid-1234", "status": "PENDING"},
        {"id": "r2", "order_id": "ord-uuid-1234", "status": "ACCEPTED"}
    ])
    mock_returns = MagicMock()
    mock_returns.find = MagicMock(return_value=mock_cursor)
    ReturnRequestRepo.return_requests_col = mock_returns

    fetched = await ReturnRequestRepo.get_by_shop_id(shop_id="shop-test-1", status="PENDING")
    assert len(fetched) == 2
    query_dict = mock_returns.find.call_args[0][0]
    assert query_dict["shop_id"] == "shop-test-1"
    assert query_dict["status"] == "PENDING"
