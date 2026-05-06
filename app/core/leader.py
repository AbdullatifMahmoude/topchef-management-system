import asyncio
import os
import socket
from app.core.redis import redis_client
from app.core.logging import logger

class LeaderManager:
    """
    Manages global leader election across multiple instances.
    Ensures that 'Global' tasks only run on one instance.
    """
    def __init__(self, service_name: str = "main_worker"):
        self.service_name = service_name
        self.instance_id = f"{socket.gethostname()}_{os.getpid()}"
        self.is_leader = False
        self._heartbeat_task = None
        self._leader_callbacks = []

    def on_leader_elected(self, callback):
        """Register a callback to run when this instance becomes leader."""
        self._leader_callbacks.append(callback)

    async def start(self):
        if self._heartbeat_task:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Leader manager started for {self.service_name} (ID: {self.instance_id})")

    async def stop(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await redis_client.release_leader_lock(self.service_name, self.instance_id)
            self._heartbeat_task = None
            self.is_leader = False

    async def _heartbeat_loop(self):
        while True:
            try:
                was_leader = self.is_leader
                self.is_leader = await redis_client.acquire_leader_lock(
                    self.service_name, 
                    self.instance_id, 
                    ttl_seconds=15
                )
                
                if self.is_leader and not was_leader:
                    logger.info(f"👑 Instance {self.instance_id} is now the LEADER for {self.service_name}")
                    # Trigger global tasks
                    for callback in self._leader_callbacks:
                        asyncio.create_task(callback())
                elif not self.is_leader and was_leader:
                    logger.warning(f"🏳️ Instance {self.instance_id} lost leadership for {self.service_name}")
                
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Leader heartbeat error: {e}")
                await asyncio.sleep(5)

# Global leader manager instance
global_leader_manager = LeaderManager()
