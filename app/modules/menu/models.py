from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base, DbEnum
from app.core.enums import ProductType


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    cat_name = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True,)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    products = relationship("Product", back_populates="category",cascade="all, delete-orphan")

    def toggle_active(self):
        self.is_active = not self.is_active
        return self.is_active


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    cat_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    product_name = Column(String(255), nullable=False)
    product_type = Column(
        DbEnum(ProductType, name="product_type_enum"),
        nullable=False,
    )
    description = Column(String(500), nullable=True)
    is_available = Column(Boolean, default=True, nullable=False)
    temporary_unavailable_until = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                       onupdate=datetime.utcnow, nullable=False)

    category = relationship("Category", back_populates="products")
    variants = relationship("Variant", back_populates="product",cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('product_name', 'cat_id', name='uq_product_name_cat_id'),
    )

    def toggle_availability(self):
        self.is_available = not self.is_available
        return self.is_available

    @property
    def is_temporarily_unavailable(self) -> bool:
        return bool(
            self.temporary_unavailable_until
            and self.temporary_unavailable_until > datetime.now(UTC).replace(tzinfo=None)
        )


class Variant(Base):
    __tablename__ = "variants"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    price = Column(Numeric(10,2), nullable=False, default=0)
    is_deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    
    product = relationship("Product", back_populates="variants")


class ProductChangeLog(Base):
    __tablename__ = "product_change_logs"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    change_type = Column(String(30), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = relationship("Product")
    changed_by = relationship("User")
