import time
from typing import Dict, Any
from src.core.config import settings


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def update_activity(self, session_id: str):
        if session_id not in self.sessions:
            self.sessions[session_id] = {"last_active": time.time()}
        else:
            self.sessions[session_id]["last_active"] = time.time()

    def is_active(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        return (
            time.time() - self.sessions[session_id]["last_active"]
        ) < settings.SESSION_INACTIVITY_TIMEOUT

    def close_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]


session_manager = SessionManager()
