from fastapi import APIRouter, Depends, HTTPException, status
from src.api.auth import get_api_key
from src.api.utils.errors import error_response
from src.infrastructure.queue.session_actor import run_session_actor
from src.api.websockets.manager import manager
from src.domain.models.errors import RedisUnavailableError
from pydantic import BaseModel
from typing import Any, Dict, Optional
import asyncio
import json
import uuid
import redis


router = APIRouter(dependencies=[Depends(get_api_key)])

# Timeout for waiting on a command result via the HTTP endpoint (seconds).
# Kept well below SESSION_INACTIVITY_TIMEOUT so the actor never expires mid-wait.
COMMAND_TIMEOUT = 60.0


class CommandRequest(BaseModel):
    type: str
    params: Optional[Dict[str, Any]] = {}


class CreateSessionRequest(BaseModel):
    headless: bool = True
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    viewport: Dict[str, int] = {"width": 1280, "height": 720}


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    session_id = str(uuid.uuid4())
    try:
        await run_session_actor.kiq(
            session_id,
            headless=request.headless,
            proxy=request.proxy,
            user_agent=request.user_agent,
            viewport=request.viewport,
        )
    except (
        redis.exceptions.ConnectionError,
        redis.exceptions.TimeoutError,
        redis.exceptions.RedisError,
    ) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_response(
                "Session creation temporarily unavailable",
                "REDIS_UNAVAILABLE",
                {"reason": str(e)},
            ),
        )
    return {"session_id": session_id, "status": "active"}


@router.post("/sessions/{session_id}/command")
async def send_command(session_id: str, command: CommandRequest):
    """
    Send a single DSL command to an active session and return the result.

    Publishes the command to the Redis ``cmd:{session_id}`` channel (same
    channel the WebSocket handler uses), then subscribes to ``res:{session_id}``
    for a one-shot result.  The connection is closed immediately after the
    first result message is received or after COMMAND_TIMEOUT seconds.

    This endpoint is the recommended interface for MCP / programmatic clients
    that cannot maintain a persistent WebSocket connection.
    """
    payload = command.model_dump()

    try:
        pubsub = await manager.subscribe_results(session_id)
    except (
        RedisUnavailableError,
        redis.exceptions.ConnectionError,
        redis.exceptions.TimeoutError,
        redis.exceptions.RedisError,
    ) as e:
        if isinstance(e, RedisUnavailableError):
            code, details = e.code, e.details
            error_msg = "Command endpoint temporarily unavailable"
        else:
            code, details = "REDIS_UNAVAILABLE", {"reason": str(e)}
            error_msg = "Command endpoint temporarily unavailable"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_response(error_msg, code, details),
        )
    try:
        try:
            await manager.publish_command(session_id, payload)
        except (
            RedisUnavailableError,
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
            redis.exceptions.RedisError,
        ) as e:
            if isinstance(e, RedisUnavailableError):
                code, details = e.code, e.details
                error_msg = "Command publishing temporarily unavailable"
            else:
                code, details = "REDIS_UNAVAILABLE", {"reason": str(e)}
                error_msg = "Command publishing temporarily unavailable"
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=error_response(error_msg, code, details),
            )

        deadline = asyncio.get_event_loop().time() + COMMAND_TIMEOUT
        async for message in pubsub.listen():
            if asyncio.get_event_loop().time() > deadline:
                await pubsub.unsubscribe(f"res:{session_id}")
                raise HTTPException(
                    status_code=504, detail="Command timed out waiting for result"
                )
            if message["type"] == "message":
                return json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(f"res:{session_id}")

    raise HTTPException(status_code=504, detail="Command timed out waiting for result")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    try:
        await manager.publish_command(session_id, {"type": "stop"})
    except (
        RedisUnavailableError,
        redis.exceptions.ConnectionError,
        redis.exceptions.TimeoutError,
        redis.exceptions.RedisError,
    ) as e:
        if isinstance(e, RedisUnavailableError):
            code, details = e.code, e.details
            error_msg = "Session deletion temporarily unavailable"
        else:
            code, details = "REDIS_UNAVAILABLE", {"reason": str(e)}
            error_msg = "Session deletion temporarily unavailable"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_response(error_msg, code, details),
        )
    return {
        "status": "success",
        "message": f"Session {session_id} termination signal sent",
    }
