"""OpenAI function calling tool definitions for the memory system.

These definitions follow the OpenAI Chat Completions API format for
function calling with ``strict: true`` mode enabled. Pass these
directly to the ``tools`` parameter of ``chat.completions.create()``.

Usage::

    from src.tools.openai_tools import MEMORY_TOOLS_OPENAI

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=MEMORY_TOOLS_OPENAI,
    )
"""

from __future__ import annotations

from typing import Any

MEMORY_TOOLS_OPENAI: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": (
                "Store a new piece of information about the user or their "
                "preferences to long-term memory. Use this when the user "
                "shares personal details, preferences, important context, or "
                "procedural knowledge that should be remembered across "
                "sessions. The system will automatically check for "
                "contradictions with existing memories."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "The information to store. Should be a clear, "
                            "concise statement of fact or preference."
                        ),
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "procedural"],
                        "description": (
                            "Type of memory. episodic = events/conversations, "
                            "semantic = facts/preferences, "
                            "procedural = how-to/workflows"
                        ),
                    },
                    "importance": {
                        "type": "number",
                        "description": (
                            "How important this memory is from 0.0 to 1.0. "
                            "User-stated preferences should be 0.7-0.9. "
                            "Inferred info should be 0.3-0.5."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional tags for categorization "
                            '(e.g., ["preference", "coding", "ui"])'
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "How this memory was obtained: user_explicit, "
                            "inferred, conversation, or system"
                        ),
                    },
                },
                "required": [
                    "content",
                    "memory_type",
                    "importance",
                    "tags",
                    "source",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_retrieve",
            "description": (
                "Search long-term memory for information relevant to a "
                "query. Uses hybrid semantic similarity + temporal decay "
                "scoring. Use this to recall user preferences, past "
                "conversations, or procedural knowledge."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language query to search memories for."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": (
                            "Maximum number of memories to return "
                            "(1-100, default 10)"
                        ),
                    },
                    "memory_type": {
                        "type": ["string", "null"],
                        "enum": [
                            "episodic",
                            "semantic",
                            "procedural",
                            None,
                        ],
                        "description": (
                            "Filter by memory type, or null for all types"
                        ),
                    },
                    "tags": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": (
                            "Filter by tags (memories must contain ALL "
                            "specified tags), or null for no filter"
                        ),
                    },
                },
                "required": ["query", "top_k", "memory_type", "tags"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_forget",
            "description": (
                "Request to forget/remove a specific memory or memories "
                "matching a query. Memories are soft-deleted (never "
                "permanently erased) to preserve bitemporal history. The "
                "user must confirm before deletion occurs."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": ["string", "null"],
                        "description": (
                            "UUID of specific memory to forget, or null "
                            "to use query-based matching"
                        ),
                    },
                    "query": {
                        "type": ["string", "null"],
                        "description": (
                            "Natural language query to find memories to "
                            'forget (e.g., "forget everything about my '
                            'ex"), or null to use memory_id'
                        ),
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": (
                            "Set to true to confirm deletion after "
                            "reviewing matches. First call with false "
                            "to preview."
                        ),
                    },
                    "reason": {
                        "type": ["string", "null"],
                        "description": (
                            "Optional reason for forgetting "
                            "(logged in audit trail)"
                        ),
                    },
                },
                "required": [
                    "memory_id",
                    "query",
                    "confirm",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
    },
]
