from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.users.models import User


class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.username == username,
                User.is_deleted == False
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(
            select(User).where(
                User.id == user_id,
                User.is_deleted == False
            )
        )
        return result.scalar_one_or_none()

    async def get_users_by_ids(self, user_ids: list[int]) -> list[User]:
        """Get multiple users by IDs."""
        if not user_ids:
            return []
        query = select(User).where(
            User.id.in_(user_ids),
            User.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalars().all()
