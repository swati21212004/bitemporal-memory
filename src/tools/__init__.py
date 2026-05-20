"""Tool definitions for AI provider integrations.

Contains ready-to-use tool/function definitions for:
- OpenAI function calling format
- Anthropic tool_use format
"""

from src.tools.anthropic_tools import MEMORY_TOOLS_ANTHROPIC
from src.tools.openai_tools import MEMORY_TOOLS_OPENAI

__all__ = ["MEMORY_TOOLS_OPENAI", "MEMORY_TOOLS_ANTHROPIC"]
