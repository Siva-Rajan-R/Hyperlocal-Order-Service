import httpx
from icecream import ic


BASE_URL="http://127.0.0.1:8010"
async def get_ui_id(shop_id:str,entity_name:str="ORDER"):
    try:
        async with httpx.AsyncClient() as request:
            response=await request.get(f"{BASE_URL}/shop-ui-ids/next/{shop_id}/{entity_name}")
            ic("product ui id => ",response)
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data:
                    return data["data"]

            return False
    except Exception as e:
        ic(f"Error fetching product ui id: {e}")
    return {}

async def get_shop_category(shop_id:str, category_id:str):
    try:
        async with httpx.AsyncClient() as request:
            response=await request.get(f"{BASE_URL}/shop-categories/{shop_id}/{category_id}")
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data:
                    return data["data"]
            return False
    except Exception as e:
        ic(f"Error fetching shop category: {e}")
    return {}

async def get_shop_unit(shop_id:str, unit_id:str):
    try:
        async with httpx.AsyncClient() as request:
            response=await request.get(f"{BASE_URL}/shop-units/{shop_id}/{unit_id}")
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data:
                    return data["data"]
            return False
    except Exception as e:
        ic(f"Error fetching shop unit: {e}")
    return {}