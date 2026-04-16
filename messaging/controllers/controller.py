from aio_pika.abc import AbstractIncomingMessage
import orjson
from icecream import ic
from icecream import ic
from hyperlocal_platform.core.utils.exception_serializer import serialize_exception
from messaging.main import RabbitMQMessagingConfig
from models.messaging_models.consumer_model import BaseConsumerModel
from hyperlocal_platform.infras.saga.schemas import CreateSagaStateSchema,UpdateSagaStateSchema
from hyperlocal_platform.infras.saga.repo import SagaStatesRepo
from core.errors.messaging_errors import BussinessError,RetryableError,FatalError,ErrorTypeSEnum
from hyperlocal_platform.core.enums.saga_state_enum import SagaStatusEnum,SagaStepsValueEnum
from hyperlocal_platform.core.enums.routingkey_enum import RoutingkeyState,RoutingkeyActions
from hyperlocal_platform.infras.saga.schemas import SagaStateExecutionTypDict,SagaStateErrorTypDict
from hyperlocal_platform.infras.saga.main import AsyncInfraDbLocalSession
from hyperlocal_platform.core.typed_dicts.messaging_typdict import SuccessMessagingTypDict,EventPublishingTypDict
from .compensation_controller import CompensationController
from models.infra_models.readdb_model import BaseReadDbModel
from hyperlocal_platform.core.basemodels.readdb_model import ReadDbBaseModel
from core.constants import SERVICE_NAME
from typing import Optional

