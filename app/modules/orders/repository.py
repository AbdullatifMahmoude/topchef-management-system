from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Optional, List
from app.modules.orders import models, schemas



class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, idnumber: int):
        return self.db.query(models.Order).filter(
            models.Order.id == idnumber).first()

    def get_by_number(self, ordernumber: str, orderdate: Optional[date] = None):
        query = self.db.query(models.Order).filter(
            models.Order.order_number == ordernumber)
        if orderdate is None:
            orderdate = date.today()

        return query.filter(
            models.Order.order_date == orderdate).first()

    def list_orders(self,
                    ordersource: Optional[models.OrderSource] = None,
                    orderstatus: Optional[models.OrderStatus] = None,
                    ordertype: Optional[models.OrderType] = None):
        query = self.db.query(models.Order)
        if ordersource:
            query = query.filter(
                models.Order.order_source == ordersource)

        if orderstatus:
            query = query.filter(
                models.Order.order_status == orderstatus)

        if ordertype:
            query = query.filter(
                models.Order.order_type == ordertype)
        today = date.today()
        yesterday = today - timedelta(days=1)
        query = query.filter(models.Order.order_date.in_([today, yesterday]))
        query = query.order_by(models.Order.created_at.desc())

        return query.all()

    def _get_next_order_number(self):
        today = date.today()
        last_order = self.db.query(models.Order).filter(
            models.Order.order_date == today).order_by(models.Order.order_number.desc()).first()

        if last_order is None:
            return "001"
        
        last_number = int(last_order.order_number)
        next_number = last_number + 1

        return f"{next_number:03d}"

    def create_order(self, order_data: schemas.OrderCreate) -> models.Order:
        next_number = self._get_next_order_number()
    
        items_data = order_data.items
        order_dict = order_data.dict(exclude={'items'})  
        
      
        order_dict['order_number'] = next_number
        order_dict['order_date'] = date.today()
        
       
        new_order = models.Order(**order_dict)
        
        
        for item_data in items_data:
            item = models.OrderItem(**item_data.dict())
            new_order.items.append(item)
        
        return new_order

    def save_order(self, order: models.Order) -> models.Order:
        """يحفظ الـ Order بعد ما Pricing يحسب"""
        
        self.db.add(order)
        
        try:
            self.db.commit()
            self.db.refresh(order)
            return order
        except Exception:
            self.db.rollback()
            raise

    # app/modules/orders/repository.py

from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Optional, List
from app.modules.orders import models, schemas


class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, idnumber: int) -> Optional[models.Order]:
        return self.db.query(models.Order).filter(
            models.Order.id == idnumber
        ).first()

    def get_by_number(
        self, 
        ordernumber: str, 
        orderdate: Optional[date] = None
    ) -> Optional[models.Order]:
        if orderdate is None:
            orderdate = date.today()
        
        return self.db.query(models.Order).filter(
            models.Order.order_number == ordernumber,
            models.Order.order_date == orderdate
        ).first()

    def list_orders(
        self,
        ordersource: Optional[models.OrderSource] = None,
        orderstatus: Optional[models.OrderStatus] = None,
        ordertype: Optional[models.OrderType] = None
    ) -> List[models.Order]:
        query = self.db.query(models.Order)
        
        if ordersource:
            query = query.filter(models.Order.order_source == ordersource)
        
        if orderstatus:
            query = query.filter(models.Order.order_status == orderstatus)
        
        if ordertype:
            query = query.filter(models.Order.order_type == ordertype)
        
        today = date.today()
        yesterday = today - timedelta(days=1)
        query = query.filter(models.Order.order_date.in_([today, yesterday]))
        query = query.order_by(models.Order.created_at.desc())
        
        return query.all()

    def _get_next_order_number(self) -> str:
        today = date.today()
        last_order = self.db.query(models.Order).filter(
            models.Order.order_date == today
        ).order_by(models.Order.order_number.desc()).first()
        
        if last_order is None:
            return "001"
        
        last_number = int(last_order.order_number)
        next_number = last_number + 1
        
        return f"{next_number:03d}"

    def create_order(
        self, 
        order_data: schemas.OrderCreate
    ) -> models.Order:
        """يحضر الـ Order من غير حسابات — Pricing Module يكمل"""
        
        # 1. الرقم التالي
        next_number = self._get_next_order_number()
        
        # 2. نفك الـ items
        items_data = order_data.items
        order_dict = order_data.dict(exclude={'items'})
        
        # 3. نضيف الرقم والتاريخ
        order_dict['order_number'] = next_number
        order_dict['order_date'] = date.today()
        
        # 4. نعمل الـ Order (لسه في الذاكرة)
        new_order = models.Order(**order_dict)
        
        # 5. نضيف الـ Items
        for item_data in items_data:
            item = models.OrderItem(**item_data.dict())
            new_order.items.append(item)
        
        # 6. نرجع من غير commit — Pricing يكمل
        return new_order

    def save_order(self, order: models.Order) -> models.Order:
        """يحفظ الـ Order بعد ما Pricing يحسب"""
        
        self.db.add(order)
        
        try:
            self.db.commit()
            self.db.refresh(order)
            return order
        except Exception:
            self.db.rollback()
            raise

    def update_order(
        self, 
        order: models.Order, 
        update_data: schemas.OrderUpdate
    ) -> models.Order:
        """يحدد الـ Order"""
        
        # نحدد الحقول اللي جات
        update_dict = update_data.dict(exclude_unset=True)
        
        for field, value in update_dict.items():
            setattr(order, field, value)
        
        order.updated_at = datetime.utcnow()
        
        try:
            self.db.commit()
            self.db.refresh(order)
            return order
        except Exception:
            self.db.rollback()
            raise
