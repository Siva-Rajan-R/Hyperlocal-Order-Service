import json
import base64
import urllib.parse
from fastapi import Header, Request
from typing import Optional, Dict, Any
from core.utils.user_context import current_user_ctx

async def get_current_user_info(
    request: Request,
    x_user_infos: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    Dependency to extract complete user context dictionary from gateway header, JWT token, or request context.
    """
    # 1. Try x-user-infos header
    if x_user_infos:
        try:
            raw_str = urllib.parse.unquote(x_user_infos)
            user_info = json.loads(raw_str)
            if isinstance(user_info, dict) and user_info:
                current_user_ctx.set(user_info)
                return user_info
        except Exception:
            pass

    # 2. Try Authorization header
    auth_header = authorization or request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token_parts = auth_header.split(" ")[1].split(".")
            if len(token_parts) == 3:
                padded = token_parts[1] + "=" * ((4 - len(token_parts[1]) % 4) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
                user_info = {
                    "user_id": payload.get("user_id") or payload.get("sub") or payload.get("id"),
                    "id": payload.get("user_id") or payload.get("sub") or payload.get("id"),
                    "name": payload.get("name") or payload.get("user_name") or payload.get("entity_name") or "",
                    "email": payload.get("email") or payload.get("user_email") or "",
                    "role": payload.get("role") or payload.get("entity_type") or "User"
                }
                current_user_ctx.set(user_info)
                return user_info
        except Exception:
            pass

    # 3. Fallback to existing ContextVar
    ctx = current_user_ctx.get()
    if isinstance(ctx, dict) and ctx:
        return ctx

    return {}

async def get_current_user_id(
    request: Request,
    x_user_infos: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    user_info = await get_current_user_info(request=request, x_user_infos=x_user_infos, authorization=authorization)
    return user_info.get("user_id") or user_info.get("id")
