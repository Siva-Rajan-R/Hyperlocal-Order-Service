import datetime
from typing import Any, Dict, List
from icecream import ic
from ..main import RabbitMQMessagingConfig
# Core utilities
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from core.utils.id_formatter import format_ui_id

# Database Sessions & Repositories
from infras.primary_db.main import AsyncOrdersLocalSession
from infras.primary_db.repos.order_repo import OrdersRepo
from infras.read_db.repos.order_repo import OrderReadDbRepo
from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo

# Database Models / Schemas
from infras.primary_db.models.order_model import OrderItems, Orders
from schemas.v1.db_schemas.order_schema import CreateOrderDbSchema
from integrations.utility_service import get_ui_id, get_shop_category, get_shop_unit


async def get_product_bulk(order_data: dict,headers: dict,payload: dict,rabbitmq_connection:RabbitMQMessagingConfig):
    product_ids=[]

    for item in order_data.get('items', []):
        product_ids.append(item.get('product_id'))

    routing_key="products.service.routing.key"
    exchange_name="products.service.exchange"
    entity_name="get_bulk_product_by_id"
    service_name="PRODUCTS"
    body={
        "shop_id":order_data.get('shop_id'),
        "id":product_ids
    }
                

    headers={
        **headers,
        "routing_key":routing_key,
        "exchange_name":exchange_name,
        "entity_name":entity_name,
        "service_name":service_name,
        "body":body
    }
    payload={
        **payload
    }

    await rabbitmq_connection.publish_event(
        routing_key=routing_key,
        payload=payload,
        headers=headers,
        exchange_name=exchange_name
    )

    return {
        "success":True,
        "execution":{
            "step":"FETCHING_PRODUCTS",
            "service":"PRODUCTS"
        }
    }

