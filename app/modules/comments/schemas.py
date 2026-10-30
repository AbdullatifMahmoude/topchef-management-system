from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.business_calendar import order_time_in_cairo


class CommentCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=100)
    stars: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    comment_text: str = Field(..., min_length=1, max_length=1000)


class CommentResponse(CommentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def display_created_at(cls, value):
        return order_time_in_cairo(value) if isinstance(value, datetime) and value.tzinfo is None else value


class CommentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    comments: list[CommentResponse]
    average_rating: float | None = None
