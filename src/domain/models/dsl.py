from enum import Enum
from pydantic import BaseModel
from typing import Dict, Any, Optional


class InteractiveSession(BaseModel):
    id: str
    status: str = "starting"
    last_active: float
    browser_process_id: Optional[str] = None


class CommandType(str, Enum):
    GOTO = "goto"
    CLICK_COORD = "click_coord"
    CLICK_OMNI = "click_omni"
    TYPE = "type"
    SCROLL = "scroll"
    SCREENSHOT = "screenshot"
    EXTRACT_JINA = "extract_jina"
    YANDEX_MAPS_EXTRACT = "yandex_maps_extract"
    YANDEX_MAPS_REVIEWS = "yandex_maps_reviews"


class Command(BaseModel):
    type: CommandType
    params: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
