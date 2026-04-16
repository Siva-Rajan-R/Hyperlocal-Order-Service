from aio_pika.abc import AbstractIncomingMessage
from dataclasses import dataclass
from typing import List
from hyperlocal_platform.core.enums.routingkey_enum import RoutingkeyActions
from icecream import ic

@dataclass(frozen=True)
class CompensationController:
    msg:AbstractIncomingMessage

    def decide(self,saga_payload:dict)->bool:
        """This method will proccess and decide the compenstaion for the controller
        based on the incoming message,and the payload of saga.
        """
        routing_key:str=self.msg.routing_key
        domain,work_for,action,state,version=routing_key.split('.')

        key:str=f"{domain}.{action}"

        ic(key,saga_payload,domain=='accounts' and key in [f"accounts.{RoutingkeyActions.CREATE.value}"])
        if domain=='accounts' and key in [f"accounts.{RoutingkeyActions.CREATE.value}"]:
            ic("hello",saga_payload['data'].get("accounts").get('is_new'))
            if saga_payload['data'].get("accounts").get('is_new'):
                ic(True)
                return True
        
        
        return False