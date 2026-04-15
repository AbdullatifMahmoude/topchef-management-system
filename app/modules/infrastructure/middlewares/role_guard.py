from typing import List

from fastapi import Depends

from app.core.enums import UserRole
from app.core.exceptions import AuthorizationError
from app.core.logging import logger
from app.modules.auth.dependencies import get_current_user


# ─── Role Capabilities Registry ───────────────────────────────
# Maps each role to the set of capabilities it has.
# This is the "Role Registry" from the RBAC sequence diagram.

class Capability:
    """All capability constants used across the system."""
    # Menu capabilities
    VIEW_MENU = "view_menu"
    MANAGE_MENU = "manage_menu"           # create/update/delete categories & products
    MANAGE_PRICES = "manage_prices"

    # User capabilities
    MANAGE_USERS = "manage_users"         # create/update/delete/toggle users

    # Order capabilities (prepared for orders module)
    CREATE_ORDER = "create_order"
    VIEW_ORDERS = "view_orders"
    UPDATE_ORDER_STATUS = "update_order_status"
    CANCEL_ORDER = "cancel_order"
    PRINT_ORDER = "print_order"

    # Delivery capabilities
    UPDATE_DELIVERY_STATUS = "update_delivery_status"

    # Offer capabilities
    VIEW_OFFERS = "view_offers"
    MANAGE_OFFERS = "manage_offers"

    # Full access
    FULL_ACCESS = "full_access"


ROLE_CAPABILITIES: dict[UserRole, set[str]] = {
    UserRole.ADMIN: {
        Capability.FULL_ACCESS,         # Admin has everything
    },
    UserRole.CASHIER: {
        Capability.VIEW_MENU,
        Capability.CREATE_ORDER,
        Capability.VIEW_ORDERS,
        Capability.UPDATE_ORDER_STATUS,
        Capability.CANCEL_ORDER,
        Capability.PRINT_ORDER,
        Capability.VIEW_OFFERS,
    },
    UserRole.DELIVERY: {
        Capability.VIEW_ORDERS,
        Capability.UPDATE_DELIVERY_STATUS,
    },
}


def _has_capability(role: UserRole, required_capability: str) -> bool:
    """Check if a role has a specific capability."""
    capabilities = ROLE_CAPABILITIES.get(role, set())

    # Admin with FULL_ACCESS bypasses all capability checks
    if Capability.FULL_ACCESS in capabilities:
        return True

    return required_capability in capabilities


def _has_role(user_role: UserRole, allowed_roles: List[UserRole]) -> bool:
    """Check if user's role is in the list of allowed roles."""
    return user_role in allowed_roles


# ─── FastAPI Dependencies ───────────────────────────────────────

def require_role(*allowed_roles: UserRole):
    async def _role_dependency(current_user=Depends(get_current_user)):
        if not _has_role(current_user.role, list(allowed_roles)):
            logger.warning(
                f"Role guard blocked: user={current_user.username} "
                f"role={current_user.role.value} "
                f"required_roles={[r.value for r in allowed_roles]}"
            )
            raise AuthorizationError(
                f"Role '{current_user.role.value}' is not authorized for this action. "
                f"Required: {[r.value for r in allowed_roles]}"
            )
        return current_user

    return _role_dependency


def require_capability(capability: str):
    async def _capability_dependency(current_user=Depends(get_current_user)):
        if not _has_capability(current_user.role, capability):
            logger.warning(
                f"Capability guard blocked: user={current_user.username} "
                f"role={current_user.role.value} "
                f"required_capability={capability}"
            )
            raise AuthorizationError(
                f"Role '{current_user.role.value}' does not have "
                f"'{capability}' capability"
            )
        return current_user

    return _capability_dependency
