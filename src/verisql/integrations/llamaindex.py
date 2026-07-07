"""LlamaIndex adapter — VeriSQL's oracle as LlamaIndex FunctionTools.

    pip install verisql[llamaindex]

    from verisql.integrations.llamaindex import make_verisql_tools
    tools = make_verisql_tools(connector=db)
    agent = ReActAgent.from_tools(tools, llm=llm)
"""
from __future__ import annotations

from typing import Any

from verisql.integrations._core import fix_payload, verify_payload


def make_verisql_tools(
    connector: Any = None,
    dialect: str = "duckdb",
    policy: Any = None,
) -> list:
    """Build [verify_sql, fix_sql] LlamaIndex FunctionTools bound to your database.

    Raises ImportError with an install hint when llama-index-core is missing.
    """
    try:
        from llama_index.core.tools import FunctionTool
    except ImportError as e:
        raise ImportError(
            "llama-index-core is required for this adapter: pip install verisql[llamaindex]"
        ) from e

    def verify_sql(sql: str, question: str = "") -> dict:
        """Deterministically verify an SQL query for silent failures (NULL
        semantics, cartesian joins, missing date scope, schema errors).
        Returns verdict, confidence, and a diagnosis per problem."""
        return verify_payload(sql, question=question, dialect=dialect,
                              connector=connector, policy=policy)

    def fix_sql(sql: str, question: str = "") -> dict:
        """Verify an SQL query AND auto-repair deterministic bugs, then
        re-verify. Returns corrected SQL ready to execute. Prefer this
        before running any query."""
        return fix_payload(sql, question=question, dialect=dialect,
                           connector=connector, policy=policy)

    return [
        FunctionTool.from_defaults(fn=verify_sql, name="verify_sql"),
        FunctionTool.from_defaults(fn=fix_sql, name="fix_sql"),
    ]
