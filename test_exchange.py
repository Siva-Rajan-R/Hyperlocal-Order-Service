import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8006"
PRODUCT_ID = "73879304-4d4f-5fd4-8887-a108d112c3b0"
SHOP_ID = "string"
CUSTOMER_ID = "00000000-0000-0000-0000-000000000001" # Mock

async def run_test():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("1. Initializing Cart...")
        res = await client.post(f"{BASE_URL}/cart/init", json={"shop_id": SHOP_ID, "origin": "ONLINE"})
        if res.status_code != 200:
            print(f"Cart init failed: {res.text}")
            return
        
        session_id = res.json()["data"]["session_id"]
        print(f"Session ID: {session_id}")

        print("\n2. Adding item to cart...")
        res = await client.post(f"{BASE_URL}/cart/add", json={
            "session_id": session_id,
            "shop_id": SHOP_ID,
            "product_id": PRODUCT_ID,
            "qty": 1.0
        })
        if res.status_code != 200:
            print(f"Cart add failed: {res.text}")
            return
        print("Item added successfully")

        print("\n3. Creating Original Order...")
        res = await client.post(f"{BASE_URL}/orders", json={
            "shop_id": SHOP_ID,
            "session_id": session_id,
            "customer_id": CUSTOMER_ID,
            "status": "COMPLETED",
            "origin": "ONLINE"
        })
        if res.status_code != 200:
            print(f"Order create failed: {res.text}")
            return
        
        order_data = res.json()["data"]
        order_id = order_data["id"]
        # Get the first order item
        order_item_id = next(iter(order_data["item_infos"].values()))["id"]
        print(f"Created Order: {order_id}")
        print(f"Order Item ID: {order_item_id}")

        print("\n4. Performing Exchange...")
        # We will exchange it for the exact same product ID as a test
        res = await client.post(f"{BASE_URL}/exchanges", json={
            "shop_id": SHOP_ID,
            "original_order_id": order_id,
            "customer_id": CUSTOMER_ID,
            "status": "EXCHANGED",
            "replacement_items": [
                {
                    "product_id": PRODUCT_ID,
                    "quantity": 1.0
                }
            ],
            "exchange_items": [
                {
                    "return_order_item_id": order_item_id,
                    "replacement_product_id": PRODUCT_ID,
                    "quantity_returned": 1.0,
                    "quantity_replaced": 1.0,
                    "reason": "Wrong size"
                }
            ]
        })

        if res.status_code != 200:
            print(f"Exchange failed: {res.text}")
        else:
            print("Exchange successful!")
            print(res.json())

if __name__ == "__main__":
    asyncio.run(run_test())
