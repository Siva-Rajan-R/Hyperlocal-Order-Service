import httpx
from icecream import ic
import os
from dotenv import load_dotenv
from typing import Optional, Dict, Any
load_dotenv()

BASE_URL = os.getenv("SHOPEMP_SERVICE_URL", "http://127.0.0.1:8001")

async def get_shop_info(shop_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as request:
            url = f"{BASE_URL}/shops/by/{shop_id}"
            ic(url)
            response = await request.get(url=url)
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data:
                    return data["data"]
            return None
    except Exception as e:
        ic(f"Error fetching shop info: {e}")
    return None
