import asyncio

from app.core.leader import global_leader_manager
from app.core.logging import logger


async def run_daily_reconciliation():
    """
    Example of a Global Singleton Task.
    This should ONLY run on the leader instance.
    """
    while global_leader_manager.is_leader:
        logger.info("🛠 Global Task: Running database integrity check...")
        # Simulate work
        await asyncio.sleep(60)
        logger.info("✅ Global Task: Integrity check complete.")
        
        # Wait until next cycle
        await asyncio.sleep(3600) # Once per hour

def init_global_workers():
    """
    Registers all global background tasks.
    These will automatically start when an instance becomes LEADER.
    """
    global_leader_manager.on_leader_elected(run_daily_reconciliation)
    # Add more global tasks here...
