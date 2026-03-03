from fastapi import APIRouter, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.users import schemas, service
from typing import List
from app.core.database import get_db


router = APIRouter(prefix="/user", tags=['user'])

@router.get("/users",response_model=List[schemas.UserResponse] )
async def get_list(db: AsyncSession = Depends(get_db)):
    user_service = service.UserService(db)
    get_list = await user_service.list_users()
    return get_list

@router.get("/users/{id}", response_model=schemas.UserResponse)
async def get_user_by_id(id:int , db: AsyncSession = Depends(get_db)):
    user_service = service.UserService(db)
    get_user = await user_service.get_by_id(id)
    return get_user

@router.post("/users", response_model=schemas.UserResponse, status_code= status.HTTP_201_CREATED)
async def create_user(data: schemas.CreateUser, db: AsyncSession = Depends(get_db)):
    user_service = service.UserService(db)
    createuser = await user_service.create_user(data)
    return createuser
 