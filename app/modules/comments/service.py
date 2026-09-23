
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.comments import models, schemas
from app.modules.comments.repository import CommentRepository


class CommentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = CommentRepository(db)

    async def create_comment(self, comment_data: schemas.CommentCreate) -> models.Comment:
        """
        Create a new comment from customer.
        No authentication required.
        """
        return await self.repository.create(comment_data)

    async def get_comment(self, comment_id: int) -> models.Comment:
        """Get a specific comment by ID."""
        comment = await self.repository.get_by_id(comment_id)
        if not comment:
            raise NotFoundError(f"Comment with ID {comment_id}")
        return comment

    async def list_comments_paginated(
        self,
        page: int = 1,
        page_size: int = 50
    ) -> tuple[int, list[models.Comment], float | None]:
        """Get paginated comments with average rating."""
        total, comments = await self.repository.list_paginated(page=page, page_size=page_size)
        average_rating = await self.repository.get_average_rating()
        return total, comments, average_rating
