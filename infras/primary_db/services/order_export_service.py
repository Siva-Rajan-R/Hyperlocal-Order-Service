import os
import json
from datetime import datetime, timezone
import redis.asyncio as aioredis
from icecream import ic
from ..main import AsyncOrdersLocalSession
from ..repos.order_repo import OrdersRepo
from schemas.v1.request_scheams.order_schema import GetOrderByShopIdSchema
from helpers.export_helper import generate_csv_bytes, generate_xlsx_bytes
from integrations.utility_service import upload_export_file
from helpers.emit_notification import emit_notification

REDIS_URL = os.getenv("PLATFORM_REDIS_URL") or "redis://localhost:6379"

async def process_order_export(payload: dict) -> dict:
    job_id = payload.get("job_id")
    shop_id = payload.get("shop_id")
    from_record = int(payload.get("from_record", 1))
    to_record = int(payload.get("to_record", 100))
    fmt = str(payload.get("format", "csv")).lower()
    query = payload.get("query")
    from_date = payload.get("from_date")
    to_date = payload.get("to_date")
    user_id = payload.get("user_id")
    status = payload.get("status")
    customer_id = payload.get("customer_id")
    origin = payload.get("origin")

    limit = max(to_record - from_record + 1, 1)
    offset = from_record

    redis_client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
    
    # 1. Update status to IN_PROGRESS
    if job_id:
        await redis_client.set(
            f"EXPORT_JOB:{job_id}",
            json.dumps({
                "job_id": job_id,
                "entity": "ORDER",
                "status": "IN_PROGRESS",
                "params": payload,
                "started_at": datetime.now(timezone.utc).isoformat()
            }),
            ex=86400
        )

    try:
        # 2. Fetch Orders
        async with AsyncOrdersLocalSession() as session:
            repo = OrdersRepo(session=session)
            fetch_schema = GetOrderByShopIdSchema(
                shop_id=shop_id,
                query=query or "",
                limit=limit,
                offset=offset,
                from_date=from_date,
                to_date=to_date,
                status=status,
                customer_id=customer_id,
                origin=origin,
                exclude_online=payload.get("exclude_online"),
                exclude_online_orders=payload.get("exclude_online_orders"),
                exclude_online_order=payload.get("exclude_online_order"),
                exclude_offline=payload.get("exclude_offline"),
                exclude_offline_orders=payload.get("exclude_offline_orders"),
                exclude_offline_order=payload.get("exclude_offline_order"),
                exclude_pos=payload.get("exclude_pos"),
                exclude_direct=payload.get("exclude_direct"),
                exclude_return=payload.get("exclude_return"),
                exclude_returns=payload.get("exclude_returns"),
                exclude_returned=payload.get("exclude_returned"),
                exclude_has_return=payload.get("exclude_has_return"),
                exclude_has_returns=payload.get("exclude_has_returns"),
                exclude_with_return=payload.get("exclude_with_return"),
                exclude_with_returns=payload.get("exclude_with_returns"),
                exclude_non_return=payload.get("exclude_non_return"),
                exclude_non_returns=payload.get("exclude_non_returns"),
                exclude_no_return=payload.get("exclude_no_return"),
                exclude_no_returns=payload.get("exclude_no_returns"),
                exclude_without_return=payload.get("exclude_without_return"),
                exclude_without_returns=payload.get("exclude_without_returns"),
            )
            orders = await repo.getby_shop_id(data=fetch_schema)

        # 3. Format Data
        headers = [
            "Order ID", "Invoice No", "Customer ID",
            "Origin", "Status", "Payment Status",
            "Total Amount", "Items Count", "Order Date", "Created Date"
        ]

        rows = []
        for ord_item in (orders or []):
            item_infos = ord_item.get("item_infos") if isinstance(ord_item.get("item_infos"), dict) else {}
            tot_amt = item_infos.get("total_order_amount") or ord_item.get("total_amount") or 0.0
            items_list = ord_item.get("items") or []
            items_count = len(items_list) if isinstance(items_list, list) else 0

            rows.append([
                ord_item.get("ui_id") or ord_item.get("id"),
                ord_item.get("invoice_no") or ord_item.get("ui_id") or "",
                ord_item.get("customer_id") or "",
                ord_item.get("origin") or "POS",
                ord_item.get("status") or "COMPLETED",
                ord_item.get("payment_status") or "COMPLETED",
                tot_amt,
                items_count,
                ord_item.get("date").strftime("%Y-%m-%d") if isinstance(ord_item.get("date"), datetime) else str(ord_item.get("date") or ""),
                ord_item.get("created_at").strftime("%Y-%m-%d %H:%M:%S") if isinstance(ord_item.get("created_at"), datetime) else str(ord_item.get("created_at") or "")
            ])

        # 4. Generate File Bytes
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "xlsx":
            file_bytes = generate_xlsx_bytes(headers, rows, sheet_name="Orders")
            file_name = f"orders_{shop_id}_{from_record}_{to_record}_{timestamp}.xlsx"
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            file_bytes = generate_csv_bytes(headers, rows)
            file_name = f"orders_{shop_id}_{from_record}_{to_record}_{timestamp}.csv"
            content_type = "text/csv"

        # 5. Upload File
        download_url = await upload_export_file(
            file_bytes=file_bytes,
            filename=file_name,
            content_type=content_type
        )

        # 6. Update Redis status to COMPLETED
        result_data = {
            "job_id": job_id,
            "entity": "ORDER",
            "status": "COMPLETED",
            "download_url": download_url,
            "file_name": file_name,
            "total_records": len(rows),
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        if job_id:
            await redis_client.set(
                f"EXPORT_JOB:{job_id}",
                json.dumps(result_data),
                ex=86400
            )

        # 7. Emit Notification Event
        await emit_notification(
            title="Order Export Ready",
            message=f"Export of {len(rows)} order records ({from_record}-{to_record}) is ready for download.",
            type="info",
            user_id=user_id or shop_id,
            additional_metadata={
                "download_url": download_url,
                "file_name": file_name,
                "entity": "ORDER",
                "count": len(rows),
                "job_id": job_id
            }
        )

        return result_data

    except Exception as e:
        ic(f"Error executing order export task: {e}")
        err_data = {
            "job_id": job_id,
            "entity": "ORDER",
            "status": "FAILED",
            "error": str(e),
            "completed_at": datetime.now(timezone.utc).isoformat()
        }
        if job_id:
            await redis_client.set(
                f"EXPORT_JOB:{job_id}",
                json.dumps(err_data),
                ex=86400
            )
        return err_data
    finally:
        await redis_client.aclose()
