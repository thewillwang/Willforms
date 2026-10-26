"""Wire protocol shared by the cloud brain, the software duck and (later) the firmware.

See docs/02-architecture.md §3.1. One WebSocket connection carries:
  * JSON text frames  -> `embody.proto.messages`
  * binary frames     -> `embody.proto.binary`
Body API tool definitions (what the LLM can call) -> `embody.proto.tools`.
"""
from .messages import *  # noqa: F401,F403
from .binary import BinaryFrame, BinaryType, pack_binary, unpack_binary  # noqa: F401
from .tools import (  # noqa: F401
    EMOTIONS,
    GESTURES,
    LOOK_DIRECTIONS,
    PHASE0_TOOLS,
    tool_names,
)
