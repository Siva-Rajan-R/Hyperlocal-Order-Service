from pydantic import BaseModel, Field
from typing import Optional, Literal

class ExportDataRequestSchema(BaseModel):
    shop_id: str
    from_record: Optional[int] = Field(default=1, ge=1, description="Starting record index (1-indexed)")
    to_record: Optional[int] = Field(default=100, ge=1, description="Ending record index (1-indexed)")
    format: Optional[Literal["csv", "xlsx"]] = Field(default="csv", description="File format: csv or xlsx")
    query: Optional[str] = Field(default=None, description="Search term filter")
    from_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    to_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    user_id: Optional[str] = Field(default=None, description="Requesting User ID for notification")
    status: Optional[str] = Field(default=None, description="Status filter")
    customer_id: Optional[str] = Field(default=None, description="Customer filter")
    origin: Optional[str] = Field(default=None, description="Order origin: POS or ONLINE")

class ExportJobResponseSchema(BaseModel):
    job_id: str
    entity: str
    status: str = "QUEUED"
    message: str = "Export task scheduled successfully in the background"

class ExportStatusResponseSchema(BaseModel):
    job_id: str
    entity: str
    status: str  # QUEUED, IN_PROGRESS, COMPLETED, FAILED
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    total_records: Optional[int] = 0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
