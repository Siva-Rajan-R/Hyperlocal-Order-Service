from .main import RabbitMQMessagingConfig,ExchangeType
from .controllers.controller import ConsumersHandler
import asyncio

async def worker():
    rabbitmq_conn=await RabbitMQMessagingConfig.get_rabbitmq_connection()
    rabbitmq_msg_obj=RabbitMQMessagingConfig(rabbitMQ_connection=rabbitmq_conn)

    # Exchanges
    exchanges=[
        {'name':'inventory.orders.orders.exchange','exc_type':ExchangeType.TOPIC}
    ]

    for exchange in exchanges:
        await rabbitmq_msg_obj.create_exchange(name=exchange['name'],exchange_type=exchange['exc_type'])

    # Queues
    queues=[
        {'exc_name':'inventory.orders.orders.exchange','q_name':'inventory.orders.orders.queue','r_key':'inventory.orders.*.*.v1'},
    ]

    for queue in queues:
        queue=await rabbitmq_msg_obj.create_queue(
            exchange_name=queue['exc_name'],
            queue_name=queue['q_name'],
            routing_key=queue['r_key']
        )

    # Consumers
    consumers=[
        {'q_name':'inventory.orders.orders.queue','handler':ConsumersHandler.main_handler}
    ]

    for consumer in consumers:
        await rabbitmq_msg_obj.consume_event(queue_name=consumer['q_name'],handler=consumer['handler'])

    await asyncio.Event().wait()

    



    