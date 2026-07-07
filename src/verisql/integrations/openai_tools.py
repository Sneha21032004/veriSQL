"""OpenAI-compatible function-calling integration — zero dependencies.

Works with any provider speaking the OpenAI tools API: OpenAI, Groq, Together,
DeepSeek, OpenRouter, vLLM, Ollama. Hand `OPENAI_TOOL_SPECS` to the model,
route its tool calls through `dispatch_tool_call`, feed the result back.

    resp = client.chat.completions.create(model=..., messages=msgs,
                                          tools=OPENAI_TOOL_SPECS)
    for call in resp.choices[0].message.tool_calls or []:
        result = dispatch_tool_call(call.function.name,
                                    call.function.arguments, connector=db)
"""
from __future__ import annotations

import json
from typing import Any

from verisql.integrations._core import fix_payload, verify_payload

_COMMON_PROPERTIES = {
    "sql": {"type": "string", "description": "The SQL query."},
    "question": {
        "type": "string",
        "description": "Natural-language question the SQL answers (enables intent checks).",
    },
    "dialect": {
        "type": "string",
        "description": "SQL dialect: duckdb, postgres, snowflake, bigquery, mysql, tsql.",
    },
}

OPENAI_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "verify_sql",
            "description": (
                "Deterministically verify an SQL query for silent failures: NULL "
                "semantics, cartesian joins, missing date scope, schema errors. "
                "Returns verdict, confidence, and a diagnosis per problem."
            ),
            "parameters": {
                "type": "object",
                "properties": _COMMON_PROPERTIES,
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fix_sql",
            "description": (
                "Verify an SQL query AND auto-repair deterministic bugs (NOT IN "
                "with NULL, timestamp=date equality), then re-verify. Returns "
                "corrected SQL ready to execute. Prefer this before running any query."
            ),
            "parameters": {
                "type": "object",
                "properties": _COMMON_PROPERTIES,
                "required": ["sql"],
            },
        },
    },
]

_HANDLERS = {"verify_sql": verify_payload, "fix_sql": fix_payload}


def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any] | str,
    connector: Any = None,
    policy: Any = None,
) -> dict[str, Any]:
    """Execute a model's tool call and return the JSON-safe result payload.

    Args:
        name: tool name from the model's tool call.
        arguments: parsed dict or the raw JSON string OpenAI-style APIs return.
        connector: optional DB adapter for live checks.
        policy: optional Policy with invariants and governance rules.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name!r} (expected one of {sorted(_HANDLERS)})")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    return handler(
        sql=arguments["sql"],
        question=arguments.get("question", ""),
        dialect=arguments.get("dialect", "duckdb"),
        connector=connector,
        policy=policy,
    )
