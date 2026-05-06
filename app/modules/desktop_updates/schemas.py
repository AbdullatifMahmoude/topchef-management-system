"""
Pydantic schemas for the desktop update system.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class VersionInfo(BaseModel):
    """Returned by GET /api/desktop/version"""
    version: str = Field(..., examples=["1.2.0"])
    mandatory: bool = Field(False, description="Force update if True")
    notes: str = Field("", description="Release notes / changelog summary")
    download_url: str = Field(..., description="Direct URL for the installer EXE")
    released_at: Optional[datetime] = None
    min_supported_version: Optional[str] = Field(
        None, description="Oldest desktop version still allowed to run"
    )


class ChangelogEntry(BaseModel):
    version: str
    date: str
    notes: str


class ChangelogResponse(BaseModel):
    entries: list[ChangelogEntry]


class MasterDataResponse(BaseModel):
    """Full snapshot of production data to be pulled by the desktop."""
    users: List[dict]
    categories: List[dict]
    products: List[dict]
    variants: List[dict]
    offers: List[dict]
    app_settings: List[dict]
    customers: List[dict]
    customer_addresses: List[dict]
    comments: List[dict]
    orders: List[dict]
    order_items: List[dict]
    order_status_history: List[dict]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DesktopSyncPayload(BaseModel):
    """Payload sent by the desktop app to push locally-queued data."""
    device_id: str
    local_version: str
    orders: list[dict] = Field(default_factory=list)
    order_items: list[dict] = Field(default_factory=list)
    order_status_history: list[dict] = Field(default_factory=list)
    customers: list[dict] = Field(default_factory=list)
    customer_addresses: list[dict] = Field(default_factory=list)
    offer_usages: list[dict] = Field(default_factory=list)
    comments: list[dict] = Field(default_factory=list)


class SyncResult(BaseModel):
    accepted: int = 0
    rejected: int = 0
    errors: list[str] = Field(default_factory=list)
