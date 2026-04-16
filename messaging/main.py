from aio_pika import RobustConnection,connect_robust,ExchangeType,Message,DeliveryMode
from aio_pika.abc import AbstractIncomingMessage
import orjson,asyncio
from typing import Optional
from icecream import ic

class RabbitMQMessagingConfig:
    def __init__(self,rabbitMQ_connection:Optional[RobustConnection]=None):
        self.rabbitMQ_connection=rabbitMQ_connection
        self.channel=None

    @staticmethod
    async def get_rabbitmq_connection()->RobustConnection:
        connection=await connect_robust()
        return connection
    
    async def _get_channel(self):
        if (self.rabbitMQ_connection==None or self.rabbitMQ_connection.is_closed):
            self.rabbitMQ_connection=await self.get_rabbitmq_connection()
        
        self.channel=await self.rabbitMQ_connection.channel()
        return self.channel
    

    async def create_exchange(self,name:str,exchange_type:ExchangeType):
        ch=await self._get_channel()

        exchange = await ch.declare_exchange(
            name=name,
            type=exchange_type,
            durable=True
        )

        ic(f"Exchange created successfully ✅ -> {exchange}")
        return exchange
    
    async def create_queue(self,routing_key:str,exchange_name:str,queue_name:str):
        ch=await self._get_channel()
        queue=await ch.declare_queue(name=queue_name,durable=True)
        await queue.bind(exchange=exchange_name,routing_key=routing_key)
        ic(f"Queue created successfully ✅ -> {queue}")
        return queue
    
    async def publish_event(self,routing_key:str,payload:dict,headers:dict,exchange_name:str):
        ch=await self._get_channel()
        exchange=await ch.get_exchange(name=exchange_name)
        message=Message(
            body=orjson.dumps(payload),
            headers=headers,
            delivery_mode=DeliveryMode.PERSISTENT
        )
        await exchange.publish(
            message=message,
            routing_key=routing_key
        )
        ic(f"Event published successfully ✅ => {routing_key}, {exchange_name}")


    async def consume_event(self,queue_name:str,handler):
        ch=await self._get_channel()

        queue=await ch.get_queue(name=queue_name)

        await queue.consume(handler)

        ic(f"CONSUMING EVENTS OF -> {queue_name}")