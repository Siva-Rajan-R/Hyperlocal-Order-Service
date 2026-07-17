import asyncio
from icecream import ic
from typing import Optional, List

async def emit_notification(
    title: str,
    message: str,
    type: str = "info",  # info, error, warning, announcement
    user_id: Optional[str] = None,
    user_ids: Optional[List[str]] = None,
    target_type: str = "particular",  # all, particular
    additional_metadata: Optional[dict] = None
):
    try:
        from messaging.main import RabbitMQMessagingConfig
        rabbitmq_msg_obj = RabbitMQMessagingConfig()
        payload = {
            "title": title,
            "message": message,
            "type": type,
            "user_id": user_id,
            "user_ids": user_ids,
            "target_type": target_type,
            "additional_metadata": additional_metadata or {}
        }
        await rabbitmq_msg_obj.publish_event(
            routing_key="notifications.service.routing.key",
            exchange_name="notifications.service.exchange",
            payload=payload,
            headers={}
        )
        ic(f"Notification event emitted successfully: {title}")
    except Exception as e:
        ic(f"Failed to emit notification event: {e}")
