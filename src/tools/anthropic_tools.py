"""Anthropic tool_use definitions for the memory system.

These definitions follow the Anthropic Messages API format for
tool use. Pass these directly to the ``tools`` parameter of
``messages.create()``.

Usage::

    from src.tools.anthropic_tools import MEMORY_TOOLS_ANTHROPIC

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=messages,
        tools=MEMORY_TOOLS_ANTHROPIC,
    )
"""

from __future__ import annotations

from typing import Any

MEMORY_TOOLS_ANTHROPIC: list[dict[str, Any]] = [
    {
        "name": "memory_write",
        "description": (
            "Store a new piece of information about the user or their "
            "preferences to long-term memory. The system will automatically "
            "check for contradictions with existing memories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to store.",
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "procedural"],
                    "description": (
                        "Type: episodic (events), semantic (facts), "
                        "procedural (workflows)"
                    ),
                },
                "importance": {
                    "type": "number",
                    "description": "Importance 0.0-1.0",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categorization tags",
                },
                "source": {
                    "type": "string",
                    "description": (
                        "Source: user_explicit, inferred, conversation, system"
                    ),
                },
            },
            "required": ["content", "memory_type", "importance", "source"],
        },
    },
    {
        "name": "memory_retrieve",
        "description": (
            "Search long-term memory using hybrid semantic + decay scoring."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "procedural"],
                    "description": "Filter by type",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_forget",
        "description": (
            "Soft-delete memories. Never permanently erased. "
            "Call with confirm=false first to preview matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of memory to forget",
                },
                "query": {
                    "type": "string",
                    "description": "Query to find memories to forget",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Confirm deletion after review",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Reason for forgetting (audit trail)"
                    ),
                },
            },
            "required": ["confirm"],
        },
    },
]
