from core.data_formats.enums.order_enum import OrderOriginEnum, OrderStatusEnum
from models.service_models.base_service_model import BaseServiceModel
from infras.primary_db.repos.order_repo import OrdersRepo
from schemas.v1.db_schemas.order_schema import CreateReturnDbSchema, CreateReturnItemDbSchema
from schemas.v1.request_scheams.order_schema import CreateReturnSchema, GetOrderByIdSchema
from hyperlocal_platform.core.utils.uuid_generator import generate_uuid
from infras.primary_db.models.order_model import Returns, ReturnItems
from infras.read_db.repos.order_repo import OrderReadDbRepo
import httpx
from fastapi import HTTPException
from icecream import ic
from ..main import AsyncSession
from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo
from core.utils.id_formatter import format_ui_id
from integrations.utility_service import get_ui_id
from integrations.customer_service import get_customer_info
from messaging.saga_producer import SagaProducer,CreateSagaStateSchema,SagaStatusEnum
from hyperlocal_platform.core.enums.saga_state_enum import SagaStepsValueEnum
from hyperlocal_platform.core.typed_dicts.saga_status_typ_dict import SagaStateExecutionTypDict
from messaging.main import RabbitMQMessagingConfig


class ReturnService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_return(self, data: CreateReturnSchema) -> bool | None:
        rabbitmq_connection=RabbitMQMessagingConfig()
        return_id = generate_uuid()
        order_data = await OrdersRepo(session=self.session).getby_id(
            data=GetOrderByIdSchema(id=data.order_id, shop_id=data.shop_id)
        )
        ic(order_data)
        if not order_data:
            raise HTTPException(status_code=404, detail="Order not found")
        
        ui_id_res = await get_ui_id(shop_id=order_data.get('shop_id'))
        ui_id=f"{ui_id_res.get("prefix")}-{ui_id_res.get("current_number")}"


        order_id=order_data['id']
        additional_infos=order_data['additional_infos']
        calculation_infos=order_data['calculation_infos']
        customer_id=order_data['customer_id']
        date=order_data['date']
        origin=order_data['origin']
        payment_infos=[data.payment_infos]
        status=order_data['status']
        shop_id=data.shop_id



        items_map = {itm["id"]: itm for itm in (order_data.get("items") or [])}
        return_toadd=None
        return_items_toadd=[]
        products_toupdate=[]
        customer_outst_toadd={}
        oncredit_amount=0
        total_refund_qty=0
        total_refund_amount=0
        for itm in data.items:
            itm=itm.model_dump()
            ic(itm)
            inc_item_id=itm['order_item_id']
            ic(inc_item_id)
            if inc_item_id not in items_map:
                ic("Invalid order item id")
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Order Item"
                )
            ic(items_map[inc_item_id])
            original_qty=items_map[inc_item_id]['quantity']
            returned_qty=items_map[inc_item_id]['returned_quantity']
            exchanged_qty=items_map[inc_item_id]['exchanged_quantity']

            inc_quantity=itm["quantity"]

            ic(original_qty,returned_qty,exchanged_qty)

            delta=original_qty-returned_qty-exchanged_qty-inc_quantity
            ic(delta)
            if delta<0:
                ic("Invalid order qty")
                raise HTTPException(
                    status_code=400,
                    detail="The given qty should not be added"
                )
            
            order_amount = items_map[inc_item_id]['sell_price']
            total_return_qty_amount=inc_quantity*order_amount
            total_returned_paid_amount=0
            
            for key,amount in data.payment_infos.items():
                total_returned_paid_amount += amount

                if key == "ON_CREDIT":
                    oncredit_amount += amount
            ic(total_return_qty_amount,total_refund_amount)
            
            if (total_return_qty_amount-total_returned_paid_amount)!=0:
                ic("Return Amount should be proeprly emnter")
                raise HTTPException(
                    status_code=400,
                    detail="Return Amount need to enter proeprly"
                )
            
            for serialno in (itm.get("serialno_infos") or []):
                if serialno['id'] not in items_map[inc_item_id]['serialno_infos']:
                    ic("Serialno not found")
                    raise HTTPException(
                        status_code=400,
                        detail="Serialno not found"
                    )

            
            products_toupdate.append(
                {
                    "shop_id":shop_id,
                    "product_id":items_map[inc_item_id]['product_id'],
                    "variant_id":items_map[inc_item_id]['variant_id'],
                    "batch_infos":items_map[inc_item_id]['batch_id'] if items_map[inc_item_id]['batch_id'] else None,
                    "serialno_infos":items_map[inc_item_id]['serialno_infos'],
                    "stocks":inc_quantity,
                    "entity_name":"OFFLINE_SALES_RETURN",
                    "type":"INCREMENT",
                    "create_stock_mov_adj":True
                }
            )

            total_refund_qty+=inc_quantity
            total_refund_amount+=total_return_qty_amount
            ic(total_refund_amount,total_refund_qty,total_return_qty_amount,total_returned_paid_amount)
            return_items_toadd.append(
                {
                    'id':generate_uuid(),
                    'return_id':return_id,
                    'order_item_id':itm['order_item_id'],
                    'product_id':items_map[inc_item_id]['product_id'],
                    'quantity':inc_quantity,
                    'refund_amount':total_return_qty_amount,
                    'reason':itm['reason']
                }
            )


        return_toadd={
            "id":return_id,
            "ui_id":ui_id,
            "order_id":order_id,
            "customer_id":customer_id,
            "shop_id":shop_id,
            "status":"COMPLETED",
            "payment_infos":payment_infos,
            "total_refund_qty":total_refund_qty,
            "total_refund_amount":total_refund_amount

        }


        if oncredit_amount:
            if not customer_id:
                ic("Cant able to add the onccredit payment for the walkincustomers")
                raise HTTPException(
                    status_code=400,
                    detail="Cant able to add the onccredit payment for the walkincustomers"
                )
            customer_infos=await get_customer_info(shop_id=data.shop_id,customer_id=customer_id)
            ic(customer_infos)
            customer_existing_outst=customer_infos['outstanding_infos']['amount'] if customer_infos else None
            if not customer_existing_outst:
                ic("There is no outstanding for the customer please provide the amount on upi,cash or any other payment method")
                raise HTTPException(
                    status_code=400,
                    detail="There is no outstanding for the customer please provide the amount on upi,cash or any other payment method"
                )
            customer_outst_toadd={
                "customer_id":customer_id,
                "shop_id":shop_id,
                "amount":oncredit_amount
            }

            

        ic(return_toadd,return_items_toadd)

        return_data={"order_return":{"return_toadd":return_toadd,"return_items_toadd":return_items_toadd,"customer_toadd":customer_outst_toadd}}
        ic(return_data)

        saga_id:str=generate_uuid()
        steps={
            "PRODUCT_VERIFY_UPDATE":SagaStepsValueEnum.PENDING,
            # "FETCHING_PRODUCTS":SagaStepsValueEnum.PENDING
        }

        saga_data=return_data
        await SagaProducer.emit(
            session=self.session,
            saga_payload=CreateSagaStateSchema(
                id=saga_id,
                status=SagaStatusEnum.IN_PROGRESS,
                type="OREDER_RETURNED",
                steps=steps,
                execution=SagaStateExecutionTypDict(
                    step="PRODUCT_VERIFY_UPDATE",
                    service="PRODUCTS"
                ),
                data=saga_data
            ),
            routing_key="products.service.routing.key",
            exchange_name="products.service.exchange",
            headers={
                "reply_key":"orders.producer.routing.key",
                "reply_exchange":"orders.producer.exchange",
                "reply_entity_name":"create_return",
                "reply_service_name":"ORDERS_RETURN",
                "service_name":"PRODUCTS",
                "entity_name":"update_bulk_prodinv",
                "body":products_toupdate

            }
        )


        if customer_outst_toadd:
            await rabbitmq_connection.publish_event(
                routing_key="customers.service.routing.key",
                exchange_name="customers.service.exchange",
                payload=customer_outst_toadd,
                headers={
                    "saga_id":generate_uuid(),
                    "reply_entity_name":"null",
                    "reply_exchange":"null",
                    "reply_key":"null",
                    "service_name":"CUSTOMERS",
                    "entity_name":"clear_customer_outstanding",
                    "service":"CUSTOMERS",
                    "body":{
                        "customer_id":customer_outst_toadd['customer_id'],
                        "shop_id":customer_outst_toadd['shop_id'],
                        "payment_infos":[{"method":'CASH',"amount":customer_outst_toadd['amount']}]
                    }
                }
            )

        return True

        


            



            

        

        
