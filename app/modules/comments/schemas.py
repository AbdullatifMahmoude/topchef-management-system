from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=100)
    stars: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    comment_text: str = Field(..., min_length=1, max_length=1000)


class CommentResponse(CommentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class CommentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    comments: list[CommentResponse]
    average_rating: float | None = None
