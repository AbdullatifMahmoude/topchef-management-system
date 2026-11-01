from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.users import models, schemas


def deleted_username(user_id: int) -> str:
    """Unique tombstone that always fits the username VARCHAR(200)."""
    return f"deleted_user_{user_id}"


def deleted_phone(user_id: int) -> str:
    """Unique tombstone that always fits the phone VARCHAR(15)."""
    return f"D{user_id:014d}"


class UserRepository:
    def __init__(self, db:AsyncSession):
        self.db = db

    async def get_by_id(self, user_id:int):
        user = await self.db.execute(select(models.User).where(
            models.User.id == user_id,
            models.User.is_deleted == False
        ))
        return user.scalar_one_or_none()

    async def get_by_name(self, user_name:str):
        username = await self.db.execute(select(models.User).where(
            models.User.username == user_name,
            models.User.is_deleted == False
        ))
        return username.scalar_one_or_none()
    
    async def get_by_phone(self, user_phone: str):
        userphone = await self.db.execute(select(models.User).where(
            models.User.phone == user_phone,
            models.User.is_deleted == False
        ))
        return userphone.scalar_one_or_none()

    async def get_by_role(self, user_role: str):
        rolelist = await self.db.execute(select(models.User).where(
            models.User.role == user_role,
            models.User.is_deleted == False
        ))
        return rolelist.scalars().all()

    async def list_users(self):
        userslist = await self.db.execute(
            select(models.User).where(models.User.is_deleted == False).order_by(models.User.id)
        )
        return userslist.scalars().all()
    
    async def create_user(self, userdata: schemas.CreateUser):
        new_user = models.User(**userdata)
        self.db.add(new_user)
        return new_user

    async def update_user(self, user:models.User , user_data: schemas.UpdateUser):
        updateuser = user_data.model_dump(exclude_unset=True)

        for key, value in updateuser.items():
            setattr(user, key, value)

        return user

    async def delete_user(self, user: models.User):
        user.is_deleted = True
        user.username = deleted_username(user.id)
        user.phone = deleted_phone(user.id)
    
    async def toggle_user(self, user: models.User):
        user.toggle_active()
        self.db.add(user)
        return user
