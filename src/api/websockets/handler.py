from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.api.websockets.manager import manager
import json
import asyncio

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pubsub = await manager.subscribe_results(session_id)

    async def listen_to_redis():
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"].decode())

    asyncio.create_task(listen_to_redis())

    try:
        while True:
            data = await websocket.receive_text()
            command = json.loads(data)
            await manager.publish_command(session_id, command)
    except WebSocketDisconnect:
        await pubsub.unsubscribe(f"res:{session_id}")
