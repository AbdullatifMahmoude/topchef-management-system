from app.core.security import get_password_hash
from app.modules.users import schemas, models, repository
from app.core.enums import UserRole
import contextlib
from app.core.exceptions import NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
import re
import json
from app.core.logging import logger

class UserService:
    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis
        self.repo = repository.UserRepository(db)
    
    @contextlib.asynccontextmanager
    async def _transaction_scope(self):
        if self.db.in_transaction():
            yield
        else:
            async with self.db.begin():
                yield
    
    async def _invalidate_delivery_cache(self):
        """Invalidate delivery users cache after any user changes."""
        if self.redis:
            try:
                await self.redis.delete("delivery:users:list")
                logger.info("✓ Invalidated delivery users cache")
            except Exception as e:
                logger.warning(f"Redis error invalidating delivery cache: {e}")
    
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
        
    async def get_by_id(self, userid: int, check_cache: bool = True):
        cache_key = f"user_session:{userid}"
        
        # 1. Try Cache Path
        if check_cache and self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return schemas.UserResponse.model_validate_json(cached)
            except Exception as e:
                logger.warning(f"Redis error getting user {userid}: {e}")

        # 2. Database Path
        user = await self.repo.get_by_id(userid)
        if not user: 
            raise NotFoundError(f"user with id:{userid} not found")
            
        # 3. Save to Cache (10 minutes)
        if self.redis:
            try:
                user_res = schemas.UserResponse.model_validate(user)
                await self.redis.setex(cache_key, 600, user_res.model_dump_json())
            except Exception as e:
                logger.warning(f"Redis error caching user {userid}: {e}")
                
        return user

    async def get_by_name(self, name:str):
        username = await self.repo.get_by_name(name)
        return username
    
    async def list_users(self):
        listusers = await self.repo.list_users()
        return [schemas.UserResponse.model_validate(c) for c in listusers]

    async def list_delivery_users(self):
        cache_key = "delivery:users:list"
        
        # 1. Try Cache Path
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info("⚡ Redis Cache Hit: Delivery Users")
                    data = json.loads(cached)
                    return [schemas.UserResponse(**item) for item in data]
            except Exception as e:
                logger.warning(f"Redis error reading delivery users: {e}")
        
        # 2. Database Path
        listusers = await self.repo.get_by_role(UserRole.DELIVERY)
        response = [schemas.UserResponse.model_validate(c) for c in listusers]
        
        # 3. Save to Cache (1 hour)
        if self.redis:
            try:
                serializable = [u.model_dump(mode='json') for u in response]
                await self.redis.setex(cache_key, 3600, json.dumps(serializable))
            except Exception as e:
                logger.warning(f"Redis error writing delivery users cache: {e}")
        
        return response


    async def create_user(self, data:schemas.CreateUser):
        async with self._transaction_scope():
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
            # Invalidate delivery cache if created user is delivery
            if data.role == UserRole.DELIVERY:
                await self._invalidate_delivery_cache()
            logger.info(f"User created: username='{data.username}', role={data.role}")
        return schemas.UserResponse.model_validate(createuser)

    async def update_user(self, user_id: int , data:schemas.UpdateUser):
        async with self._transaction_scope():
            user = await self.get_by_id(user_id, check_cache=False)
            
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
            
            # Invalidate Redis cache
            if self.redis:
                await self.redis.delete(f"user_session:{user_id}")
                # Invalidate delivery cache if user is or was delivery
                if user.role == UserRole.DELIVERY or (data.role and data.role == UserRole.DELIVERY):
                    await self._invalidate_delivery_cache()
            
            logger.info(f"User updated: id={user_id}, fields={list(update_data.keys())}")
        return schemas.UserResponse.model_validate(updateuser)

    async def delete_user(self, userid: int):
        async with self._transaction_scope():
            user = await self.get_by_id(userid, check_cache=False)
            await self.repo.delete_user(user)
            
            # Invalidate Redis cache
            if self.redis:
                await self.redis.delete(f"user_session:{userid}")
                # Invalidate delivery cache if deleted user is delivery
                if user.role == UserRole.DELIVERY:
                    await self._invalidate_delivery_cache()
                
            logger.info(f"User deleted: id={userid}, username='{user.username}'")
        return True

    async def toggle_user(self, user_id):
        async with self._transaction_scope():
            user = await self.get_by_id(user_id, check_cache=False)
            toggle = await self.repo.toggle_user(user)
            
            # Invalidate Redis cache
            if self.redis:
                await self.redis.delete(f"user_session:{user_id}")
                # Invalidate delivery cache if toggled user is delivery
                if toggle.role == UserRole.DELIVERY:
                    await self._invalidate_delivery_cache()
                
            logger.info(f"User active status toggled: id={user_id}, now_active={toggle.is_active}")
        return schemas.UserResponse.model_validate(toggle)


