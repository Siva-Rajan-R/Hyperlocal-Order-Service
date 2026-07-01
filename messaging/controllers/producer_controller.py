from aio_pika.abc import AbstractIncomingMessage
import orjson,inspect
from icecream import ic

from messaging.main import RabbitMQMessagingConfig
from models.messaging_models.consumer_model import BaseConsumerModel
from hyperlocal_platform.infras.saga.schemas import CreateSagaStateSchema,UpdateSagaStateSchema
from hyperlocal_platform.infras.saga.repo import SagaStatesRepo
from core.errors.messaging_errors import BussinessError,RetryableError,FatalError
from hyperlocal_platform.core.enums.saga_state_enum import SagaStatusEnum,SagaStepsValueEnum
from hyperlocal_platform.core.enums.routingkey_enum import RoutingkeyState,RoutingkeyActions
from hyperlocal_platform.infras.saga.schemas import SagaStateExecutionTypDict,SagaStateErrorTypDict
from hyperlocal_platform.infras.saga.main import AsyncInfraDbLocalSession
from hyperlocal_platform.core.typed_dicts.messaging_typdict import SuccessMessagingTypDict,EventPublishingTypDict
from core.utils.exception_serializer import serialize_exception
from hyperlocal_platform.core.typed_dicts.messaging_typdict import EventPublishingTypDict
from hyperlocal_platform.core.utils.routingkey_builder import generate_routingkey
from typing import Optional
from hyperlocal_platform.core.basemodels.readdb_model import ReadDbBaseModel
from ..msgqueue_producers.order_msgqueue_producer import MessagingQueueOrderProducer
from ..msgqueue_producers.order_return_msgqueue_producer import MessagingQueueOrderReturnProducer


MESSAGING_QUEUE_PRODUCER_MAPPER_BY_SERVICE_NAME={
    "ORDERS": MessagingQueueOrderProducer,
    "ORDERS_RETURN":MessagingQueueOrderReturnProducer
}

SERVICE_NAME="ORDERS".upper()



