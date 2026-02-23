from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Index,
    DateTime,
    Boolean,
    ForeignKey,
    Numeric,
    Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from enum import Enum
from app.core.enums import ProductType 




class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    cat_name = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True,)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    products = relationship("Product", back_populates="category",cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    cat_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    product_name = Column(String(100), unique=True, nullable=False)
    product_type = Column(
        SQLEnum(ProductType, name="product_type_enum"), nullable=False)
    description = Column(String(500), nullable=True)
    is_available = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    update_at = Column(DateTime, default=datetime.utcnow,
                       onupdate=datetime.utcnow, nullable=False)

    category = relationship("Category", back_populates="products")
    variants = relationship("Variant", back_populates="product",cascade="all, delete-orphan")


class Variant(Base):
    __tablename__ = "variants"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    name = Column(String(50), nullable=False)
    price = Column(Numeric(10,2), nullable=False, default=0)

    
    product = relationship("Product", back_populates="variants")


class Addon(Base):
    __tablename__ = "addons"

    id = Column(Integer, primary_key=True, index=True)
    addon_name = Column(String(50), unique=True, nullable=False)
    addon_price = Column(Numeric(10,2), nullable=False, default=0)
