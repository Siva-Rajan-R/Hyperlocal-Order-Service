import os
from typing import Any, Dict, List, Optional
import httpx
from icecream import ic


def _get_notification_service_url() -> str:
    env_url = os.getenv("NOTIFICATION_SERVICE_URL")
    if env_url:
        return env_url.strip().rstrip("/")
    if os.path.exists("/.dockerenv") or os.getenv("DOCKER_ENV") == "true":
        return "http://notification-service:8000"
    return "http://127.0.0.1:8009"


async def send_notification(
    *,
    title: str,
    message: str,
    notif_type: str = "info",
    user_id: Optional[str] = None,
    user_ids: Optional[List[str]] = None,
    target_type: str = "particular",
    additional_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Fire-and-forget HTTP notification dispatch to Hyperlocal-Notification-Service."""
    clean_ids = [str(uid).strip() for uid in (user_ids or []) if uid and str(uid).strip()]
    clean_uid = str(user_id).strip() if user_id and str(user_id).strip() else None
    if target_type == "particular" and not clean_uid and not clean_ids:
        return False

    meta = dict(additional_metadata or {})
    meta.setdefault("category", "digital_store")
    meta.setdefault("channel", "digital_store")
    meta.setdefault("origin", "ONLINE")

    payload: Dict[str, Any] = {
        "title": title,
        "message": message,
        "type": notif_type,
        "target_type": target_type,
        "user_id": clean_uid,
        "user_ids": clean_ids if clean_ids else ([clean_uid] if clean_uid else []),
        "additional_metadata": meta,
    }

    url = f"{_get_notification_service_url()}/notifications/send"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                ic(f"Notification service returned {resp.status_code}: {resp.text}")
                return False
            return True
    except Exception as exc:
        ic(f"Failed to send notification to {url}: {exc}")
        return False

