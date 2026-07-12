import httpx
from fastapi import APIRouter, HTTPException, Depends
from typing import Annotated, Optional
from datetime import datetime, timezone, timedelta
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from hyperlocal_platform.core.models.req_res_models import SuccessResponseTypDict, BaseResponseTypDict, ErrorResponseTypDict
from infras.caching.models.cart_model import OrderCartCacheModel
from infras.primary_db.main import AsyncSession, get_pg_async_session
from pydantic import BaseModel
from schemas.v1.request_scheams.cart_schema import CartCancelRequest,CartCompleteRequest,CartRemoveRequest,CartReserveRequest,CartSerialNoInfos
from icecream import ic


BASE_URL="http://127.0.0.1:8004/inventories/inventories"
TTL_MINUTES = 3

async def create_reservation(data:CartReserveRequest):
    cart = OrderCartCacheModel(data.session_id)
    existing_cart = await cart.get_cart()
    ic(existing_cart)
    if existing_cart is None:
        raise HTTPException(status_code=400, detail="Invalid or expired session")
    
    # Fetch product to validate sub units
    product_data = {}
    async with httpx.AsyncClient() as client:
        try:
            prod_res = await client.get(f"{BASE_URL}/by/id/{data.shop_id}/{data.product_id}")
            if prod_res.status_code == 200:
                product_data = prod_res.json().get("data", {})
        except Exception as e:
            ic(f"Error fetching product data for unit validation: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve product data for unit validation")

    if not product_data:
        raise HTTPException(status_code=404, detail="Product not found")

    unit_infos = product_data.get("unit_infos", {})
    base_unit_name = unit_infos.get("name", "")
    sub_units = unit_infos.get("sub_units", []) or []

    conversion_factor = 1.0
    if data.unit:
        if data.unit.lower() == base_unit_name.lower():
            conversion_factor = 1.0
        else:
            matched_sub = next((su for su in sub_units if su and su.get("name", "").lower() == data.unit.lower()), None)
            if not matched_sub:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid unit '{data.unit}'. Configured base unit: '{base_unit_name}', sub units: {[su.get('name') for su in sub_units if su]}"
                )
            conversion_factor = float(matched_sub.get("factor", 1.0))

    base_qty = data.qty * conversion_factor

    # Expires logic
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTES)
        
    # Only reserve inventory if we are reducing stock
    payload = {
        "session_id": data.session_id,
        "product_id": data.product_id,
        "variant_id": data.variant_id,
        "batch_id": data.batch_id,
        "shop_id": data.shop_id,
        "qty": base_qty,
        "serialno_infos":[sn.model_dump(mode="json") for sn in data.serialno_infos] if data.serialno_infos else None,
        "expires_at": expires_at.isoformat()
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{BASE_URL}/reservations/reserve", json=payload)
            ic(response)
            ic(response.status_code)
            ic(response.url)
            ic(response.text)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Failed to communicate with Inventory Service: {e}")

    # Add to cart
    cart_item = data.model_dump(mode="json")
    cart_item["qty"] = base_qty
    cart_item["entered_qty"] = data.qty
    cart_item["entered_unit"] = data.unit
    await cart.add_or_update_item(item=cart_item, ttl=TTL_MINUTES * 60)

    return True




async def commit_reservation(session_id:str):
    cart = OrderCartCacheModel(session_id)
    items = await cart.get_cart()
    
    if items is None or len(items) == 0:
        raise HTTPException(status_code=400, detail="Cart is empty or session expired")

    # 1. Commit reservations in inventory service
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{BASE_URL}/reservations/commit", json={"session_id": session_id,"entity_name":"OFFLINE_SALES",'record_stock':True})
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"Failed to commit inventory reservations: {e}")

    # 3. Clean up Redis
    await cart.delete_cart()

    return True




async def remove_reservation_item(data:CartRemoveRequest):
    cart = OrderCartCacheModel(data.session_id)
    
    # Release the specific reservation item
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "session_id": data.session_id,
                "product_id": data.product_id,
                "variant_id": data.variant_id,
                "batch_id": data.batch_id
            }
            await client.post(f"{BASE_URL}/reservations/release-item", json=payload)
        except httpx.HTTPError:
            pass # Graceful failure
            
    await cart.remove_item(
        product_id=data.product_id, 
        variant_id=data.variant_id, 
        batch_id=data.batch_id, 
        ttl=TTL_MINUTES * 60
    )

    return True



async def cancel_reservation(data:CartCancelRequest):
    cart = OrderCartCacheModel(data.session_id)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{BASE_URL}/reservations/release", json={"session_id": data.session_id})
        except httpx.HTTPError as e:
            pass # Graceful failure
            
    await cart.delete_cart()

    return True