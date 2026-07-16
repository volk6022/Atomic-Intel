import pytest
import time
from src.infrastructure.browser.session_manager import session_manager


def test_session_inactivity():
    session_id = "test-session"
    session_manager.update_activity(session_id)
    assert session_manager.is_active(session_id) is True

    # Mocking time for timeout
    session_manager.sessions[session_id]["last_active"] = time.time() - 700
    assert session_manager.is_active(session_id) is False
