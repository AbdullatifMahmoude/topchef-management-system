from app.core.security import get_password_hash
from app.modules.users import schemas, models, repository
from app.core.enums import UserRole
from app.core.exceptions import NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
import re
from app.core.logging import logger

class UserService:
    def __init__(self, db:AsyncSession):
        self.db = db
        self.repo = repository.UserRepository(db)
    
    @staticmethod
    def validate_password(password: str) -> None:
        if not re.search(r"[A-Z]", password):
            raise ValidationError(
                "Password must contain at least one uppercase letter"
            )

        if not re.search(r"[a-z]", password):
            raise ValidationError(
                "Password must contain at least one lowercase letter"
            )

        if not re.search(r"[0-9]", password):
            raise ValidationError(
                "Password must contain at least one digit"
            )
        
    async def get_by_id(self, userid: int):
        user = await self.repo.get_by_id(userid)
        if not user: 
            raise NotFoundError(f"user with id:{userid} not found")
        return user

    async def get_by_name(self, name:str):
        username = await self.repo.get_by_name(name)
        return username
    
    async def list_users(self):
        listusers = await self.repo.list_users()
        return [schemas.UserResponse.model_validate(c) for c in listusers]

    async def create_user(self, data:schemas.CreateUser):
        async with self.db.begin():
            exist_user = await self.get_by_name(data.username)
            if exist_user:
                raise ValidationError(f"user with name: {data.username} already exists")
            exist_phone = await self.repo.get_by_phone(data.phone)
            if exist_phone:
                raise ValidationError(f"user with phone number: {data.phone} already exists")
            self.validate_password(data.password)

            hashed_password = get_password_hash(data.password)
            user_dect = data.model_dump(exclude={"password"})
            user_dect['hashed_password'] = hashed_password

            createuser = await self.repo.create_user(user_dect)
            logger.info(f"User created: username='{data.username}', role={data.role}")
        return schemas.UserResponse.model_validate(createuser)

    async def update_user(self, user_id: int , data:schemas.UpdateUser):
        async with self.db.begin():
            user = await self.get_by_id(user_id)
            
            if data.username is not None:
                exist_name = await self.repo.get_by_name(data.username)
                if exist_name and exist_name.id != user_id:
                    raise ValidationError(
                        f"user with name: '{data.username}' already exists")

            if data.phone is not None:
                exist_phone = await self.repo.get_by_phone(data.phone)
                if exist_phone and exist_phone.id != user_id:
                     raise ValidationError(
                        f"user with phone: '{data.phone}' already exists")
            update_data = data.model_dump(exclude_unset=True)

            if "password" in update_data:
                self.validate_password(update_data["password"])
                user.hashed_password = get_password_hash(update_data["password"])
                update_data.pop("password")

            updateuser = await self.repo.update_user(user, schemas.UpdateUser(**update_data))
            logger.info(f"User updated: id={user_id}, fields={list(update_data.keys())}")
        return schemas.UserResponse.model_validate(updateuser)

    async def delete_user(self, userid: int):
        async with self.db.begin():
            user = await self.get_by_id(userid)
            await self.repo.delete_user(user)
            logger.info(f"User deleted: id={userid}, username='{user.username}'")
        return True

    async def toggle_user(self, user_id):
        async with self.db.begin():
            user = await self.get_by_id(user_id)
            toggle = await self.repo.toggle_user(user)
            logger.info(f"User active status toggled: id={user_id}, now_active={toggle.is_active}")
        return schemas.UserResponse.model_validate(toggle)

