import json
from fastapi import Header
from typing import Optional

async def get_current_user_id(x_user_infos: Optional[str] = Header(None)) -> Optional[str]:
    """
    Dependency to extract user_id from the gateway-injected x-user-infos header.
    """
    if not x_user_infos:
        return None
    try:
        user_info = json.loads(x_user_infos)
        return user_info.get("user_id")
    except Exception:
        return None