async def producer_main_controller(msg:AbstractIncomingMessage):
    async with AsyncInfraDbLocalSession() as session:
        payload=orjson.loads(msg.body)
        headers:dict=msg.headers
        saga_id:str=headers.get("saga_id")

        reply_key:str=headers.get("reply_key")
        reply_exchange:str=headers.get("reply_exchange")
        reply_entity_name:str=headers.get("reply_entity_name")
        reply_service_name:str=headers.get("reply_service_name")

        saga_repo=SagaStatesRepo(session=session)
        saga_datas=await saga_repo.getby_id(saga_id=saga_id)
        ic(saga_datas)
        ic(payload,headers,saga_id,reply_entity_name,reply_key,reply_exchange,reply_service_name)

        try:
            
            if not reply_service_name or not saga_id or not reply_key or not reply_exchange or not reply_entity_name:
                ic("One or more required fields are missing in the message headers")
                await saga_repo.update_status(
                    status=SagaStatusEnum.CANCELED,
                    saga_id=saga_id
                )
                await saga_repo.update_error(
                    saga_id=saga_id,
                    error=SagaStateErrorTypDict(
                        code="BUSSINESS_ERROR",
                        debug=f"entity_name, , saga_id, reply_key, reply_exchange, reply_entity_name and service_name are required in the message headers ( {saga_id}, {reply_key}, {reply_exchange}, {reply_entity_name})",
                        user_msg="One or more required fields are missing in the message headers"
                    )
                )
                await saga_repo.update_step(
                    saga_id=saga_id,
                    key=saga_datas['execution']['step'],
                    status=SagaStepsValueEnum.FAILED
                )

                await session.commit()
                return False

            producer = MESSAGING_QUEUE_PRODUCER_MAPPER_BY_SERVICE_NAME.get(reply_service_name.upper())
            
            if not producer:
                ic(f"Service name '{reply_service_name}' is not recognized")
                await saga_repo.update_status(
                    status=SagaStatusEnum.CANCELED,
                    saga_id=saga_id
                )
                await saga_repo.update_error(
                    saga_id=saga_id,
                    error=SagaStateErrorTypDict(
                        code="BUSSINESS_ERROR",
                        debug=f"service_name '{reply_service_name}' is not recognized",
                        user_msg="Service name in the message headers is not recognized, please check and try again"
                    )
                )
                await saga_repo.update_step(
                    saga_id=saga_id,
                    key=saga_datas['execution']['step'],
                    status=SagaStepsValueEnum.FAILED
                )

                await session.commit()
            
                return False
            
            
            ic(saga_datas)
            
            method = getattr(producer(payload=payload,headers=headers,saga_datas=saga_datas), reply_entity_name, None)
            ic(method)
            if not method:
                ic(f"Entity name '{reply_entity_name}' is not recognized")
                await saga_repo.update_status(
                    status=SagaStatusEnum.CANCELED,
                    saga_id=saga_id
                )
                await saga_repo.update_error(
                    saga_id=saga_id,
                    error=SagaStateErrorTypDict(
                        code="BUSSINESS_ERROR",
                        debug=f"entity_name '{reply_entity_name}' is not recognized",
                        user_msg="Entity name in the message headers is not recognized, please check and try again"
                    )
                )
                await saga_repo.update_step(
                    saga_id=saga_id,
                    key=saga_datas['execution']['step'],
                    status=SagaStepsValueEnum.FAILED
                )

                await session.commit()
                
                return False
            
            if saga_datas['status']==SagaStatusEnum.CANCELED.value:
                return False
            
            if inspect.iscoroutinefunction(method):
                result = await method()
            else:
                result = method()

            ic(result)
            success:bool=result['success']
            error_msg:str=""
            if not success:
                error_msg=result['error_infos']['msg']
            
            execution=result['execution']
            next_step=execution['step'] if execution else None
            execution_service=execution['service'] if execution else None

            # Re-fetch saga to get the CURRENT execution step (avoids stale cached value
            # causing the same step to be re-marked when subsequent messages arrive)
            
            # fresh_saga_datas = await saga_repo.getby_id(saga_id=saga_id)
            current_step = saga_datas['execution']['step']

            if success:
                ic(f"Successfully processed the message for entity '{reply_entity_name}' with response: {success}")
                await saga_repo.update_status(
                    status=SagaStatusEnum.COMPLETED,
                    saga_id=saga_id
                )

                await saga_repo.update_step(
                    saga_id=saga_id,
                    key=current_step,
                    status=SagaStepsValueEnum.COMPLETED
                )
                ic(next_step,current_step,execution_service)
                if execution:
                    await saga_repo.update_execution(
                        saga_id=saga_id,
                        execution=SagaStateExecutionTypDict(
                            step=next_step,
                            service=execution_service
                        )
                    )
                
                await session.commit()

                ic(await saga_repo.getby_id(saga_id=saga_id))

            else:
                ic(f"Failed to process the message for entity '{reply_entity_name}'")
                await saga_repo.update_status(
                    status=SagaStatusEnum.CANCELED,
                    saga_id=saga_id
                )
                await saga_repo.update_error(
                    saga_id=saga_id,
                    error=SagaStateErrorTypDict(
                        code="BUSSINESS_ERROR",
                        debug=f"Processing the message for entity '{reply_entity_name}' failed reason : {error_msg}",
                        user_msg=error_msg
                    )
                )
                await saga_repo.update_step(
                    saga_id=saga_id,
                    key=current_step,
                    status=SagaStepsValueEnum.FAILED
                )

                await session.commit()

            return True


        except Exception as e:
            ic(f"An error occurred while processing the message: {e}")
            debug_msg=serialize_exception(e)
            await saga_repo.update_status(
                    status=SagaStatusEnum.CANCELED,
                    saga_id=saga_id
                )
            await saga_repo.update_error(
                saga_id=saga_id,
                error=SagaStateErrorTypDict(
                    code="FATAL_ERROR",
                    debug=f"Processing the message for entity '{reply_entity_name}' failed with exceptions, {debug_msg}",
                    user_msg="Failed to process the message due to fatal error, please check the data and try again"
                )
            )
            await saga_repo.update_step(
                saga_id=saga_id,
                key=saga_datas['execution']['step'],
                status=SagaStepsValueEnum.FAILED
            )

            await session.commit()

            return False
        
        finally:
            ic("Finally not publishing the event bcoz its a producer just ack")
            # await RabbitMQMessagingConfig().publish_event(
            #     routing_key=reply_key,
            #     payload=payload,
            #     headers=headers,
            #     exchange_name=reply_exchange
            # )

            await msg.ack()
            return True
