import asyncio
import json
import time
from typing import Any, Dict, Optional
from redis.asyncio import Redis
from src.core.config import settings
from src.infrastructure.browser.pool_manager import pool_manager
from src.domain.registry.action_registry import action_registry
from src.domain.models.dsl import CommandType
from src.infrastructure.queue.broker import broker


class SessionActor:
    def __init__(
        self,
        session_id: str,
        headless: bool = True,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
    ):
        self.session_id = session_id
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.context = None
        self.page = None

    async def start(self):
        self.context = await pool_manager.create_context(
            headless=self.headless,
            proxy=self.proxy,
            user_agent=self.user_agent,
            viewport=self.viewport,
        )
        self.page = await self.context.new_page()

    async def execute(self, command: Dict[str, Any]) -> Dict[str, Any]:
        action_type = command.get("type")
        if not action_type:
            return {"status": "error", "message": "Missing action type"}

        try:
            command_type = CommandType(action_type)
        except ValueError:
            return {"status": "error", "message": f"Unknown action: {action_type}"}

        params = command.get("params", {})
        action_func = action_registry.get_action(command_type)
        if action_func:
            return await action_func(self.page, params)
        return {"status": "error", "message": f"Unknown action: {action_type}"}

    async def stop(self):
        if self.context:
            await self.context.close()


@broker.task
async def run_session_actor(
    session_id: str,
    headless: bool = True,
    proxy: Optional[str] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, int]] = None,
):
    actor = SessionActor(
        session_id,
        headless=headless,
        proxy=proxy,
        user_agent=user_agent,
        viewport=viewport,
    )
    await actor.start()

    redis = Redis.from_url(settings.REDIS_URL)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"cmd:{session_id}")

    last_active = time.time()

    try:
        while True:
            # Check for inactivity timeout
            if time.time() - last_active > settings.SESSION_INACTIVITY_TIMEOUT:
                break

            try:
                # Listen for commands with a timeout to allow for periodic inactivity check
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True), timeout=10.0
                )
                if message and message["type"] == "message":
                    last_active = time.time()
                    command = json.loads(message["data"])

                    if command.get("type") == "stop":
                        break

                    result = await actor.execute(command)
                    await redis.publish(f"res:{session_id}", json.dumps(result))
            except asyncio.TimeoutError:
                continue
    finally:
        await pubsub.unsubscribe(f"cmd:{session_id}")
        await actor.stop()
        await redis.close()
