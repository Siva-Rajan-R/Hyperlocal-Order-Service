from ...handlers.return_handler import HandleReturnRequest
from schemas.v1.request_scheams.order_schema import (
    CreateReturnSchema,
    CreateReturnRequestSchema,
    UpdateReturnRequestStatusSchema
)
from fastapi import APIRouter, Depends, Query, Request
from typing import Annotated, Optional, List, Dict, Any
from infras.primary_db.main import get_pg_async_session, AsyncSession
from core.utils.user_info import get_current_user_info
from infras.read_db.repos.return_request_repo import ReturnRequestRepo
from hyperlocal_platform.core.models.req_res_models import SuccessResponseTypDict, BaseResponseTypDict

router = APIRouter(
    prefix='/returns',
    tags=['Returns']
)

PG_SESSION = Annotated[AsyncSession, Depends(get_pg_async_session)]
SHOP_ID = "37d5519b-51a1-5854-982b-4d6524171017" # Consistent with existing implementation


# ── Customer Return Request Endpoints ────────────────────────────────────────

@router.post('/request')
@router.post('/requests')
async def create_return_request(
    data: CreateReturnRequestSchema,
    session: PG_SESSION,
    user_info: Dict[str, Any] = Depends(get_current_user_info)
):
    """
    Customer return request endpoint.
    Requires order_id, chosen items (must be present in the order), and detailed description.
    """
    res = await ReturnRequestRepo.create_request(data=data, session=session, user_info=user_info)
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=201,
            msg="Return request submitted successfully",
            success=True
        ),
        data=res
    )


@router.get('/requests/{shop_id}')
async def get_shop_return_requests(
    shop_id: str,
    status: Optional[str] = Query(None, description="Filter by status: PENDING, ACCEPTED, REJECTED, ALL"),
    order_id: Optional[str] = Query(None, description="Filter by order ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(1, ge=1)
):
    """
    Fetch return requests for a specific shop.
    """
    res = await ReturnRequestRepo.get_by_shop_id(
        shop_id=shop_id,
        status=status,
        order_id=order_id,
        limit=limit,
        offset=offset
    )
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200,
            msg="Return requests fetched successfully",
            success=True
        ),
        data=res
    )


@router.get('/requests/order/{order_id}')
async def get_order_return_requests(order_id: str):
    """
    Fetch return requests for a specific order.
    """
    res = await ReturnRequestRepo.get_by_order_id(order_id=order_id)
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200,
            msg="Order return requests fetched successfully",
            success=True
        ),
        data=res
    )


@router.get('/requests/detail/{request_id}')
async def get_return_request_detail(request_id: str):
    """
    Fetch detailed return request by ID.
    """
    res = await ReturnRequestRepo.get_by_id(request_id=request_id)
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200,
            msg="Return request detail fetched successfully",
            success=True
        ),
        data=res
    )


@router.put('/requests/{request_id}/status')
@router.patch('/requests/{request_id}/status')
async def update_return_request_status(
    request_id: str,
    data: UpdateReturnRequestStatusSchema,
    user_info: Dict[str, Any] = Depends(get_current_user_info)
):
    """
    Update status of a return request to ACCEPTED or REJECTED.
    """
    res = await ReturnRequestRepo.update_status(
        request_id=request_id,
        data=data,
        user_info=user_info
    )
    return SuccessResponseTypDict(
        detail=BaseResponseTypDict(
            status_code=200,
            msg=f"Return request status updated to {data.status.upper()}",
            success=True
        ),
        data=res
    )


# ── Standard In-Store Return Endpoints ────────────────────────────────────────

@router.post('/{shop_id}')
async def create_return_by_shop_id(
    shop_id: str,
    data: CreateReturnSchema,
    session: PG_SESSION,
    user_info: Dict[str, Any] = Depends(get_current_user_info)
):
    data.shop_id = shop_id
    user_id = user_info.get("user_id") or user_info.get("id") or ""
    return await HandleReturnRequest(session=session, shop_id=shop_id, cur_user_id=user_id, custom_user_info=user_info).create(data=data)


@router.post('')
async def create_return(
    data: CreateReturnSchema,
    session: PG_SESSION,
    user_info: Dict[str, Any] = Depends(get_current_user_info)
):
    shop_id = data.shop_id or SHOP_ID
    data.shop_id = shop_id
    user_id = user_info.get("user_id") or user_info.get("id") or ""
    return await HandleReturnRequest(session=session, shop_id=shop_id, cur_user_id=user_id, custom_user_info=user_info).create(data=data)
