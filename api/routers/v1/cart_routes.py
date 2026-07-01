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
