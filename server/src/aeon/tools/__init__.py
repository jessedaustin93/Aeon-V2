"""Built-in Aeon-V2 tool handlers.

Each submodule exposes DEFINITIONS (list[ToolDefinition]) and
HANDLERS (dict[name, callable(arguments, config) -> dict]).
"""
from typing import Callable, Dict, List, Tuple

from aeon.core.config import Config
from aeon.core.tools import ToolDefinition

from . import crypto, fs, memory, mesh, models, planning, safecli, services, shell, skills, snifferops, ssh, vault, web

_MODULES = [fs, shell, web, memory, vault, skills, mesh, crypto, safecli, services, planning, snifferops, models, ssh]


def all_handlers(config: Config) -> Tuple[Dict[str, Callable], List[ToolDefinition]]:
    handlers: Dict[str, Callable] = {}
    definitions: List[ToolDefinition] = []
    for module in _MODULES:
        handlers.update(module.HANDLERS)
        definitions.extend(module.DEFINITIONS)
    return handlers, definitions
