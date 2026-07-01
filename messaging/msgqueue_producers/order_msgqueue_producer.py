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


        if current_step in ["FETCHING_PRODUCTS", "FETCHING_PPRODUCTS"]:
            ic(f"Skipping order creation. Current step is: {current_step}")

            products_data = datas.get("products", [])
            order_id = generate_uuid()
            order_items_toadd = []
            ui_id_res = await get_ui_id(shop_id=order_payload.get('shop_id'))
            ic(ui_id_res)
            ui_id=f"{ui_id_res.get("prefix")}-{ui_id_res.get("current_number")}"
            ic(ui_id)
            item_infos={
                    'total_items':0,
                    'total_stocks':0,
                    'total_cost':0,
                    'total_gst_amount':0
                }
            shop_id=order_payload['shop_id']
            origin=order_payload['origin']
            status=order_payload['status']
            charges_infos=order_payload['charges_infos']
            calculation_infos=order_payload['calculation_infos']
            payment_infos=order_payload['payment_infos']
            ord_date=order_payload.get("date", datetime.datetime.now()) or datetime.datetime.now()
            if isinstance(ord_date, str):
                ord_date = datetime.datetime.strptime(
                    ord_date,
                    "%Y-%m-%d"
                ).date()
            customer_id=order_payload['customer_id']

            validated_data={}
            for prod in cart_items:
                ic(prod)
                product_id=prod['product_id']
                if product_id not in validated_data:
                    validated_data[product_id]=[]
                
                validated_data[product_id].append(prod)
            ic(validated_data)


            read_items = []

            for prod in products_data:
                ic(prod)
                product_id=prod['id']
                product_name=prod['name']
                prod_ui_id=prod['ui_id']
                has_variant=prod['type_infos']['has_variant']
                has_batch=prod['type_infos']['has_batch']
                has_serialno=prod['type_infos']['has_serialno']
                variant_id=None
                batch_id=None
                variant_name=''
                batch_infos={}
                serialno_infos=[]
                stock_infos={}
                stl_infos={}
                rop_infos={}
                pricing_infos={}
                gst=prod['gst']

                category_id = prod.get('category_id')
                unit_id = prod.get('unit_id')
                category_name = ""
                unit_name = ""
                if category_id:
                    cat_res = await get_shop_category(shop_id=shop_id, category_id=category_id)
                    category_name = cat_res.get("name", "") if isinstance(cat_res, dict) else ""
                if unit_id:
                    unit_res = await get_shop_unit(shop_id=shop_id, unit_id=unit_id)
                    unit_name = unit_res.get("name", "") if isinstance(unit_res, dict) else ""

                stock_before=0
                stock_after=0
                stocks=0

                pur_items_toadd=[]
                pur_pricing_toadd=[]
                pur_stl_toadd=[]
                pur_rop_toadd=[]


                validate_data_res=validated_data.get(product_id)
                for itm in validate_data_res:
                    batch_id=itm['batch_id']
                    variant_id=itm['variant_id']
                    if has_variant:
                        if variant_id in prod['variants']:
                            stock_infos=prod['variants'][variant_id].get("stock_infos",{})
                    
                            variant_name=prod['variants']['name']
                            if has_batch and not has_serialno:
                                batch_infos=prod['variants'][variant_id]['batch_infos'].get("batch_id",{})
                                stock_infos=batch_infos['stock_infos']
                            
                            if has_serialno and not has_batch:
                                serialno_infos=prod['variants'][variant_id].get('serialno_infos',{})

                            if has_serialno and has_batch:
                                batch_infos=prod['variants'][variant_id]['batch_infos'].get("batch_id",{})
                                stock_infos=batch_infos['stock_infos']
                                serialno_infos=batch_infos['serialno_infos']
                            
                            stl_infos=prod['variants'][variant_id].get("storage_location_infos",{})
                            rop_infos=prod['variants'][variant_id].get("reorder_point_infos",{})
                            pricing_infos=prod['variants'][variant_id]['pricing_infos']


                            stocks=itm['qty']
                            stock_before=stock_infos['physical_stocks']-stocks
                            stock_after=stock_infos['physical_stocks']+stocks



                    else:

                        stock_infos=stock_infos=prod.get("stock_infos",{})

                        if has_batch and not serialno_infos:
                            batch_infos=prod['batch_infos'][batch_id]
                            stock_infos=batch_infos['stock_infos']
                        
                        if has_serialno and not has_batch:
                            serialno_infos=prod['serialno_infos']
                        
                        if has_serialno and has_batch:
                            batch_infos=prod['batch_infos'][batch_id]
                            stock_infos=batch_infos['stock_infos']
                            serialno_infos=batch_infos['serialno_infos']

                        stocks=itm['qty']
                        stock_before=stock_infos['physical_stocks']-stocks
                        stock_after=stock_infos['physical_stocks']+stocks

                        stl_infos=prod.get("storage_location_infos",{})
                        rop_infos=prod.get("reorder_point_infos",{})
                        pricing_infos=prod['pricing_infos']


                        item_infos['total_items']+=1
                        item_infos['total_cost']+=pricing_infos['sell_price']
                        item_infos['total_gst_amount']+=(int(gst[:-1])/100)*pricing_infos['buy_price']
                        item_infos['total_stocks']+=stocks
                    
                    order_item_id = generate_uuid()
                    
                    read_items.append({
                        "id": order_item_id,
                        "product_id": product_id,
                        "ui_id": prod_ui_id,
                        "name": product_name,
                        "category_name": category_name,
                        "unit_name": unit_name,
                        "variant_infos": {"variant_id": variant_id, "variant_name": variant_name} if variant_id else None,
                        "batch_infos": {"batch_id": batch_id, "batch_name": batch_infos.get('name', '') if isinstance(batch_infos, dict) else str(batch_infos)} if batch_id else None,
                        "serialno_infos": {"serialno_id": "bulk", "serial_numbers": [s.get('name', s) if isinstance(s, dict) else s for s in serialno_infos]} if serialno_infos else None,
                        "buy_price": pricing_infos.get('buy_price', 0.0),
                        "sell_price": pricing_infos.get('sell_price', 0.0),
                        "quantity": stocks,
                        "returned_quantity": 0.0,
                        "total_amount": pricing_infos.get('sell_price', 0.0) * stocks,
                        "status": status,
                        "gst": gst
                    })

                    order_items_toadd.append(
                        OrderItems(
                            order_id=order_id,
                            id=order_item_id,
                            product_id=product_id,
                            variant_id=variant_id,
                            batch_id=batch_id,
                            serialno_infos=serialno_infos,
                            gst=gst,
                            buy_price=pricing_infos['buy_price'],
                            sell_price=pricing_infos['sell_price'],
                            quantity=stocks
                        )
                    )
                
                    
            async with AsyncOrdersLocalSession() as session:
                repo = OrdersRepo(session=session)
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


                total_amount_paid=0
                total_cost=item_infos['total_cost']+item_infos['total_gst_amount']
                for payment in payment_infos:
                    for _, amount in payment.items():
                        total_amount_paid += amount

                ic(total_amount_paid,total_cost)
                outstanding_amount=abs(total_cost-total_amount_paid)

                outstanding_status="COMPLETED"
                if outstanding_amount==total_cost:
                    outstanding_status="NOT-PAID"
                else:
                    outstanding_status="PARTIALY-PAID"

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
                    "date": ord_date,
                    "items": read_items
                }
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

                return {
                    "success": True,
                    "execution": {
                        "step":"SUCCESS",
                        "service":"ORDERS"
                    }
                }



        if current_step=="SUCCESS":
            ic("Successfully Completed the purchase")
            return {
                "success": True,
                "execution": None
            }
