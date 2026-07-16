from src.infrastructure.browser.session_manager import session_manager
from src.infrastructure.queue.broker import broker


@broker.task
async def cleanup_sessions():
    sessions_to_close = []
    for session_id in session_manager.sessions:
        if not session_manager.is_active(session_id):
            sessions_to_close.append(session_id)

    for session_id in sessions_to_close:
        session_manager.close_session(session_id)
        # In a real implementation, we would also stop the Taskiq actor here
