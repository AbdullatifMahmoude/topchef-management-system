import asyncio
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.leader import global_leader_manager
from app.core.logging import logger
from app.core.redis import redis_client


async def main():
    logger.info("🚀 Starting Global Worker Process...")
    
    # 1. Initialize shared resources
    await redis_client.connect()
    
    # 2. Start Leader Election
    # Only one instance of this script will become the 'Active' worker
    await global_leader_manager.start()
    
    try:
        while True:
            if global_leader_manager.is_leader:
                # --- GLOBAL BACKGROUND TASKS GO HERE ---
                # Example: process_dead_letter_queue()
                # Example: run_daily_reports()
                pass
            
            await asyncio.sleep(5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker shutting down...")
    finally:
        await global_leader_manager.stop()
        await redis_client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
