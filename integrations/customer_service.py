import httpx
from icecream import ic
import os
from dotenv import load_dotenv
load_dotenv()


# BASE_URL="http://127.0.0.1:8006/customers"
BASE_URL = os.getenv("CUSTOMER_SERVICE_URL")
async def get_customer_info(shop_id:str,customer_id:str):
    try:
        async with httpx.AsyncClient() as request:
            url=f"{BASE_URL}/by/id/{shop_id}/{customer_id}"
            ic(url)
            response=await request.get(url=url)
            ic("product ui id => ",response.json())
            if response.status_code == 200:
                
                data = response.json()
                ic(data)
                if data and "data" in data:
                    return data["data"]
                
                

            return False
    except Exception as e:
        ic(f"Error fetching product ui id: {e}")
    return {}