class ConsumersHandler:
    @staticmethod
    async def _helper(consumer_cls:BaseConsumerModel,msg:AbstractIncomingMessage,service_name:str,exchange_service_name:str,readdb_cls:Optional[BaseReadDbModel]=None):
        try:
            domain,work_for,action,state,version=msg.routing_key.split('.')
            ACTIONS_MAP={
                'create':'create','update':'update','delete':'delete','failed':''
            }

            headers:dict=msg.headers
            saga_id:str=headers.get('saga_id')
            payload=None
            compensation_payload:EventPublishingTypDict=EventPublishingTypDict(
                exchange_name=f"{service_name}.{work_for}.{exchange_service_name}.exchange",
                routing_key=f"{service_name}.{work_for}.{action}.{RoutingkeyState.FAILED.value}.{version}",
                payload={},
                headers={'saga_id':saga_id}
            )

            async with msg.process():
                async with AsyncInfraDbLocalSession() as session:
                    await SagaStatesRepo(session=session).update_execution(
                        execution=SagaStateExecutionTypDict(
                            step=f"{service_name}:{action}",
                            service=f"{service_name.upper()}_SERVICE"
                        ),
                        saga_id=saga_id
                    )
                    saga_infos=await SagaStatesRepo(session=session).getby_id(saga_id=saga_id)

                    payload=saga_infos
                    
                    consumer_obj=consumer_cls(session=session,payload=payload,headers=headers,saga_id=saga_id)
                    method_name=ACTIONS_MAP.get(action if state!=RoutingkeyState.FAILED.value else state,None)

                    if not method_name:
                        raise FatalError(
                            type=ErrorTypeSEnum.FATAL_ERROR,
                            error=SagaStateErrorTypDict(
                                code=ErrorTypeSEnum.FATAL_ERROR.value,
                                debug=f"There is no method name found for the action key of {action} , routing key => {msg.routing_key}",
                                user_msg="We are facing some internal issue please try again after sometimes"
                            ),
                            compensation=CompensationController(msg=msg).decide(saga_payload=saga_infos),
                            compensation_payload=compensation_payload
                        )
                    
                    handler=getattr(consumer_obj,method_name,None)
                    if not handler:
                        raise FatalError(
                            type=ErrorTypeSEnum.FATAL_ERROR,
                            error=SagaStateErrorTypDict(
                                code=ErrorTypeSEnum.FATAL_ERROR.value,
                                debug=f"There is no consumer handler found for the action key of {action} , routing key => {msg.routing_key}",
                                user_msg="We are facing some internal issue please try again after sometimes"
                            ),
                            compensation=CompensationController(msg=msg).decide(saga_payload=saga_infos),
                            compensation_payload=compensation_payload
                        )
                    
                    res:SuccessMessagingTypDict=await handler()
                    if res:
                        if res.get("set_response"):
                            await SagaStatesRepo(session=session).merge(service=service_name,data=res.get("response"),saga_id=saga_id)

                        status:SagaStatusEnum=SagaStatusEnum.COMPLETED
                        if state == RoutingkeyState.FAILED.value:
                            status=SagaStatusEnum.COMPENSIATED
                        elif not res.get("mark_completed"):
                            status=SagaStatusEnum.IN_PROGRESS

                        await SagaStatesRepo(session=session).update_status(status=status,saga_id=saga_id)
                        await SagaStatesRepo(session=session).update_step(key=f"{service_name}.{action}",status=SagaStepsValueEnum.COMPLETED,saga_id=saga_id)
                        
                        if res.get("emit_success"):
                            emit_payload:EventPublishingTypDict=res.get("emit_payload")
                            await RabbitMQMessagingConfig().publish_event(
                                routing_key=emit_payload.get('routing_key'),
                                payload=emit_payload.get('payload'),
                                headers=emit_payload.get("headers"),
                                exchange_name=emit_payload.get("exchange_name")
                            )
                        
                        if res.get('read_db') and readdb_cls:
                            read_db_infos:ReadDbBaseModel=res.get('read_db')
                            readdb_cls_obj=readdb_cls(
                                payload=read_db_infos.payload,
                                conditions=read_db_infos.condition
                            )
                            handler=getattr(readdb_cls_obj,read_db_infos.method)
                            if not handler:
                                ic(f"Readdb handler was not implement for the class & method of => {readdb_cls} {read_db_infos}")
                            res=await handler()
                            ic(f"Read-DB response => {res}")
                        
                        return

                return


        except BussinessError as e:
            ic(e)
            async with AsyncInfraDbLocalSession() as session:
                await SagaStatesRepo(session=session).update_status(saga_id=saga_id,status=SagaStatusEnum.CANCELED.value)
                await SagaStatesRepo(session=session).update_step(key=f"{service_name}.{action}",status=SagaStepsValueEnum.FAILED.value,saga_id=saga_id)
                await SagaStatesRepo(session=session).update_error(error=e.error,saga_id=saga_id)

            if e.compensation:
                await RabbitMQMessagingConfig().publish_event(
                    routing_key=e.compensation_payload.get("routing_key"),
                    payload=e.compensation_payload.get("payload"),
                    headers=e.compensation_payload.get("headers"),
                    exchange_name=e.compensation_payload.get("exchange_name")
                )

            return

        except RetryableError as e:
            ic(e)
            prev_retry_count=payload['retry_count']
            status=SagaStatusEnum.RETRYING
            retry_count:int=prev_retry_count+1

            async with AsyncInfraDbLocalSession() as session:
                if retry_count>3:
                    status=SagaStatusEnum.CANCELED
                await SagaStatesRepo(session=session).update_status(saga_id=saga_id,status=status.value)
                await SagaStatesRepo(session=session).update_step(key=f"{service_name}.{action}",status=SagaStepsValueEnum.FAILED.value,saga_id=saga_id)
                await SagaStatesRepo(session=session).update_error(error=e.error,saga_id=saga_id)
                await SagaStatesRepo(session=session).update_retry_count(retry_count=retry_count,saga_id=saga_id)

            if e.compensation:
                await RabbitMQMessagingConfig().publish_event(
                    routing_key=e.compensation_payload.get("routing_key"),
                    payload=e.compensation_payload.get("payload"),
                    headers=e.compensation_payload.get("headers"),
                    exchange_name=e.compensation_payload.get("exchange_name")
                )

            if status==SagaStatusEnum.RETRYING:
                raise
            else:
                return
            
        except (Exception,FatalError) as e:
            ic(e)
            error=e
            if not isinstance(e,FatalError):
                error = FatalError(
                    type=ErrorTypeSEnum.FATAL_ERROR,
                    error=SagaStateErrorTypDict(
                        code=ErrorTypeSEnum.FATAL_ERROR.value,
                        debug=serialize_exception(e),
                        user_msg="Something went wrong, please try agian Later"
                    )
                )
            # need to implement a dlq in future
            async with AsyncInfraDbLocalSession() as session:
                await SagaStatesRepo(session=session).update_status(saga_id=saga_id,status=SagaStatusEnum.ATTENTION_REQUIRED.value)
                await SagaStatesRepo(session=session).update_step(key=f"{service_name}.{action}",status=SagaStepsValueEnum.FAILED.value,saga_id=saga_id)
                await SagaStatesRepo(session=session).update_error(error=error.error,saga_id=saga_id)
            ic(error.compensation)
            if error.compensation:
                await RabbitMQMessagingConfig().publish_event(
                    routing_key=e.compensation_payload.get("routing_key"),
                    payload=e.compensation_payload.get("payload"),
                    headers=e.compensation_payload.get("headers"),
                    exchange_name=e.compensation_payload.get("exchange_name")
                )

            return





    @staticmethod
    async def main_handler(msg:AbstractIncomingMessage):
        """This is the core controller for the handling the consumers"""
        routing_key:str=msg.routing_key
        domain,work_for,action,state,version=routing_key.split('.')
        ic(f"Name => {domain}\nWork-For => {work_for}\nAction => {action}\nstate => {state}\nVersion => {version}")
        if f"{domain}.{work_for}"=='accounts.employees':
            ...
        else:
            ic("Unknown event")