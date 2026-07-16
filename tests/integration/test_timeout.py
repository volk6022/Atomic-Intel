import pytest
import asyncio
import time
from src.infrastructure.browser.session_manager import session_manager
from src.infrastructure.queue.cleanup_worker import cleanup_sessions


@pytest.mark.asyncio
async def test_session_auto_termination():
    session_id = "test-session"
    session_manager.update_activity(session_id)
    session_manager.sessions[session_id]["last_active"] = time.time() - 700

    await cleanup_sessions()
    assert session_id not in session_manager.sessions
