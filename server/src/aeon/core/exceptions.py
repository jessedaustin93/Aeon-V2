class CoreMemoryProtectedError(Exception):
    """Raised when code attempts to write to vault/core/ and allow_core_modification is False.

    vault/core/ is the human-gated long-term memory layer. No automated process
    may write there unless a human has explicitly set config.allow_core_modification = True.
    """


class ToolAlreadyRegisteredError(Exception):
    """Raised when registering a tool name that already exists and allow_tool_override is False."""
