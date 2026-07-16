from typing import Dict, Any, Callable, Type, Optional
from src.domain.models.dsl import CommandType


class ActionRegistry:
    def __init__(self):
        self._actions: Dict[CommandType, Callable] = {}

    def register(self, command_type: CommandType):
        def decorator(func: Callable):
            self._actions[command_type] = func
            return func

        return decorator

    def get_action(self, command_type: CommandType) -> Optional[Callable]:
        return self._actions.get(command_type)


action_registry = ActionRegistry()
