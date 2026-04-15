from typing import List
from app.core.enums import OrderStatus, OrderType

class InvalidOrderTransitionError(Exception):
    """Exception raised for invalid order state transitions."""
    def __init__(self, current_status: OrderStatus, target_status: OrderStatus, order_type: OrderType):
        self.current_status = current_status
        self.target_status = target_status
        self.order_type = order_type
        super().__init__(
            f"Cannot transition order of type '{order_type.value}' "
            f"from '{current_status.value}' to '{target_status.value}'."
        )


class OrderStateMachine:
    """
    Manages the state transitions for orders based on the defined business rules.
    """
    
    @staticmethod
    def get_allowed_transitions(current_status: OrderStatus, order_type: OrderType) -> List[OrderStatus]:
        """
        Returns a list of allowed next statuses based on the current status and order type.
        """
        allowed = []
        
        # Any state (except already CANCELLED) can transition to CANCELLED
        if current_status != OrderStatus.CANCELLED and current_status != OrderStatus.COMPLETED and current_status != OrderStatus.DELIVERED:
            allowed.append(OrderStatus.CANCELLED)

        # Logic for NEW
        if current_status == OrderStatus.NEW:
            allowed.append(OrderStatus.CONFIRMED)

        # Logic for CONFIRMED
        elif current_status == OrderStatus.CONFIRMED:
            if order_type in [OrderType.HALL, OrderType.TAKEAWAY]:
                allowed.append(OrderStatus.COMPLETED)
            elif order_type in [OrderType.DELIVERY, OrderType.ONLINE]:
                allowed.append(OrderStatus.DELIVERED)

        return allowed

    @staticmethod
    def validate_transition(current_status: OrderStatus, target_status: OrderStatus, order_type: OrderType) -> None:
        """
        Validates whether the transition from current_status to target_status is allowed.
        Raises InvalidOrderTransitionError if not allowed.
        """
        allowed_transitions = OrderStateMachine.get_allowed_transitions(current_status, order_type)
        if target_status not in allowed_transitions:
            raise InvalidOrderTransitionError(current_status, target_status, order_type)

    def __init__(self, current_status: OrderStatus, order_type: OrderType):
        self.current_status = current_status
        self.order_type = order_type

    def transition_to(self, target_status: OrderStatus) -> OrderStatus:
        """
        Attempts to change the state machine's internal status, raising an error if invalid.
        """
        self.validate_transition(self.current_status, target_status, self.order_type)
        self.current_status = target_status
        return self.current_status
