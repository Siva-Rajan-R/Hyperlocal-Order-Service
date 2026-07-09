from fastapi import APIRouter, HTTPException
import httpx
from datetime import datetime, timezone, timedelta
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from hyperlocal_platform.core.models.req_res_models import SuccessResponseTypDict, BaseResponseTypDict
from infras.caching.models.cart_model import OrderCartCacheModel
from schemas.v1.request_scheams.cart_schema import CartRemoveRequest, CartCancelRequest,CartSerialNoInfos,CartCompleteRequest,CartReserveRequest
from integrations.stock_reservation import create_reservation,remove_reservation_item,cancel_reservation
from icecream import ic

router = APIRouter(
    tags=["Order Cart"],
    prefix="/cart"
)

INVENTORY_SERVICE_URL = "http://127.0.0.1:8000/inventories/inventories"
TTL_MINUTES = 15

@router.post('/init')
async def init_cart():
    session_id = generate_uuid()
    cart = OrderCartCacheModel(session_id)
    await cart.set_cart(items=[],ttl=TTL_MINUTES * 60)
    
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200, 
            success=True, 
            msg="Cart session initialized successfully"
        ),
        data={"session_id": session_id}
    )

@router.post('/add')
async def add_item(data:CartReserveRequest ):
    res=await create_reservation(data=data)
    ic(res)
    return SuccessResponseTypDict(detail=BaseResponseTypDict(status_code=200, success=True, msg="Item reserved and added to cart"))


@router.post('/remove')
async def remove_item(data: CartRemoveRequest):
    res=await remove_reservation_item(data=data)
    ic(res)
    return SuccessResponseTypDict(detail=BaseResponseTypDict(status_code=200, success=True, msg="Item removed from cart and reservation released"))

@router.post('/cancel')
async def cancel_cart(data: CartCancelRequest):
    res=await cancel_reservation(data=data)
    ic(res)
    return SuccessResponseTypDict(detail=BaseResponseTypDict(status_code=200, success=True, msg="Cart session cancelled"))

@router.get('/{session_id}')
async def get_cart_stored_order(session_id: str):
    cart = OrderCartCacheModel(session_id)
    items = await cart.get_cart()
    if items is None:
        raise HTTPException(status_code=404, detail="Cart session not found or expired")

    enriched_items = []
    async with httpx.AsyncClient() as client:
        for item in items:
            shop_id = item.get("shop_id")
            product_id = item.get("product_id")
            item_info = {}
            if shop_id and product_id:
                try:
                    url = f"http://127.0.0.1:8004/inventories/by/id/{shop_id}/{product_id}"
                    response = await client.get(url)
                    if response.status_code == 200:
                        res_json = response.json()
                        item_info = res_json.get("data", {})
                except Exception as e:
                    ic(f"Error fetching item info from inventory service: {e}")
            
            enriched_items.append({
                **item,
                "item_info": item_info
            })
            
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200,
            success=True,
            msg="Cart stored order fetched successfully"
        ),
        data={
            "session_id": session_id,
            "items": enriched_items
        }
    )

