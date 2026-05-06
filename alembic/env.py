from logging.config import fileConfig
from sqlalchemy import create_engine
from alembic import context
from app.core.database import Base, get_sync_engine
from app.core.config import settings
from app.modules.menu.models import Category, Product, Variant
from app.modules.users.models import User
from app.modules.offer.models import Offer, OfferUsage
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.customer.models import Customer, CustomerAddress

# Alembic Config object
config = context.config

# Logging setup
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData للـ autogenerate
target_metadata = Base.metadata

# --------------------------------------------------------
# Offline migrations
# --------------------------------------------------------
def run_migrations_offline() -> None:
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").split("?")[0]
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# --------------------------------------------------------
# Online migrations
# --------------------------------------------------------
def run_migrations_online() -> None:
    connectable = get_sync_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


# --------------------------------------------------------
# Run offline or online
# --------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()