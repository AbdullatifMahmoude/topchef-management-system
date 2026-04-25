from typing import Any, Dict, Optional
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log

class CustomerService:
    def get_or_create_customer(self, phone: str, name: str) -> Dict[str, Any]:
        """
        Retrieve a customer by phone or create a new one if not found.
        Matches the logic in the cloud CustomerService.
        """
        if not phone:
            return {}
            
        customer = local_repository.get_customer_by_phone(phone)
        if customer:
            return customer
            
        # Create new local customer
        log.info("Creating new local customer: %s (%s)", name, phone)
        return local_repository.create_customer({
            "name": name,
            "phone_number": phone
        })

    def add_address(self, customer_id: int, address: str) -> Dict[str, Any]:
        """Add a new address for a customer."""
        return local_repository.add_customer_address(customer_id, address)

customer_service = CustomerService()
