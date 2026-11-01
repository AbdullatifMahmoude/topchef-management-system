from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.comments import schemas
from app.modules.comments.service import CommentService


# Dependency to get service
async def get_comment_service(db: AsyncSession = Depends(get_db)) -> CommentService:
    return CommentService(db)


router = APIRouter(prefix="/comments", tags=["Comments"])


@router.post("/", response_model=schemas.CommentResponse)
async def create_comment(
    comment_data: schemas.CommentCreate,
    service: CommentService = Depends(get_comment_service)
):
    """
    Create a new comment from customer.
    No authentication required.
    """
    return await service.create_comment(comment_data)


@router.get("/", response_model=schemas.CommentListResponse)
async def list_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    service: CommentService = Depends(get_comment_service)
):
    """
    List all comments with pagination.
    No authentication required.
    """
    total, comments, average_rating = await service.list_comments_paginated(
        page=page,
        page_size=page_size
    )
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "comments": comments,
        "average_rating": average_rating
    }


@router.get("/{comment_id}", response_model=schemas.CommentResponse)
async def get_comment(
    comment_id: int,
    service: CommentService = Depends(get_comment_service)
):
    """
    Get a specific comment by ID.
    No authentication required.
    """
    return await service.get_comment(comment_id)