class MessagingQueueOrderProducer:

    def __init__(self, headers: dict, payload: dict, saga_datas: dict):
        self.headers = headers
        self.payload = payload
        self.saga_datas = saga_datas

    

    async def create_order(self):
        """
        Migrated Order Flow: Extracts order details from the saga data,
        generates sequential UI IDs, saves to primary DB, replicates to read DB,
        and fires an activity log via RabbitMQ.
        """
        ic(self.headers, self.payload, self.saga_datas)
        
        execution = self.saga_datas.get('execution', {})
        current_step = execution.get('step')
        datas = self.saga_datas.get("data", {})
        order_payload = datas.get("orders")  # This is a dict from saga data
        cart_items = order_payload.get("items", []) if order_payload else []

        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        
        if not order_payload or not cart_items:
            ic("Missing 'order_payload' or 'cart_items' in saga data context.")
            return {"success": False, "reason": "Missing required payload data"}


        if current_step == "VERIFY_CUSTOMER":
            ic("Inside verify customer")
            customer_data=datas.get("customers")
            if not customer_data:
                ic("Invalid Customer Info")
                return False

            return await get_product_bulk(
                order_data=order_payload,
                headers=self.headers,
                payload=self.payload,
                rabbitmq_connection=rabbitmq_msg_obj

            )


        # STEP-3: PARSE AND PERSIST TRANSACTION RECORD
        if current_step == "FETCHING_PRODUCTS":
            order_id = generate_uuid()
            
            ui_id_res = await get_ui_id(shop_id=order_payload.get('shop_id'))
            if isinstance(ui_id_res, dict) and "prefix" in ui_id_res:
                ui_id = f"{ui_id_res.get('prefix')}-{ui_id_res.get('current_number')}"
            else:
                ui_id = f"PUR-{int(datetime.datetime.utcnow().timestamp())}"
            ic(cart_items)

            product_res = datas.get("products") or []
            shop_id = order_payload.get("shop_id")
            calculation_infos = order_payload.get("calculation_infos") or {}
            charges_infos = order_payload.get("charges_infos") or {}
            payment_infos = order_payload.get("payment_infos") or {}
            origin=order_payload['origin']
            status=order_payload['status']
            customer_id=order_payload['customer_id']
            ord_date=order_payload.get("date", datetime.datetime.now()) or datetime.datetime.now()
            if isinstance(ord_date, str):
                ord_date = datetime.datetime.strptime(
                    ord_date,
                    "%Y-%m-%d"
                ).date()

            item_infos = {
                'total_order_items': 0,
                'total_order_qty': 0,
                'total_order_cost': 0,
                'total_order_amount': 0
            }
            
            validated_payload_map: Dict[str, List[dict]] = {}
            for prod in cart_items:
                p_id = prod['product_id']
                if p_id not in validated_payload_map:
                    validated_payload_map[p_id] = []
                validated_payload_map[p_id].append(prod)

            read_items = []
            order_items_toadd = []

            async with AsyncOrdersLocalSession() as session:
                repo = OrdersRepo(session)

                ic(product_res)
                for prod_db in product_res:
                    ic(prod_db)
                    product_id = prod_db['id']
                    product_name = prod_db['name']
                    db_ui_id = prod_db['ui_id']
                    
                    type_infos = prod_db.get('type_infos', {})
                    has_variant = type_infos.get('has_variant', False)
                    has_batch = type_infos.get('has_batch', False)
                    has_serialno = type_infos.get('has_serialno', False)
                    gst = prod_db.get('gst', '0%')

                    category_infos=prod_db.get('category_infos') or {}
                    unit_infos=prod_db.get('unit_infos') or {}

                    incoming_item_matches = validated_payload_map.get(product_id) or []
                    
                    for itm in incoming_item_matches:
                        variant_id = itm.get('variant_id')
                        batch_id = itm.get('batch_id')

                        variant_name = ''
                        batch_infos = {}
                        serialno_infos = []
                        stock_infos = {}
                        stl_infos = {}
                        rop_infos = {}
                        pricing_infos = {}

                        # --- Dynamic Scope Resolution Resolution Tree ---
                        if has_variant:
                            variants_dict = prod_db.get('variants', {})
                            variant_data = variants_dict.get(variant_id) if variants_dict else None
                            
                            if variant_data:
                                variant_name = variant_data.get('name', '')
                                
                                if has_batch:
                                    batches_list = variant_data.get('batch_infos', [])
                                    for b in batches_list:
                                        if (batch_id and b.get('id') == batch_id):
                                            batch_infos = b
                                            break
                                    
                                    stock_infos = batch_infos.get('stock_infos') or {}
                                    serialno_infos = batch_infos.get('serialno_infos') or [] if has_serialno else []
                                    stl_infos = batch_infos.get("storage_location_infos") or {}
                                    rop_infos = batch_infos.get("reorder_point_infos") or {}
                                    pricing_infos = batch_infos.get('pricing_infos') or {}
                                else:
                                    stock_infos = variant_data.get('stock_infos') or {}
                                    serialno_infos = variant_data.get('serialno_infos') or [] if has_serialno else []
                                    stl_infos = variant_data.get("storage_location_infos") or {}
                                    rop_infos = variant_data.get("reorder_point_infos") or {}
                                    pricing_infos = variant_data.get('pricing_infos') or {}
                        else:
                            if has_batch:
                                batches_list = prod_db.get('batch_infos', [])
                                for b in batches_list:
                                    if (batch_id and b.get('id') == batch_id) or (batch_target_name and b.get('name') == batch_target_name):
                                        batch_infos = b
                                        break
                                
                                stock_infos = batch_infos.get('stock_infos') or {}
                                serialno_infos = batch_infos.get('serialno_infos') or [] if has_serialno else []
                                stl_infos = batch_infos.get("storage_location_infos") or {}
                                rop_infos = batch_infos.get("reorder_point_infos") or {}
                                pricing_infos = batch_infos.get('pricing_infos') or {}
                            else:
                                stock_infos = prod_db.get('stock_infos') or {}
                                serialno_infos = prod_db.get('serialno_infos') or [] if has_serialno else []
                                stl_infos = prod_db.get("storage_location_infos") or {}
                                rop_infos = prod_db.get("reorder_point_infos") or {}
                                pricing_infos = prod_db.get('pricing_infos') or {}

                        # Compute Safe Inventory Delta Strategy metrics
                        stocks = float(itm.get('qty',0))
                        current_db_physical = float(stock_infos.get('physical_stocks', 0))
                        
                        stock_before = current_db_physical + stocks
                        ic(stock_before, current_db_physical, stocks)
                        stock_after = current_db_physical

                        # Update transaction metadata
                        item_infos['total_order_items'] += 1
                        sell_price_val = float(pricing_infos.get('sell_price', 0))
                        item_infos['total_order_amount'] += sell_price_val
                        
                        # if gst and gst.endswith('%') and gst_infos.get('type') == "EXCLUSIVE":
                        #     try:
                        #         gst_rate = float(gst[:-1]) / 100.0
                        #         item_infos['total_gst_amount'] += gst_rate * buy_price_val
                        #     except ValueError:
                        #         pass
                        
                        item_infos['total_order_qty'] += stocks

                        ord_item_id = generate_uuid()  
                        order_items_toadd.append(
                            OrderItems(
                                order_id=order_id,
                                id=ord_item_id,
                                product_id=product_id,
                                variant_id=variant_id,
                                batch_id=batch_id,
                                serialno_infos=itm['serialno_infos'],
                                gst=gst,
                                buy_price=pricing_infos.get('buy_price', 0.0),
                                sell_price=pricing_infos.get('sell_price', 0.0),
                                quantity=stocks
                            )
                        )

                        

                        read_items.append(
                            {
                                "id": ord_item_id,
                                "product_id": product_id,
                                "ui_id": db_ui_id,
                                "name": product_name,
                                "category_infos":category_infos,
                                "unit_infos":unit_infos,
                                "variant_infos": {"variant_id": variant_id, "variant_name": variant_name} if variant_id else None,
                                "batch_infos": {
                                    "batch_id": batch_id,
                                    "batch_name": batch_infos.get('name', ''),
                                    "exp_date":batch_infos.get("expiry_date"),
                                    "mfg_date":batch_infos.get("manufacturing_date")
                                } if batch_id else None,
                                "serialno_infos": itm['serialno_infos'] if itm['serialno_infos'] else None,
                                "buy_price": pricing_infos.get('buy_price', 0.0),
                                "sell_price": pricing_infos.get('sell_price', 0.0),
                                "quantity": stocks,
                                "stock_before":stock_before,
                                "stock_after":stock_after,
                                "returned_quantity": 0.0,
                                "total_amount": pricing_infos.get('sell_price', 0.0) * stocks,
                                "status": status,
                                "gst": gst
                            }
                        )

                order_toadd=CreateOrderDbSchema(
                    id=order_id,
                    ui_id=ui_id,
                    shop_id=shop_id,
                    customer_id=customer_id,
                    status=status,
                    origin=origin,
                    calculation_infos=calculation_infos,
                    item_infos=item_infos,
                    payment_infos=payment_infos,
                    charges_infos=charges_infos,
                    date=ord_date
                )

                await repo.create(data=order_toadd)

                await repo.create_bulk_items(datas=order_items_toadd)


                total_amount_paid = sum(amount for method,amount in payment_infos.items())
                total_ord_cost = float(item_infos['total_order_amount'])
                outstanding_amount = abs(total_ord_cost - total_amount_paid)
                ic(total_amount_paid,total_ord_cost,outstanding_amount)

                if outstanding_amount == 0:
                    outstanding_status = "COMPLETED"
                elif total_amount_paid == 0:
                    outstanding_status = "NOT-PAID"
                else:
                    outstanding_status = "PARTIALY-PAID"


                read_db_order_payload = {
                    "id": order_id,
                    "ui_id": ui_id,
                    "shop_id": shop_id,
                    "customer_id": customer_id,
                    "status": status,
                    "origin": origin,
                    "calculation_infos": calculation_infos or {},
                    "charges_infos": charges_infos or {},
                    "item_infos": item_infos or {},
                    "payment_infos": payment_infos or [],
                    "payment_status":outstanding_status,
                    "pending_amount":outstanding_amount,
                    "date": ord_date,
                    "items": read_items
                }
                ic(item_infos)
                ic(read_items)
                ic(read_db_order_payload)
                await OrderReadDbRepo.replace_order(read_db_order_payload)

                

                if outstanding_status!="COMPLETED" and customer_id:
                    await rabbitmq_msg_obj.publish_event(
                        routing_key="customers.service.routing.key",
                        exchange_name="customers.service.exchange",
                        payload={
                            "shop_id": order_payload.get('shop_id'),
                            "id":order_payload.get("customer_id"),
                            "outstanding_infos":{"amount":outstanding_amount},
                            "type":"INCREMENT",
                        },
                        headers={
                            **self.headers.copy(),
                            "body":{
                                "shop_id": order_payload.get('shop_id'),
                                "id":order_payload.get("customer_id"),
                                "outstanding_infos":{"amount":outstanding_amount},
                                "type":"INCREMENT",
                            },
                            "entity_name":"add_customer_outstanding",
                            "service_name":"CUSTOMERS"
                        }
                    )

                try:
                    analytics_payload = {
                        "shop_id": shop_id,
                        "datas": [
                            {
                                "sales_id": order_id,
                                "customer_id": customer_id,
                                "product_id": item['product_id'],
                                "variant_id": item.get('variant_infos', {}).get('variant_id') if item.get('variant_infos') else None,
                                "batch_id": item.get('batch_infos', {}).get('batch_id') if item.get('batch_infos') else None,
                                "stocks": float(item.get('quantity', 0)),
                                "sales_amounts": float(item.get('total_amount', 0)),
                                "sales_type": origin
                            }
                            for item in read_items
                        ]
                    }
                    await rabbitmq_msg_obj.publish_event(
                        routing_key="analytics.service.routing.key",
                        exchange_name="analytics.service.exchange",
                        payload=analytics_payload,
                        headers={
                            "entity_name": "sales_event",
                            "service_name": "ANALYTICS",
                            "saga_id": "none",
                            "reply_key": "none",
                            "reply_exchange": "none",
                            "reply_entity_name": "none",
                            "body": analytics_payload
                        }
                    )
                except Exception as e:
                    ic(f"Failed to publish analytics event: {e}")

                return {
                    "success": True,
                    "execution": {
                        "step":"SUCCESS",
                        "service":"ORDERS"
                    }
                }



        if current_step == "SUCCESS":
            ic("Successfully completed the order cycle context workflow.")
            return {
                "success": True,
                "execution": None
            }
    
