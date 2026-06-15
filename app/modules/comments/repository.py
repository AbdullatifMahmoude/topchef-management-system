from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional, Tuple, List
from app.modules.comments import models, schemas


class CommentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, comment_data: schemas.CommentCreate) -> models.Comment:
        """Create a new comment in the database."""
        comment = models.Comment(**comment_data.model_dump())
        self.db.add(comment)
        try:
            await self.db.commit()
            await self.db.refresh(comment)
            return comment
        except Exception:
            await self.db.rollback()
            raise

    async def get_by_id(self, comment_id: int) -> Optional[models.Comment]:
        """Get a comment by ID."""
        query = select(models.Comment).where(
            models.Comment.id == comment_id,
            models.Comment.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[int, List[models.Comment]]:
        """Get paginated comments, ordered by newest first."""
        query = select(models.Comment).where(models.Comment.is_deleted == False).order_by(desc(models.Comment.created_at))
        
        # Count total
        count_query = select(func.count()).select_from(models.Comment).where(models.Comment.is_deleted == False)
        total = await self.db.scalar(count_query) or 0
        
        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        return total, result.scalars().all()

    async def get_average_rating(self) -> Optional[float]:
        """Get average rating of all comments."""
        query = select(func.avg(models.Comment.stars)).where(models.Comment.is_deleted == False)
        result = await self.db.scalar(query)
        return float(result) if result else None
