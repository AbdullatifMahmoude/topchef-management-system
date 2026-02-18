from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Index,
    DateTime,
    Boolean,
    ForeignKey,
    Numeric
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    cat_name = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True,)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True) 
    cat_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    product_name = Column(String(100), unique=True, nullable=False)
    product_price = Column(Numeric(10,2), nullable=False)
    is_available = Column(Boolean, default=True , nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    update_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="products")



